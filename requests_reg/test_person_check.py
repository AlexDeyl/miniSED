"""
Тесты заявки на проверку лица: анкета, маршрут по типу лица, исполнение
службой безопасности (решение + отчёт) и передача функций СБ юристам.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import AuditLog, Facility, Organization, Role, UserProfile
from documents import services as docsvc

from . import check
from . import constants as C
from .models import RegulatoryRequest, RoleAssignment, SecurityDelegation

INITIATOR = 1
SECURITY = 40
LAWYER = 30
STRANGER = 99


def api(uid):
    c = APIClient()
    c.credentials(HTTP_X_B24_USER=str(uid))
    return c


def legal_data(**over):
    d = {
        "person_type": "legal", "urgency": "standard",
        "legal": {
            "name": "ООО Ромашка", "inn_ogrn": "7707083893", "direction": "supplier",
            "contract_kind": "standard", "place": "vvedensky", "other_info": "",
        },
        "coop_info": "",
    }
    d["legal"].update(over)
    return d


def individual_data(**over):
    d = {
        "person_type": "individual", "urgency": "urgent", "direction": "npd",
        "individual": {
            "last_name": "Иванов", "first_name": "Иван", "middle_name": "",
            "birth_date": "1990-01-02", "passport": "4010 123456",
            "position": "Фотограф", "place": "nevesomost",
        },
        "coop_info": "Съёмка мероприятий",
    }
    d["individual"].update(over)
    return d


class _CheckBase(TestCase):
    def setUp(self):
        self.uk = Organization.objects.create(short_name="ООО Управление Отелями")
        self.vved_org = Organization.objects.create(short_name="АО Отель Введенский")
        self.nev = Organization.objects.create(short_name="ООО Невесомость")
        self.vved = Facility.objects.create(name="Отель Введенский", organization=self.vved_org)
        RoleAssignment.objects.create(
            role_code=C.ROLE_SECURITY_ADVISOR, user_b24_id=SECURITY, user_name="Советник СБ",
        )
        p = UserProfile.objects.create(fio="Юрист Юрьев", bitrix_id=LAWYER, is_active=True)
        p.roles.add(Role.objects.get(code="lawyer"))

    # --- helpers ---
    def _create(self, data, uid=INITIATOR):
        return api(uid).post("/api/reg/requests/", {
            "request_type": "check", "data": data,
        }, format="json")

    def _submit(self, rid):
        route = api(INITIATOR).get(f"/api/reg/requests/{rid}/route_preview/").json()["route"]
        parts = [
            {"type": "internal", "b24_user_id": s["b24_user_id"], "role": s["role_code"], "order": i}
            for i, s in enumerate(route)
        ]
        r = api(INITIATOR).post(f"/api/reg/requests/{rid}/submit/", {"participants": parts}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def _approve(self, rid, uid):
        body = api(INITIATOR).get(f"/api/reg/requests/{rid}/").json()
        pid = body["approval"]["rounds"][-1]["participants"][0]["id"]
        return api(uid).post(f"/api/reg/requests/{rid}/decide/", {
            "participant_id": pid, "decision": "approve",
        }, format="json")

    def _report(self, rid, uid=SECURITY):
        req = RegulatoryRequest.objects.get(pk=rid)
        doc = docsvc.create_document(
            title="Отчёт", document_type=C.CHECK_REPORT_DOC_TYPE,
            linked_object=req, created_by_b24_id=uid,
        )
        docsvc.add_version(doc, SimpleUploadedFile("report.pdf", b"%PDF-1.4"), uploaded_by_b24_id=uid)

    def _approved_individual(self):
        rid = self._create(individual_data()).json()["id"]
        self._submit(rid)
        self.assertEqual(self._approve(rid, SECURITY).json()["status"], C.STATUS_APPROVED)
        return rid


class PersonCheckTests(_CheckBase):
    # --- анкета ---
    def test_create_legal_derives_org_facility_and_subject(self):
        r = self._create(legal_data())
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["status"], C.STATUS_DRAFT)
        self.assertTrue(body["number"].startswith("ПРВ-"))
        self.assertEqual(body["subject_name"], "ООО Ромашка")
        self.assertEqual(body["organization"], self.vved_org.id)
        self.assertEqual(body["facility"], self.vved.id)

    def test_nevesomost_is_organization_multiple_falls_back_to_uk(self):
        body = self._create(individual_data()).json()
        self.assertEqual(body["organization"], self.nev.id)
        self.assertEqual(body["subject_name"], "Иванов Иван")
        self.assertEqual(body["position"], "Фотограф")
        body = self._create(legal_data(place="multiple", other_info="Введенский и SAGA")).json()
        self.assertEqual(body["organization"], self.uk.id)

    def test_multiple_objects_require_other_info(self):
        r = self._create(legal_data(place="multiple", other_info=""))
        self.assertEqual(r.status_code, 400)
        self.assertIn("Иная информация", str(r.json()))

    def test_individual_required_fields(self):
        self.assertEqual(self._create(individual_data(passport="12 34")).status_code, 400)
        self.assertEqual(self._create(individual_data(birth_date="")).status_code, 400)
        self.assertEqual(self._create(individual_data(place="multiple")).status_code, 400)
        d = individual_data()
        d.pop("direction")
        self.assertEqual(self._create(d).status_code, 400)
        # отчество не обязательно
        self.assertEqual(self._create(individual_data(middle_name="")).status_code, 201)

    def test_legal_inn_length_checked(self):
        self.assertEqual(self._create(legal_data(inn_ogrn="123")).status_code, 400)
        self.assertEqual(self._create(legal_data(inn_ogrn="1027700132195")).status_code, 201)

    # --- маршрут ---
    def test_route_individual_is_security_advisor(self):
        rid = self._create(individual_data()).json()["id"]
        route = api(INITIATOR).get(f"/api/reg/requests/{rid}/route_preview/").json()["route"]
        self.assertEqual([s["role_code"] for s in route], [C.ROLE_SECURITY_ADVISOR])
        self.assertEqual(route[0]["b24_user_id"], SECURITY)

    def test_route_legal_is_legal_group(self):
        rid = self._create(legal_data()).json()["id"]
        route = api(INITIATOR).get(f"/api/reg/requests/{rid}/route_preview/").json()["route"]
        self.assertEqual([s["role_code"] for s in route], [C.ROLE_LEGAL_DEPT])
        self.assertTrue(route[0]["group"])

    def test_legal_approved_by_any_lawyer_lands_in_security_new(self):
        rid = self._create(legal_data()).json()["id"]
        self._submit(rid)
        r = self._approve(rid, LAWYER)
        self.assertEqual(r.json()["status"], C.STATUS_APPROVED)
        new = api(SECURITY).get("/api/reg/requests/security_queue/?scope=new").json()
        self.assertEqual([x["id"] for x in new], [rid])

    def test_reject_requires_reason(self):
        rid = self._create(individual_data()).json()["id"]
        body = self._submit(rid)
        pid = body["approval"]["rounds"][0]["participants"][0]["id"]
        r = api(SECURITY).post(f"/api/reg/requests/{rid}/decide/", {
            "participant_id": pid, "decision": "reject", "comment": "",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    # --- исполнение СБ ---
    def test_full_execution_flow(self):
        rid = self._approved_individual()
        # просмотреть «Новые» может СБ, посторонний — нет
        self.assertEqual(api(SECURITY).get(f"/api/reg/requests/{rid}/").status_code, 200)
        self.assertEqual(api(STRANGER).get(f"/api/reg/requests/{rid}/").status_code, 404)

        r = api(SECURITY).post(f"/api/reg/requests/{rid}/security_take/")
        self.assertEqual(r.json()["status"], C.STATUS_CHECK_WORK)
        self.assertEqual(r.json()["status_display"], "На исполнении")
        self.assertIsNotNone(r.json()["taken_at"])

        # без отчёта исполнить нельзя
        r = api(SECURITY).post(f"/api/reg/requests/{rid}/security_execute/", {"result": "approved"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("отчёт", r.json()["detail"])

        self._report(rid)
        # «с замечаниями» — без комментария нельзя
        r = api(SECURITY).post(f"/api/reg/requests/{rid}/security_execute/",
                               {"result": "approved_remarks"}, format="json")
        self.assertEqual(r.status_code, 400)

        r = api(SECURITY).post(f"/api/reg/requests/{rid}/security_execute/",
                               {"result": "approved_remarks", "comment": "Долг по налогам"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["status"], C.STATUS_EXECUTED)
        self.assertEqual(body["check_result_display"], "Согласовано с замечаниями")
        self.assertEqual(body["executor_b24_id"], SECURITY)

        archive = api(SECURITY).get("/api/reg/requests/security_queue/?scope=archive").json()
        self.assertEqual([x["id"] for x in archive], [rid])
        # инициатор видит итог в своей карточке
        mine = api(INITIATOR).get(f"/api/reg/requests/{rid}/").json()
        self.assertEqual(mine["check_comment"], "Долг по налогам")

    def test_queue_and_actions_closed_to_non_security(self):
        rid = self._approved_individual()
        self.assertEqual(api(STRANGER).get("/api/reg/requests/security_queue/").status_code, 403)
        # юрист без передачи функций — тоже нет
        self.assertEqual(api(LAWYER).get("/api/reg/requests/security_queue/").status_code, 403)
        self.assertEqual(api(LAWYER).post(f"/api/reg/requests/{rid}/security_take/").status_code, 403)

    def test_other_types_not_executable_by_security(self):
        req = RegulatoryRequest.objects.create(
            request_type=C.TYPE_POA, organization=self.uk, status=C.STATUS_APPROVED,
            initiator_b24_id=INITIATOR,
        )
        r = api(SECURITY).post(f"/api/reg/requests/{req.id}/security_take/")
        self.assertIn(r.status_code, (400, 404))

    # --- передача функций СБ юристам ---
    def test_delegation_gives_lawyers_access_and_is_logged(self):
        rid = self._approved_individual()
        # не юрист включить не может
        r = api(STRANGER).post("/api/reg/requests/security_delegation/", {"active": True}, format="json")
        self.assertEqual(r.status_code, 403)

        r = api(LAWYER).post("/api/reg/requests/security_delegation/",
                             {"active": True, "comment": "отпуск СБ"}, format="json")
        self.assertTrue(r.json()["active"])
        self.assertTrue(check.can_work_security(LAWYER))
        self.assertIn(LAWYER, check.security_recipient_ids())

        r = api(LAWYER).post(f"/api/reg/requests/{rid}/security_take/")
        self.assertEqual(r.json()["status"], C.STATUS_CHECK_WORK)
        self._report(rid, uid=LAWYER)
        r = api(LAWYER).post(f"/api/reg/requests/{rid}/security_execute/",
                             {"result": "approved"}, format="json")
        self.assertEqual(r.json()["executor_b24_id"], LAWYER)
        log = AuditLog.objects.filter(action="request_security_executed").latest("id")
        self.assertTrue(log.new_value["delegated"])

        # вернуть может и сотрудник СБ
        r = api(SECURITY).post("/api/reg/requests/security_delegation/", {"active": False}, format="json")
        self.assertFalse(r.json()["active"])
        self.assertFalse(check.can_work_security(LAWYER))
        d = SecurityDelegation.objects.get()
        self.assertEqual((d.started_by_b24_id, d.ended_by_b24_id), (LAWYER, SECURITY))

    def test_profile_flag(self):
        from core.auth_views import _is_security

        self.assertTrue(_is_security(SECURITY))
        self.assertFalse(_is_security(LAWYER))


class PersonCheckNotificationTests(_CheckBase):
    """Письма уходят по on_commit — прогоняем колбэки явно."""

    def setUp(self):
        super().setUp()
        UserProfile.objects.create(fio="Советник", bitrix_id=SECURITY, email="sb@x.ru", is_active=True)
        UserProfile.objects.create(fio="Кадровик", bitrix_id=INITIATOR, email="hr@x.ru", is_active=True)

    def test_security_notified_on_approval_initiator_on_result(self):
        from django.core import mail

        rid = self._create(individual_data()).json()["id"]
        self._submit(rid)
        with self.captureOnCommitCallbacks(execute=True):
            self._approve(rid, SECURITY)
        self.assertTrue(any("sb@x.ru" in m.to for m in mail.outbox
                            if m.subject == "Новая заявка на проверку лица"))

        api(SECURITY).post(f"/api/reg/requests/{rid}/security_take/")
        self._report(rid)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            api(SECURITY).post(f"/api/reg/requests/{rid}/security_execute/",
                               {"result": "rejected", "comment": "Санкции"}, format="json")
        msg = next(m for m in mail.outbox if m.subject == "Проверка лица исполнена")
        self.assertIn("hr@x.ru", msg.to)
        self.assertIn("Не согласовано", msg.body)
        self.assertIn("Санкции", msg.body)


class DelegatedApprovalTests(_CheckBase):
    """Функции СБ у юристов: согласует проверку физлица любой юрист."""

    def _delegate(self, on=True):
        api(LAWYER).post("/api/reg/requests/security_delegation/", {"active": on}, format="json")

    def test_route_default_is_security_advisor(self):
        rid = self._create(individual_data()).json()["id"]
        route = api(INITIATOR).get(f"/api/reg/requests/{rid}/route_preview/").json()["route"]
        self.assertEqual((route[0]["role_code"], route[0]["b24_user_id"], route[0]["needs_manual"]),
                         (C.ROLE_SECURITY_ADVISOR, SECURITY, False))

    def test_route_during_delegation_is_legal_group(self):
        self._delegate()
        rid = self._create(individual_data()).json()["id"]
        route = api(INITIATOR).get(f"/api/reg/requests/{rid}/route_preview/").json()["route"]
        self.assertEqual([s["role_code"] for s in route], [C.ROLE_LEGAL_DEPT])
        self.assertTrue(route[0]["group"])
        self._submit(rid)
        self.assertEqual(self._approve(rid, LAWYER).json()["status"], C.STATUS_APPROVED)

    def test_lawyer_closes_pending_security_stage_after_delegation(self):
        rid = self._create(individual_data()).json()["id"]
        self._submit(rid)  # ушла на Золотько (SECURITY)
        # без передачи юрист решать не может
        self.assertEqual(self._approve(rid, LAWYER).status_code, 400)
        self.assertEqual(api(LAWYER).get("/api/reg/requests/todo/").json(), [])

        self._delegate()
        self.assertEqual([x["id"] for x in api(LAWYER).get("/api/reg/requests/todo/").json()], [rid])
        r = self._approve(rid, LAWYER)
        self.assertEqual(r.json()["status"], C.STATUS_APPROVED)
        part = r.json()["approval"]["rounds"][0]["participants"][0]
        self.assertEqual(part["b24_user_id"], LAWYER)  # записан тот, кто решил
        self.assertTrue(AuditLog.objects.filter(action="security_approval_by_lawyer").exists())

    def test_stranger_cannot_close_security_stage_even_during_delegation(self):
        rid = self._create(individual_data()).json()["id"]
        self._submit(rid)
        self._delegate()
        # посторонний карточку даже не видит (404), решение не принимается
        self.assertIn(self._approve(rid, STRANGER).status_code, (400, 404))
        self.assertEqual(RegulatoryRequest.objects.get(pk=rid).status, C.STATUS_ON_APPROVAL)
