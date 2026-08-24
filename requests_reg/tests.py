"""
Тесты регламентных заявок: маршрутизация, согласование, двухэтапное
исполнение юротделом, ручной выбор согласующего, API.
"""

from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import CFO, Facility, Organization
from core.models import AuditLog, Role, UserProfile
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
        # b24=30 — юрист (роль lawyer c правом legal_manage): для юр-очереди/исполнения
        lawyer_role = Role.objects.get(code="lawyer")
        p = UserProfile.objects.create(fio="Юрист Юрьев", bitrix_id=30, is_active=True)
        p.roles.add(lawyer_role)

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

    def test_term_over_3_years_rejected(self):
        # доверенность более чем на 3 года — 400
        r = api(1).post("/api/reg/requests/", {
            "request_type": "poa", "organization": self.org.id, "subject_name": "Petrov",
            "data": {"term_type": "period", "term_from": "2026-01-01", "term_to": "2029-06-01"},
        }, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("3 года", str(r.json()))

    def test_term_within_3_years_ok(self):
        r = api(1).post("/api/reg/requests/", {
            "request_type": "poa", "organization": self.org.id, "subject_name": "Petrov",
            "data": {"term_type": "period", "term_from": "2026-01-01", "term_to": "2029-01-01"},
        }, format="json")
        self.assertEqual(r.status_code, 201)

    def test_detail_documents_include_versions(self):
        """Карточка отдаёт историю версий и признак онлайн-правки."""
        rid = self._create()
        r = api(1).post("/api/documents/", {
            "title": "Образец доверенности.docx",
            "linked_type": "requests_reg.regulatoryrequest", "linked_id": str(rid),
            "file": SimpleUploadedFile("f.docx", b"v1", content_type="application/octet-stream"),
        })
        self.assertEqual(r.status_code, 201, r.content)
        doc_id = r.json()["id"]
        api(1).post(f"/api/documents/{doc_id}/versions/", {
            "file": SimpleUploadedFile("f.docx", b"v2", content_type="application/octet-stream"),
            "change_comment": "уточнили полномочия",
        })

        doc = api(1).get(f"/api/reg/requests/{rid}/").json()["documents"][0]
        self.assertEqual(doc["current_version_number"], 2)
        self.assertEqual([v["version_number"] for v in doc["versions"]], [1, 2])
        self.assertEqual(doc["versions"][1]["change_comment"], "уточнили полномочия")
        self.assertIn("can_edit_online", doc)
        self.assertIn(f"/api/documents/{doc_id}/versions/", doc["download_url"])

    def test_types_includes_roles(self):
        data = api(1).get("/api/reg/requests/types/").json()
        codes = {r["code"] for r in data["roles"]}
        self.assertIn("legal_dept", codes)
        self.assertIn("cfo_head", codes)

    def test_sheet_pdf_endpoint(self):
        rid = self._create()
        api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": 20, "order": 0}],
        }, format="json")
        resp = api(1).get(f"/api/reg/requests/{rid}/sheet_pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(resp.streaming_content).startswith(b"%PDF"))

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

    # --- видимость ---
    def test_list_shows_only_my_requests(self):
        mine = self._create()  # api(1)
        api(2).post("/api/reg/requests/", {
            "request_type": "poa", "organization": self.org.id, "subject_name": "Чужой",
        }, format="json")
        data = api(1).get("/api/reg/requests/").json()
        ids = {r["id"] for r in data}
        self.assertIn(mine, ids)
        self.assertEqual(len(ids), 1)  # чужую не видно

    def test_retrieve_forbidden_for_stranger(self):
        rid = self._create()
        self.assertEqual(api(99).get(f"/api/reg/requests/{rid}/").status_code, 404)
        self.assertEqual(api(1).get(f"/api/reg/requests/{rid}/").status_code, 200)

    # --- инбокс «Требует действия» ---
    def test_todo_shows_for_current_approver_only(self):
        rid = self._create()
        api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": 20, "order": 0}],
        }, format="json")
        self.assertIn(rid, {r["id"] for r in api(20).get("/api/reg/requests/todo/").json()})
        self.assertNotIn(rid, {r["id"] for r in api(21).get("/api/reg/requests/todo/").json()})

    # --- групповой юрэтап ---
    def _submit_legal_group(self):
        rid = self._create()
        r = api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": None,
                              "role": C.ROLE_LEGAL_DEPT, "order": 0}],
        }, format="json")
        pid = r.json()["approval"]["rounds"][0]["participants"][0]["id"]
        return rid, pid

    def test_legal_group_visible_to_all_lawyers(self):
        rid, _ = self._submit_legal_group()
        self.assertIn(rid, {r["id"] for r in api(30).get("/api/reg/requests/todo/").json()})
        self.assertNotIn(rid, {r["id"] for r in api(21).get("/api/reg/requests/todo/").json()})

    def test_legal_group_any_lawyer_approves(self):
        rid, pid = self._submit_legal_group()
        # посторонний вообще не видит заявку
        self.assertEqual(api(21).post(f"/api/reg/requests/{rid}/decide/",
                         {"participant_id": pid, "decision": "approve"}, format="json").status_code, 404)
        # инициатор видит, но не юрист — согласовать юрэтап не может
        bad = api(1).post(f"/api/reg/requests/{rid}/decide/",
                          {"participant_id": pid, "decision": "approve"}, format="json")
        self.assertEqual(bad.status_code, 400)
        # юрист может; фиксируется его b24_id
        ok = api(30).post(f"/api/reg/requests/{rid}/decide/",
                          {"participant_id": pid, "decision": "approve"}, format="json")
        self.assertEqual(ok.status_code, 200)
        from approvalflow.models import ApprovalParticipant
        self.assertEqual(ApprovalParticipant.objects.get(id=pid).b24_user_id, 30)

    # --- ссылка в уведомлении ---
    def test_notification_carries_card_link(self):
        """Колокольчик Битрикса ведёт в карточку: ссылка спрятана за подписью
        «Перейти к согласованию», а не показана голым адресом."""
        from unittest import mock

        from django.test import override_settings

        from . import notifications

        req = RegulatoryRequest.objects.create(
            request_type="poa", organization=self.org, initiator_b24_id=1,
            status="to_legal",
        )
        with override_settings(BITRIX_APP_URL="https://portal.bitrix24.ru/marketplace/app/150/"):
            with mock.patch.object(notifications, "_bitrix_notify") as bell,                  mock.patch.object(notifications, "_email") as email:
                notifications.notify_legal_queue(req)

        link = f"https://portal.bitrix24.ru/marketplace/app/150/?to=%2Frequests%2F{req.id}"
        self.assertEqual(bell.call_args.kwargs["link"], link)
        self.assertEqual(bell.call_args.kwargs["link_text"], "Открыть заявку")
        # в письме ссылка идёт строкой — там BB-коды не работают
        self.assertIn(link, email.call_args[0][2])

    # --- права юр-очереди ---
    def test_legal_queue_requires_lawyer(self):
        self.assertEqual(api(21).get("/api/reg/requests/legal_queue/").status_code, 403)
        self.assertEqual(api(30).get("/api/reg/requests/legal_queue/").status_code, 200)

    def test_legal_queue_scopes(self):
        def mk(status):
            return RegulatoryRequest.objects.create(
                request_type="poa", organization=self.org, initiator_b24_id=1, status=status,
            ).id
        new_id, work_id, exec_id, closed_id = (
            mk("to_legal"), mk("legal_work"), mk("executed"), mk("closed"),
        )
        rejected_id, canceled_id, draft_id, appr_id = (
            mk("rejected"), mk("canceled"), mk("draft"), mk("on_approval"),
        )

        def ids(scope):
            return {r["id"] for r in api(30).get(
                f"/api/reg/requests/legal_queue/?scope={scope}").json()}

        self.assertEqual(ids("new"), {new_id})
        self.assertEqual(ids("work"), {work_id, exec_id})
        # архив — всё отработанное, включая отклонённые/отменённые
        self.assertEqual(ids("archive"), {closed_id, rejected_id, canceled_id})
        # «Все» — весь поток юротдела, кроме черновиков
        self.assertEqual(ids("all"), {
            new_id, work_id, exec_id, closed_id, rejected_id, canceled_id, appr_id,
        })
        self.assertNotIn(draft_id, ids("all"))

    # --- отмена и удаление ---
    def test_cancel_then_delete(self):
        rid = self._create()
        r = api(1).post(f"/api/reg/requests/{rid}/cancel/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "canceled")
        # удалить отменённую можно
        self.assertEqual(api(1).delete(f"/api/reg/requests/{rid}/").status_code, 204)
        self.assertEqual(api(1).get(f"/api/reg/requests/{rid}/").status_code, 404)

    def test_delete_only_when_canceled(self):
        rid = self._create()  # draft
        self.assertEqual(api(1).delete(f"/api/reg/requests/{rid}/").status_code, 403)

    def test_cancel_only_initiator(self):
        rid = self._create()
        # юрист видит заявку, но отменить может только инициатор
        self.assertEqual(api(30).post(f"/api/reg/requests/{rid}/cancel/").status_code, 403)

    def test_confirm_receipt_only_initiator(self):
        r = RegulatoryRequest.objects.create(
            request_type="poa", organization=self.org, initiator_b24_id=1, status="executed",
        )
        # юрист не закрывает заявку за инициатора
        self.assertEqual(api(30).post(f"/api/reg/requests/{r.id}/confirm_receipt/").status_code, 403)
        # инициатор — может
        resp = api(1).post(f"/api/reg/requests/{r.id}/confirm_receipt/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "closed")

    # --- уведомления ---
    def test_notify_legal_queue_targets_lawyers(self):
        from requests_reg import notifications
        r = RegulatoryRequest.objects.create(
            request_type="poa", organization=self.org, initiator_b24_id=1, status="to_legal",
        )
        with mock.patch.object(notifications, "_dispatch") as disp:
            notifications.notify_legal_queue(r)
        disp.assert_called_once()
        self.assertIn(30, disp.call_args.args[0])  # юрист из setUp

    def test_notify_initiator_executed(self):
        from requests_reg import notifications
        r = RegulatoryRequest.objects.create(
            request_type="poa", organization=self.org, initiator_b24_id=1, status="executed",
        )
        with mock.patch.object(notifications, "_dispatch") as disp:
            notifications.notify_initiator_executed(r)
        disp.assert_called_once()
        self.assertIn(1, disp.call_args.args[0])  # инициатор

    def test_flow_fires_notifications_on_commit(self):
        from requests_reg import notifications
        rid = self._create()
        with mock.patch.object(notifications, "_dispatch") as disp, \
                self.captureOnCommitCallbacks(execute=True):
            r = api(1).post(f"/api/reg/requests/{rid}/submit/", {
                "participants": [{"type": "internal", "b24_user_id": 20, "order": 0}],
            }, format="json")
            pid = r.json()["approval"]["rounds"][0]["participants"][0]["id"]
            api(20).post(f"/api/reg/requests/{rid}/decide/", {
                "participant_id": pid, "decision": "approve",
            }, format="json")
        # submit → уведомление согласующему; decide→to_legal → уведомление юристам
        self.assertTrue(disp.called)

    # --- перезапуск после отклонения ---
    def test_restart_after_reject(self):
        rid = self._create()
        r = api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": 20, "order": 0}],
        }, format="json")
        pid = r.json()["approval"]["rounds"][0]["participants"][0]["id"]
        api(20).post(f"/api/reg/requests/{rid}/decide/",
                     {"participant_id": pid, "decision": "reject", "comment": "нет"}, format="json")
        self.assertEqual(api(1).get(f"/api/reg/requests/{rid}/").json()["status"], "rejected")
        again = api(1).post(f"/api/reg/requests/{rid}/submit/", {
            "participants": [{"type": "internal", "b24_user_id": 22, "order": 0}],
        }, format="json")
        self.assertEqual(again.status_code, 200)


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
