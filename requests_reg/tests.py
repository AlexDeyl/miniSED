"""
Тесты регламентных заявок: маршрутизация, согласование, двухэтапное
исполнение юротделом, ручной выбор согласующего, API.
"""

from datetime import date, datetime, timedelta
from unittest import mock
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import CFO, Facility, Organization
from core.models import AuditLog, Role, UserProfile
from documents import services as docsvc
from . import constants as C
from . import routing, services, validators
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

    def _req(self, cfo=None, facility=None, request_type=C.TYPE_POA):
        return services.create_request(
            request_type=request_type, organization=self.org, cfo=cfo, facility=facility,
            initiator_b24_id=1,
        )

    def test_base_route_always_roles(self):
        route = routing.build_route(self._req())
        codes = [s["role_code"] for s in route]
        # без ЦФО: всегда — руководитель ЦФО, финдиректор, юротдел.
        # ГД в маршруте доверенности НЕТ: он подписывает её на бумаге.
        self.assertEqual(codes, [
            C.ROLE_CFO_HEAD, C.ROLE_FINANCE_DIRECTOR, C.ROLE_LEGAL_DEPT,
        ])

    def test_poa_route_has_no_final_signer(self):
        """Обычную доверенность ГД подписывает вживую, на бумаге, — в
        электронном маршруте его быть не должно."""
        codes = [s["role_code"] for s in routing.build_route(self._req())]
        self.assertNotIn(C.ROLE_FINAL_SIGNER, codes)

    def test_mchd_keeps_final_signer(self):
        """ГД остаётся согласующим только у МЧД: обычную доверенность он
        подписывает на бумаге, а в маршруте ЭЦП его по ТЗ нет вовсе."""
        codes = [s["role_code"] for s in
                 routing.build_route(self._req(request_type=C.TYPE_MCHD))]
        self.assertIn(C.ROLE_FINAL_SIGNER, codes)
        # и он последний в маршруте — подписант замыкает согласование
        self.assertEqual(codes[-1], C.ROLE_FINAL_SIGNER)

    def test_sales_category_adds_sales_head(self):
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=self.cfo_sales))]
        self.assertIn(C.ROLE_SALES_HEAD, codes)

    def test_it_category_adds_tech_director(self):
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=self.cfo_it))]
        self.assertIn(C.ROLE_TECH_DIRECTOR, codes)

    def test_nevesomost_adds_restaurant_director(self):
        """«Проект Невесомость» — это ЮРЛИЦО: у него рестораны и своя
        ресторанная служба. Раньше правило смотрело только на объект (отель) и
        не срабатывало никогда, потому что Невесомость заведена юрлицом."""
        nev = Organization.objects.create(short_name='ООО "Невесомость"')
        req = services.create_request(
            request_type=C.TYPE_POA, organization=nev, initiator_b24_id=1,
        )
        codes = [s["role_code"] for s in routing.build_route(req)]
        self.assertIn(C.ROLE_RESTAURANT_DIRECTOR, codes)

    def test_nevesomost_facility_still_works(self):
        """Объект с таким названием тоже может появиться — его не теряем."""
        fac = Facility.objects.create(name="Невесомость", organization=self.org)
        codes = [s["role_code"] for s in routing.build_route(self._req(facility=fac))]
        self.assertIn(C.ROLE_RESTAURANT_DIRECTOR, codes)

    def test_restaurant_cfo_adds_restaurant_director(self):
        cfo = CFO.objects.create(name="Ресторанная служба", organization=self.org,
                                 category="restaurant")
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=cfo))]
        self.assertIn(C.ROLE_RESTAURANT_DIRECTOR, codes)

    def test_its_it_does_not_call_ops_director(self):
        """ИТС и ИТ ведёт только технический директор: операционному эти
        заявки падать не должны (уточнение заказчика)."""
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=self.cfo_it))]
        self.assertIn(C.ROLE_TECH_DIRECTOR, codes)
        self.assertNotIn(C.ROLE_OPS_DIRECTOR, codes)

    def test_reception_calls_ops_director(self):
        """СПиР — зона операционного директора, техдиректор не нужен."""
        cfo = CFO.objects.create(name="СПиР Отель Введенский", organization=self.org,
                                 category="reception")
        codes = [s["role_code"] for s in routing.build_route(self._req(cfo=cfo))]
        self.assertIn(C.ROLE_OPS_DIRECTOR, codes)
        self.assertNotIn(C.ROLE_TECH_DIRECTOR, codes)

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
        # роль cfo_head не имеет назначения -> ручной выбор, должен залогироваться
        services.submit(req, [internal(77, 0, C.ROLE_CFO_HEAD)])
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
        # доверенность: ГД подписывает на бумаге, в маршруте его нет
        self.assertNotIn(C.ROLE_FINAL_SIGNER, codes)

    def test_route_preview_mchd_keeps_final_signer(self):
        rid = api(1).post("/api/reg/requests/", {
            "request_type": "mchd", "organization": self.org.id, "subject_name": "Petrov",
        }, format="json").json()["id"]
        data = api(1).get(f"/api/reg/requests/{rid}/route_preview/").json()
        self.assertIn(C.ROLE_FINAL_SIGNER, [s["role_code"] for s in data["route"]])

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

    # --- поиск ---
    def _mk_poa(self, subject, number, status="to_legal", **data):
        req = RegulatoryRequest.objects.create(
            request_type="poa", organization=self.org, initiator_b24_id=1,
            subject_name=subject, status=status, data=data,
        )
        req.number = number
        req.save(update_fields=["number"])
        return req

    def test_search_by_fio_number_and_anketa(self):
        """Ищем так, как помнят заявку: ФИО, номер, паспорт из анкеты."""
        petrov = self._mk_poa("Петров Пётр Петрович", "ДОВ-000001",
                              rep={"passport": "4011 123456", "position": "Курьер"})
        self._mk_poa("Сидоров Сидор", "ДОВ-000002")

        def found(q):
            r = api(30).get(f"/api/reg/requests/legal_queue/?q={q}")
            self.assertEqual(r.status_code, 200, r.content)
            return {x["id"] for x in r.json()}

        self.assertEqual(found("Петров"), {petrov.id})
        self.assertEqual(found("ДОВ-000001"), {petrov.id})
        self.assertEqual(found("123456"), {petrov.id})        # паспорт из анкеты
        self.assertEqual(found("Ленин"), set())

    def test_search_by_attached_file(self):
        """Готовую доверенность юрист прикладывает файлом — по имени файла и
        названию документа заявка должна находиться."""
        req = self._mk_poa("Кузнецов Кузьма", "ДОВ-000060", status="closed")
        other = self._mk_poa("Иванов Иван", "ДОВ-000061", status="closed")
        doc = docsvc.create_document(title="Скан доверенности", linked_object=req)
        docsvc.add_version(doc, SimpleUploadedFile("dov-77-2026.pdf", b"scan"))

        def found(q):
            return {x["id"] for x in api(30).get(
                f"/api/reg/requests/legal_queue/?q={q}").json()}

        self.assertEqual(found("dov-77-2026"), {req.id})     # имя файла
        self.assertEqual(found("dov-77-2026.pdf"), {req.id})
        self.assertNotIn(other.id, found("dov-77"))
        # заявка не задваивается, даже если версий несколько
        docsvc.add_version(doc, SimpleUploadedFile("dov-77-2026.pdf", b"scan v2"))
        self.assertEqual(len(api(30).get(
            "/api/reg/requests/legal_queue/?q=dov-77-2026").json()), 1)

    def test_search_skips_deleted_files(self):
        """Удалённый файл не должен вытаскивать заявку в результаты."""
        req = self._mk_poa("Кузнецов", "ДОВ-000070", status="closed")
        doc = docsvc.create_document(title="Скан", linked_object=req)
        docsvc.add_version(doc, SimpleUploadedFile("secret-file.pdf", b"x"))
        doc.deleted_at = timezone.now()
        doc.save(update_fields=["deleted_at"])

        r = api(30).get("/api/reg/requests/legal_queue/?q=secret-file")
        self.assertEqual(r.json(), [])

    @skipUnless(
        connection.vendor == "postgresql",
        "LIKE в SQLite регистронезависим только для ASCII; в бою Postgres (ILIKE)",
    )
    def test_search_cyrillic_case_and_anketa(self):
        r"""На Postgres (боевая СУБД) кириллица ищется без учёта регистра, в том
        числе внутри анкеты: ILIKE + jsonb::text отдают настоящий UTF-8.

        В SQLite оба сценария не работают в принципе: LIKE регистронезависим
        только для ASCII, а JSON хранится с \uXXXX-экранированием."""
        petrov = self._mk_poa("Петров Пётр", "ДОВ-000050",
                              rep={"position": "Курьер"})

        def found(q):
            return {x["id"] for x in api(30).get(
                f"/api/reg/requests/legal_queue/?q={q}").json()}

        self.assertEqual(found("петров"), {petrov.id})   # регистр не важен
        self.assertEqual(found("ПЕТРОВ"), {petrov.id})
        self.assertEqual(found("курьер"), {petrov.id})   # должность из анкеты

    def test_search_terms_are_and(self):
        """Несколько слов сужают выборку, а не расширяют."""
        a = self._mk_poa("Петров Пётр", "ДОВ-000010")
        self._mk_poa("Петров Иван", "ДОВ-000011")

        r = api(30).get("/api/reg/requests/legal_queue/?q=Петров Пётр")
        self.assertEqual({x["id"] for x in r.json()}, {a.id})

    def test_search_ignores_tab_but_not_drafts(self):
        """Дубль ищут не зная статуса: поиск идёт по всем статусам, кроме
        черновиков (чужой черновик — ещё не заявка)."""
        closed = self._mk_poa("Петров", "ДОВ-000020", status="closed")
        draft = self._mk_poa("Петров", "ДОВ-000021", status="draft")

        # вкладка «Новые», а находим закрытую
        r = api(30).get("/api/reg/requests/legal_queue/?scope=new&q=Петров")
        ids = {x["id"] for x in r.json()}
        self.assertIn(closed.id, ids)
        self.assertNotIn(draft.id, ids)

    def test_search_survives_cp1251_from_perimeter(self):
        """Периметр перекодирует кириллицу в query в CP1251 — поиск обязан
        пережить это (тот же гоча, что у подсказок адреса)."""
        petrov = self._mk_poa("Петров Пётр", "ДОВ-000030")
        cp1251 = "".join(f"%{b:02X}" for b in "Петров".encode("cp1251"))

        r = api(30).get(f"/api/reg/requests/legal_queue/?q={cp1251}")
        self.assertEqual({x["id"] for x in r.json()}, {petrov.id})

    def test_search_in_own_requests_section(self):
        """В разделе «Регламентные заявки» ищем среди своих."""
        mine = self._mk_poa("Петров", "ДОВ-000040", status="on_approval")
        RegulatoryRequest.objects.create(
            request_type="poa", organization=self.org, initiator_b24_id=777,
            subject_name="Петров", status="on_approval",
        )
        r = api(1).get("/api/reg/requests/?q=Петров")
        self.assertEqual({x["id"] for x in r.json()}, {mine.id})

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


class MchdIdentifiersTests(TestCase):
    """ИНН и СНИЛС представителя обязательны для МЧД: по ним ФНС опознаёт
    представителя, и без них доверенность не примут."""

    VALID = {"inn": "500100732259", "snils": "112-233-445 95"}

    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    # --- сами проверки контрольных разрядов ---
    def test_inn_checksum(self):
        self.assertTrue(validators.is_valid_inn("500100732259"))
        self.assertFalse(validators.is_valid_inn("500100732250"))  # битый разряд
        self.assertFalse(validators.is_valid_inn("5001007322"))    # 10 цифр — это ИНН юрлица
        self.assertFalse(validators.is_valid_inn(""))

    def test_snils_checksum_and_format(self):
        self.assertTrue(validators.is_valid_snils("112-233-445 95"))
        self.assertTrue(validators.is_valid_snils("11223344595"))  # без разделителей
        self.assertFalse(validators.is_valid_snils("112-233-445 96"))
        self.assertFalse(validators.is_valid_snils("112-233-445"))
        self.assertEqual(validators.format_snils("11223344595"), "112-233-445 95")

    def test_snils_without_checksum_range(self):
        """Номера до 001-001-998 выданы без контрольного числа."""
        self.assertTrue(validators.is_valid_snils("001-001-998 00"))

    # --- API: создание заявки ---
    def _post(self, rtype, rep):
        return api(1).post("/api/reg/requests/", {
            "request_type": rtype, "organization": self.org.id,
            "subject_name": "Петров", "data": {"rep": rep},
        }, format="json")

    def test_mchd_accepted_without_identifiers(self):
        """На Госуслугах ИНН и СНИЛС для МЧД не требуют — пустые поля не ошибка."""
        self.assertEqual(self._post("mchd", {}).status_code, 201)
        self.assertEqual(self._post("mchd", {"inn": self.VALID["inn"]}).status_code, 201)
        self.assertEqual(self._post("mchd", {"snils": self.VALID["snils"]}).status_code, 201)

    def test_typo_still_rejected(self):
        """Заполнил — значит проверяем: опечатку ФНС всё равно не пропустит."""
        r = self._post("mchd", {"snils": "112-233-445 96"})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("СНИЛС", str(r.json()))

    def test_mchd_rejected_on_typo(self):
        r = self._post("mchd", {"inn": "500100732250", "snils": self.VALID["snils"]})
        self.assertEqual(r.status_code, 400, r.content)

    def test_mchd_accepted_with_valid_identifiers(self):
        r = self._post("mchd", dict(self.VALID))
        self.assertEqual(r.status_code, 201, r.content)

    def test_poa_does_not_require_identifiers(self):
        """Бумажную доверенность удостоверяет паспорт — ИНН/СНИЛС не нужны."""
        r = self._post("poa", {"last_name": "Петров"})
        self.assertEqual(r.status_code, 201, r.content)

    def test_patch_without_anketa_not_blocked(self):
        """PATCH одного поля не должен спотыкаться о проверку анкеты."""
        rid = self._post("mchd", dict(self.VALID)).json()["id"]
        r = api(1).patch(f"/api/reg/requests/{rid}/", {"comment": "уточнение"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.content)

    # --- гейт на отправке (заявка могла быть создана в обход анкеты) ---
    def test_submit_allowed_without_identifiers(self):
        """Заявку без ИНН/СНИЛС отправить можно — поля не обязательные."""
        req = services.create_request(
            request_type=C.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
        )
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_ON_APPROVAL)

    def test_submit_blocked_on_typo(self):
        """А вот заполненный с ошибкой ИНН отправку останавливает."""
        req = services.create_request(
            request_type=C.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
            data={"rep": {"inn": "500100732250"}},
        )
        with self.assertRaises(services.RequestError) as ctx:
            services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        self.assertIn("ИНН", str(ctx.exception))
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_DRAFT)

    def test_submit_passes_with_identifiers(self):
        req = services.create_request(
            request_type=C.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
            data={"rep": dict(self.VALID)},
        )
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_ON_APPROVAL)


class RequestScopeTests(TestCase):
    """?scope=participant — заявки, где я согласующий: этим живёт рабочее
    место визирования (раздел показывает всё, что проходило через меня)."""

    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def _submitted(self, initiator, approver):
        req = services.create_request(
            request_type=C.TYPE_POA, organization=self.org,
            initiator_b24_id=initiator, subject_name="Петров",
        )
        services.submit(req, [internal(approver, 0, C.ROLE_CFO_HEAD)])
        return req

    def _ids(self, uid, scope):
        r = api(uid).get(f"/api/reg/requests/?scope={scope}")
        self.assertEqual(r.status_code, 200, r.content)
        return {x["id"] for x in r.json()}

    def test_participant_sees_foreign_request(self):
        req = self._submitted(initiator=1, approver=20)
        self.assertEqual(self._ids(20, "participant"), {req.id})
        # в своём разделе «Регламентные заявки» её быть не должно — она чужая
        self.assertEqual(self._ids(20, "mine"), set())

    def test_initiator_not_listed_as_participant(self):
        self._submitted(initiator=1, approver=20)
        self.assertEqual(self._ids(1, "participant"), set())

    def test_scope_all_is_union(self):
        foreign = self._submitted(initiator=1, approver=20)
        own = self._submitted(initiator=20, approver=30)
        self.assertEqual(self._ids(20, "all"), {foreign.id, own.id})

    def test_default_scope_unchanged(self):
        """Без scope раздел «Регламентные заявки» по-прежнему показывает свои."""
        self._submitted(initiator=1, approver=20)
        own = self._submitted(initiator=20, approver=30)
        r = api(20).get("/api/reg/requests/")
        self.assertEqual({x["id"] for x in r.json()}, {own.id})

    def test_lawyer_sees_group_legal_stage(self):
        """Групповой юр-этап засчитывается всему юротделу, а не одному юристу."""
        lawyer = UserProfile.objects.create(fio="Юрист", bitrix_id=31, is_active=True)
        lawyer.roles.add(Role.objects.get(code="lawyer"))
        req = services.create_request(
            request_type=C.TYPE_POA, organization=self.org,
            initiator_b24_id=1, subject_name="Петров",
        )
        services.submit(req, [{
            "type": "internal", "b24_user_id": None, "order": 0,
            "role": C.ROLE_LEGAL_DEPT,
        }])
        self.assertEqual(self._ids(31, "participant"), {req.id})


class MachineReadableDetectionTests(TestCase):
    """«МЧД» в форме говорится в трёх местах: тип заявки, тип доверенности и
    форма выдачи. Требование об ИНН/СНИЛС должно срабатывать по любому из них —
    иначе доверенность, поданная как обычная, но машиночитаемая по анкете,
    уходила бы к юристам без реквизитов, которых требует ФНС."""

    VALID = {"inn": "500100732259", "snils": "112-233-445 95"}

    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def test_detection_rule(self):
        mr = validators.is_machine_readable
        self.assertTrue(mr(C.TYPE_MCHD, {}))
        self.assertTrue(mr(C.TYPE_POA, {"poa_type": "mchd"}))
        self.assertTrue(mr(C.TYPE_POA, {"form": "mchd"}))
        self.assertFalse(mr(C.TYPE_POA, {"poa_type": "special", "form": "standard"}))
        self.assertFalse(mr(C.TYPE_POA, None))

    def _post(self, data):
        return api(1).post("/api/reg/requests/", {
            "request_type": "poa", "organization": self.org.id,
            "subject_name": "Петров", "data": data,
        }, format="json")

    def test_poa_with_mchd_type_checks_filled_identifiers(self):
        """Признак машиночитаемости включает проверку, но не обязательность."""
        self.assertEqual(self._post({"poa_type": "mchd", "rep": {}}).status_code, 201)
        r = self._post({"poa_type": "mchd", "rep": {"inn": "500100732250"}})
        self.assertEqual(r.status_code, 400, r.content)

    def test_poa_with_mchd_form_checks_filled_identifiers(self):
        r = self._post({"form": "mchd", "rep": {"snils": "112-233-445 96"}})
        self.assertEqual(r.status_code, 400, r.content)

    def test_plain_poa_still_free(self):
        r = self._post({"poa_type": "special", "rep": {}})
        self.assertEqual(r.status_code, 201, r.content)

    def test_poa_with_mchd_type_accepted_when_filled(self):
        r = self._post({"poa_type": "mchd", "rep": dict(self.VALID)})
        self.assertEqual(r.status_code, 201, r.content)

    def test_submit_gate_uses_same_rule(self):
        req = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=1,
            data={"poa_type": "mchd", "rep": {"snils": "112-233-445 96"}},
        )
        with self.assertRaises(services.RequestError):
            services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])


class EcpRouteAndExecutionTests(TestCase):
    """Заявка на ЭЦП: маршрут короче доверенности, а исполняет её не юротдел,
    а ИТ-специалист объекта (ТЗ «Базовый маршрут ЭЦП»)."""

    IT = 700
    INITIATOR = 1

    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")
        self.hotel = Facility.objects.create(name="Отель Введенский", organization=self.org)
        self.cfo_sales = CFO.objects.create(name="Продажи", organization=self.org, category="sales")
        RoleAssignment.objects.create(
            role_code=C.ROLE_IT_SPECIALIST, facility=self.hotel,
            user_b24_id=self.IT, user_name="ИТ-специалист",
        )

    def _ecp(self, cfo=None):
        return services.create_request(
            request_type=C.TYPE_ECP, organization=self.org, facility=self.hotel,
            cfo=cfo, initiator_b24_id=self.INITIATOR, subject_name="Петров",
        )

    # --- маршрут ---
    def test_route_is_cfo_head_only(self):
        """Без ЦФО-условий маршрут ЭЦП — один руководитель ЦФО: ни финдиректора,
        ни юротдела, ни ГД в нём нет."""
        codes = [s["role_code"] for s in routing.build_route(self._ecp())]
        self.assertEqual(codes, [C.ROLE_CFO_HEAD])

    def test_conditional_roles_still_apply(self):
        codes = [s["role_code"] for s in routing.build_route(self._ecp(cfo=self.cfo_sales))]
        self.assertEqual(codes, [C.ROLE_CFO_HEAD, C.ROLE_SALES_HEAD])

    def test_poa_route_unchanged(self):
        """Доверенность свой маршрут не потеряла — финдиректор и юротдел на месте."""
        poa = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=1,
        )
        codes = [s["role_code"] for s in routing.build_route(poa)]
        self.assertEqual(codes, [C.ROLE_CFO_HEAD, C.ROLE_FINANCE_DIRECTOR, C.ROLE_LEGAL_DEPT])

    def test_mchd_keeps_final_signer_ecp_does_not(self):
        mchd = services.create_request(
            request_type=C.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
            data={"rep": {"inn": "500100732259", "snils": "112-233-445 95"}},
        )
        self.assertIn(C.ROLE_FINAL_SIGNER,
                      [s["role_code"] for s in routing.build_route(mchd)])
        self.assertNotIn(C.ROLE_FINAL_SIGNER,
                         [s["role_code"] for s in routing.build_route(self._ecp())])

    # --- исполнение ---
    def test_approved_ecp_goes_to_it_not_legal(self):
        req = self._ecp()
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "approve")
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_TO_IT)

    def test_full_execution_cycle(self):
        req = self._ecp()
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "approve")

        r = api(self.IT).post(f"/api/reg/requests/{req.id}/it_take/", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_IT_WORK)
        self.assertEqual(req.executor_b24_id, self.IT)

        r = api(self.IT).post(f"/api/reg/requests/{req.id}/it_execute/",
                              {"comment": "выдана"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_EXECUTED)
        self.assertIsNotNone(req.executed_at)

        # инициатор подтверждает получение — заявка закрывается
        services.confirm_receipt(req, by_b24_id=self.INITIATOR)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_CLOSED)

    def test_queue_and_card_closed_for_strangers(self):
        req = self._ecp()
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "approve")

        self.assertEqual(api(self.IT).get("/api/reg/requests/it_queue/").status_code, 200)
        self.assertEqual(api(999).get("/api/reg/requests/it_queue/").status_code, 403)
        # посторонний не исполнит и не откроет карточку
        self.assertEqual(
            api(999).post(f"/api/reg/requests/{req.id}/it_take/", {}, format="json").status_code,
            404,
        )
        self.assertEqual(api(self.IT).get(f"/api/reg/requests/{req.id}/").status_code, 200)

    def test_it_queue_holds_only_ecp(self):
        """Доверенности в очередь ИТ не попадают — у них свой раздел."""
        poa = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=1,
        )
        services.submit(poa, [internal(10, 0, C.ROLE_CFO_HEAD)])
        pid = services.get_approval(poa).rounds.first().participants.first().id
        services.decide(poa, pid, "approve")
        poa.refresh_from_db()
        self.assertEqual(poa.status, C.STATUS_TO_LEGAL)

        ids = {x["id"] for x in api(self.IT).get(
            "/api/reg/requests/it_queue/?scope=all").json()}
        self.assertNotIn(poa.id, ids)

    def test_it_cannot_execute_foreign_type(self):
        poa = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=1,
        )
        with self.assertRaises(services.RequestError):
            services.it_take_in_work(poa, by_b24_id=self.IT)


class MchdPlaceholderTests(TestCase):
    """Прочерк в графе ИНН/СНИЛС — это «значения нет», а не ошибка.

    Для МЧД через Госуслуги эти данные не нужны, и в бумажных бланках туда
    ставят прочерк; человек повторяет привычку в форме."""

    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def _post(self, rep):
        return api(1).post("/api/reg/requests/", {
            "request_type": "mchd", "organization": self.org.id,
            "subject_name": "Петров", "data": {"rep": rep},
        }, format="json")

    def test_placeholders_accepted(self):
        for value in ("—", "-", "нет", "н/д", "прочерк", "  "):
            with self.subTest(value=value):
                self.assertTrue(validators.is_placeholder(value))
                self.assertEqual(self._post({"inn": value, "snils": value}).status_code, 201)

    def test_digits_still_checked(self):
        """Появились цифры — значит человек вводил номер, и опечатку ловим."""
        self.assertFalse(validators.is_placeholder("500100732250"))
        self.assertEqual(self._post({"inn": "500100732250"}).status_code, 400)
        # частично введённый номер — тоже ошибка, а не «прочерк»
        self.assertEqual(self._post({"snils": "112-233"}).status_code, 400)

    def test_submit_passes_with_placeholders(self):
        req = services.create_request(
            request_type=C.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
            data={"rep": {"inn": "—", "snils": "—"}},
        )
        services.submit(req, [internal(10, 0, C.ROLE_CFO_HEAD)])
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_ON_APPROVAL)

class RevokeRequestTests(TestCase):
    """Заявка на отзыв доверенности/МЧД.

    Маршрут — один руководитель ЦФО; если он же и подаёт заявку, согласования
    нет вовсе и заявка уходит прямо юристам. Отзываемая доверенность
    привязывается карточкой, а для бумажной (выданной до MiniSED) — реквизитами
    вручную."""

    CFO_HEAD = 501
    EMPLOYEE = 502

    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")
        self.cfo = CFO.objects.create(name="Продажи", organization=self.org, category="sales")
        RoleAssignment.objects.create(
            role_code=C.ROLE_CFO_HEAD, cfo=self.cfo,
            user_b24_id=self.CFO_HEAD, user_name="Руководитель ЦФО",
        )
        # доверенность, которую будем отзывать (уже выдана)
        self.poa = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, cfo=self.cfo,
            initiator_b24_id=self.EMPLOYEE, subject_name="Петров П.П.",
        )
        self.poa.status = C.STATUS_EXECUTED
        self.poa.save(update_fields=["status"])

    def _revoke(self, initiator, *, source=True, data=None):
        payload = {"revoke_reason": "dismissal", "revoke_date": "2026-09-10"}
        payload.update(data or {})
        return services.create_request(
            request_type=C.TYPE_REVOKE, organization=self.org, cfo=self.cfo,
            initiator_b24_id=initiator, subject_name=self.poa.subject_name,
            source_request=self.poa if source else None, data=payload,
        )

    # --- маршрут ---
    def test_route_is_cfo_head_only(self):
        route = routing.build_route(self._revoke(self.EMPLOYEE))
        self.assertEqual([s["role_code"] for s in route], [C.ROLE_CFO_HEAD])
        self.assertEqual(route[0]["b24_user_id"], self.CFO_HEAD)

    def test_route_empty_for_cfo_head(self):
        """Руководитель ЦФО сам себе согласующим не нужен."""
        req = self._revoke(self.CFO_HEAD)
        self.assertEqual(routing.build_route(req), [])
        self.assertTrue(routing.approval_free(req))

    def test_other_cfo_head_does_not_skip_approval(self):
        """Руководитель СОСЕДНЕГО ЦФО согласование не отменяет."""
        other = CFO.objects.create(name="Бухгалтерия", organization=self.org, category="accounting")
        RoleAssignment.objects.create(
            role_code=C.ROLE_CFO_HEAD, cfo=other, user_b24_id=999, user_name="Другой",
        )
        req = self._revoke(999)
        self.assertFalse(routing.approval_free(req))
        self.assertEqual([s["role_code"] for s in routing.build_route(req)], [C.ROLE_CFO_HEAD])

    def test_poa_route_unchanged(self):
        """Маршрут самой доверенности отзыв не задел."""
        codes = [s["role_code"] for s in routing.build_route(self.poa)]
        self.assertIn(C.ROLE_LEGAL_DEPT, codes)
        self.assertIn(C.ROLE_FINANCE_DIRECTOR, codes)

    # --- отправка ---
    def test_cfo_head_submit_goes_straight_to_legal(self):
        req = self._revoke(self.CFO_HEAD)
        services.submit(req, [], actor_b24_id=self.CFO_HEAD)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_TO_LEGAL)
        # круга согласования не создаётся вовсе — печатать было бы нечего
        self.assertIsNone(services.get_approval(req))
        self.assertTrue(
            AuditLog.objects.filter(action="request_submitted_without_approval").exists()
        )

    def test_employee_submit_needs_cfo_head_approval(self):
        req = self._revoke(self.EMPLOYEE)
        services.submit(req, [internal(self.CFO_HEAD, role=C.ROLE_CFO_HEAD)],
                        actor_b24_id=self.EMPLOYEE)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_ON_APPROVAL)
        pending = services.current_pending_participant(services.get_approval(req))
        self.assertEqual(pending.b24_user_id, self.CFO_HEAD)

    def test_approved_revoke_goes_to_legal(self):
        req = self._revoke(self.EMPLOYEE)
        services.submit(req, [internal(self.CFO_HEAD, role=C.ROLE_CFO_HEAD)],
                        actor_b24_id=self.EMPLOYEE)
        pending = services.current_pending_participant(services.get_approval(req))
        services.decide(req, pending.id, "approve", actor_b24_id=self.CFO_HEAD)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_TO_LEGAL)

    def test_empty_route_rejected_for_ordinary_initiator(self):
        """Пустой маршрут — привилегия руководителя ЦФО, а не всех подряд."""
        req = self._revoke(self.EMPLOYEE)
        with self.assertRaises(services.RequestError):
            services.submit(req, [], actor_b24_id=self.EMPLOYEE)

    # --- что именно отзываем ---
    def test_source_required(self):
        req = self._revoke(self.CFO_HEAD, source=False)
        with self.assertRaises(services.RequestError):
            services.submit(req, [], actor_b24_id=self.CFO_HEAD)

    def test_manual_source_accepted(self):
        """Бумажная доверенность до MiniSED: карточки нет, есть реквизиты."""
        req = self._revoke(
            self.CFO_HEAD, source=False,
            data={"source": {"kind": C.TYPE_POA, "number": "12/2023",
                             "issued_at": "2023-05-01", "subject_name": "Сидоров"}},
        )
        services.submit(req, [], actor_b24_id=self.CFO_HEAD)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_TO_LEGAL)

    def test_reason_required(self):
        req = self._revoke(self.CFO_HEAD, data={"revoke_reason": ""})
        with self.assertRaises(services.RequestError):
            services.submit(req, [], actor_b24_id=self.CFO_HEAD)

    def test_other_reason_needs_text(self):
        req = self._revoke(self.CFO_HEAD, data={"revoke_reason": "other"})
        with self.assertRaises(services.RequestError):
            services.submit(req, [], actor_b24_id=self.CFO_HEAD)
        req.data["revoke_reason_text"] = "переезд представителя"
        req.save(update_fields=["data"])
        services.submit(req, [], actor_b24_id=self.CFO_HEAD)
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_TO_LEGAL)

    # --- связка карточек и API ---
    def test_link_visible_from_both_sides(self):
        req = self._revoke(self.EMPLOYEE)
        c = api(self.EMPLOYEE)
        revoke_card = c.get(f"/api/reg/requests/{req.id}/").json()
        self.assertEqual(revoke_card["source_request_info"]["number"], self.poa.number)
        poa_card = c.get(f"/api/reg/requests/{self.poa.id}/").json()
        self.assertEqual([r["number"] for r in poa_card["revocations"]], [req.number])

    def test_cannot_link_non_revocable(self):
        ecp = services.create_request(
            request_type=C.TYPE_ECP, organization=self.org, initiator_b24_id=self.EMPLOYEE,
        )
        resp = api(self.EMPLOYEE).post("/api/reg/requests/", {
            "request_type": C.TYPE_REVOKE, "organization": self.org.id,
            "source_request": ecp.id,
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_source_request_only_on_revoke(self):
        resp = api(self.EMPLOYEE).post("/api/reg/requests/", {
            "request_type": C.TYPE_POA, "organization": self.org.id,
            "source_request": self.poa.id,
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_revocable_list_shows_issued_poa_to_its_cfo_head(self):
        """Руководителю ЦФО видны доверенности его ЦФО — он отзывает их за
        уволившимся сотрудником, хотя заявку заводил не он."""
        resp = api(self.CFO_HEAD).get("/api/reg/requests/revocable/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.poa.id, [r["id"] for r in resp.json()])

    def test_revocable_list_hides_foreign_drafts(self):
        draft = services.create_request(
            request_type=C.TYPE_POA, organization=self.org, initiator_b24_id=self.EMPLOYEE,
            subject_name="Черновиков",
        )
        ids = [r["id"] for r in api(self.CFO_HEAD).get("/api/reg/requests/revocable/").json()]
        self.assertNotIn(draft.id, ids)

    def test_revoke_pdf_renders(self):
        from . import anketa_pdf

        pdf = anketa_pdf.render_pdf(self._revoke(self.EMPLOYEE))
        self.assertTrue(pdf.startswith(b"%PDF"))
