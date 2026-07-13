"""
Тесты регламентных заявок: маршрутизация, согласование, двухэтапное
исполнение юротделом, ручной выбор согласующего, API.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import CFO, Facility, Organization
from core.models import AuditLog
from documents import services as docsvc
from . import constants as C
from . import routing, services
from .models import RegulatoryRequest, RoleAssignment


def api(uid=None):
    c = APIClient()
    if uid is not None:
        c.credentials(HTTP_X_B24_USER=str(uid))
    return c


def internal(uid, order=0, role=""):
    return {"type": "internal", "b24_user_id": uid, "order": order, "role": role}


class RoutingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")
        self.cfo_sales = CFO.objects.create(name="Продажи", organization=self.org, category="sales")
        self.cfo_it = CFO.objects.create(name="ИТ", organization=self.org, category="its_it")

    def _req(self, cfo=None, facility=None):
        return services.create_request(
            request_type=C.TYPE_POA, organization=self.org, cfo=cfo, facility=facility,
            initiator_b24_id=1,
        )

    def test_base_route_always_roles(self):
        route = routing.build_route(self._req())
        codes = [s["role_code"] for s in route]
        # без ЦФО: всегда — руководитель ЦФО, финдиректор, юротдел, финальный подписант
        self.assertEqual(codes, [
            C.ROLE_CFO_HEAD, C.ROLE_FINANCE_DIRECTOR, C.ROLE_LEGAL_DEPT, C.ROLE_FINAL_SIGNER,
        ])

    def test_sales_category_adds_sales_head(self):
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=self.cfo_sales))]
        self.assertIn(C.ROLE_SALES_HEAD, codes)

    def test_it_category_adds_tech_and_ops(self):
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=self.cfo_it))]
        self.assertIn(C.ROLE_TECH_DIRECTOR, codes)
        self.assertIn(C.ROLE_OPS_DIRECTOR, codes)

    def test_nevesomost_adds_restaurant_director(self):
        fac = Facility.objects.create(name="Невесомость", organization=self.org)
        codes = [s["role_code"] for s in routing.build_route(self._req(facility=fac))]
        self.assertIn(C.ROLE_RESTAURANT_DIRECTOR, codes)

    def test_role_resolution_and_manual_fallback(self):
        RoleAssignment.objects.create(
            role_code=C.ROLE_CFO_HEAD, cfo=self.cfo_sales, user_b24_id=500, user_name="Начальник"
        )
        route = routing.build_route(self._req(cfo=self.cfo_sales))
        cfo_slot = next(s for s in route if s["role_code"] == C.ROLE_CFO_HEAD)
        self.assertTrue(cfo_slot["resolved"])
        self.assertEqual(cfo_slot["b24_user_id"], 500)
        # финансовый директор не назначен -> ручной выбор
        fd_slot = next(s for s in route if s["role_code"] == C.ROLE_FINANCE_DIRECTOR)
        self.assertTrue(fd_slot["needs_manual"])


class FlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def _req(self):
        return services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=1,
            subject_name="Иванов",
        )

    def _attach_doc(self, req):
        doc = docsvc.create_document(title="Доверенность", linked_object=req)
        docsvc.add_version(doc, SimpleUploadedFile("dov.pdf", b"scan"))
        return doc

    def test_full_cycle_to_closed(self):
        req = self._req()
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_ON_APPROVAL)

        approval = services.get_approval(req)
        pid = approval.rounds.first().participants.first().id
        services.decide(req, pid, "approve")
        req.refresh_from_db()
        # финальное утверждение -> автопередача юристам
        self.assertEqual(req.status, C.STATUS_TO_LEGAL)

        services.take_in_work(req); req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_LEGAL_WORK)
        services.to_signing(req); req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_SIGNING)

        # исполнение без файла — ошибка
        with self.assertRaises(services.RequestError):
            services.execute(req, delivery_method="post")

        self._attach_doc(req)
        services.execute(req, delivery_method="post", delivery_comment="Почтой России")
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_EXECUTED)
        self.assertEqual(req.delivery_method, "post")
        self.assertIsNotNone(req.executed_at)

        services.confirm_receipt(req, by_b24_id=1)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_CLOSED)
        self.assertIsNotNone(req.received_at)

    def test_execute_requires_delivery_method(self):
        req = self._req()
        services.submit(req, [internal(10)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "approve")
        services.take_in_work(req)
        self._attach_doc(req)
        with self.assertRaises(services.RequestError):
            services.execute(req, delivery_method="")

    def test_reject(self):
        req = self._req()
        services.submit(req, [internal(10)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "reject", "нет оснований")
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_REJECTED)

    def test_manual_selection_logged(self):
        req = self._req()
        # роль final_signer не имеет назначения -> ручной выбор, должен залогироваться
        services.submit(req, [internal(77, 0, C.ROLE_FINAL_SIGNER)])
        self.assertTrue(
            AuditLog.objects.filter(action="manual_approver_selected").exists()
        )


class ApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def _create(self):
        return api(1).post("/api/reg/requests/", {
            "request_type": "poa", "organization": self.org.id, "subject_name": "Petrov",
        }, format="json").json()["id"]

    def test_route_preview(self):
        rid = self._create()
        data = api(1).get(f"/api/reg/requests/{rid}/route_preview/").json()
        codes = [s["role_code"] for s in data["route"]]
        self.assertIn(C.ROLE_CFO_HEAD, codes)
        self.assertIn(C.ROLE_FINAL_SIGNER, codes)

    def test_submit_decide_reaches_legal_queue(self):
        rid = self._create()
        r = api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": 20, "order": 0}],
        }, format="json")
        self.assertEqual(r.status_code, 200)
        pid = r.json()["approval"]["rounds"][0]["participants"][0]["id"]
        r = api(20).post(f"/api/reg/requests/{rid}/decide/", {
            "participant_id": pid, "decision": "approve",
        }, format="json")
        self.assertEqual(r.json()["status"], "to_legal")

        # появляется в очереди юристов
        queue = api(30).get("/api/reg/requests/legal_queue/").json()
        self.assertTrue(any(x["id"] == rid for x in queue))

    def test_power_templates(self):
        data = api(1).get("/api/reg/requests/power_templates/").json()
        codes = {t["code"] for t in data}
        self.assertIn("УПР1", codes)
        self.assertIn("ФНС1", codes)
        self.assertEqual(len(data), 16)

    def test_anketa_pdf_endpoint(self):
        rid = self._create()
        # заполним часть анкеты
        api(1).patch(f"/api/reg/requests/{rid}/", {
            "data": {
                "poa_type": "single", "urgency": "standard",
                "rep": {"last_name": "Иванов", "first_name": "Иван"},
                "powers": ["contracts", "acts"],
                "power_templates": ["УПР1"],
            },
        }, format="json")
        resp = api(1).get(f"/api/reg/requests/{rid}/anketa_pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(resp.streaming_content).startswith(b"%PDF"))

    def test_legal_execute_via_api(self):
        rid = self._create()
        r = api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": 20, "order": 0}],
        }, format="json")
        pid = r.json()["approval"]["rounds"][0]["participants"][0]["id"]
        api(20).post(f"/api/reg/requests/{rid}/decide/", {"participant_id": pid, "decision": "approve"}, format="json")

        api(30).post(f"/api/reg/requests/{rid}/take/")
        # прикрепить документ через documents API
        api(30).post("/api/documents/", {
            "title": "Доверенность",
            "linked_type": "requests_reg.regulatoryrequest",
            "linked_id": rid,
            "file": SimpleUploadedFile("d.pdf", b"scan"),
        }, format="multipart")
        r = api(30).post(f"/api/reg/requests/{rid}/execute/", {"delivery_method": "courier"}, format="json")
        self.assertEqual(r.json()["status"], "executed")

        r = api(1).post(f"/api/reg/requests/{rid}/confirm_receipt/")
        self.assertEqual(r.json()["status"], "closed")


class AnketaTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def test_submit_attaches_anketa_pdf(self):
        req = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=1,
            data={"poa_type": "general", "powers": ["court"], "power_templates": ["СУД1"]},
        )
        services.submit(req, [internal(10)])
        docs = req.documents.filter(document_type="anketa")
        self.assertEqual(docs.count(), 1)
        cur = docs.first().current_version
        cur.file.seek(0)
        self.assertTrue(cur.file.read(4) == b"%PDF")

    def test_render_pdf_bytes(self):
        from requests_reg.anketa_pdf import render_pdf
        req = services.create_request(
            request_type=C.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
            data={"poa_type": "mchd", "rep": {"last_name": "Петров"}},
        )
        pdf = render_pdf(req)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 800)
