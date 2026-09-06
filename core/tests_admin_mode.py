"""
Режим администратора: сквозной просмотр + решение за любого согласующего.

Ключевое здесь — что заголовок X-Admin-Mode сам по себе НИЧЕГО не даёт:
право проверяется на сервере. Поэтому в каждом сценарии есть пара «с ролью /
без роли», иначе режим превратился бы в дыру, включаемую из консоли браузера.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from approvalflow.models import ApprovalParticipant
from core.models import Organization, Role, UserProfile
from requests_reg import constants as C, services
from requests_reg.models import RegulatoryRequest

ADMIN = 900          # системный администратор
APPROVER = 20        # согласующий по маршруту
INITIATOR = 1


def api(uid, admin_mode=False):
    c = APIClient()
    headers = {"HTTP_X_B24_USER": str(uid)}
    if admin_mode:
        headers["HTTP_X_ADMIN_MODE"] = "1"
    c.credentials(**headers)
    return c


class AdminModeTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")
        admin = UserProfile.objects.create(fio="Админ", bitrix_id=ADMIN, is_active=True)
        admin.roles.add(Role.objects.get(code="sys_admin"))
        # обычный сотрудник без роли — им проверяем, что заголовок не работает
        UserProfile.objects.create(fio="Обычный", bitrix_id=APPROVER, is_active=True)

    def _submitted(self):
        req = services.create_request(
            request_type=C.TYPE_POA, organization=self.org,
            initiator_b24_id=INITIATOR, subject_name="Петров",
        )
        services.submit(req, [
            {"type": "internal", "b24_user_id": APPROVER, "order": 0, "role": C.ROLE_CFO_HEAD},
        ])
        return req

    def _participant(self, req):
        approval = services.get_approval(req)
        return ApprovalParticipant.objects.get(round__approval=approval)

    # --- видимость ---
    def test_admin_mode_shows_foreign_requests(self):
        req = self._submitted()
        # без режима админ видит только свои (он не инициатор и не согласующий)
        self.assertEqual(api(ADMIN).get("/api/reg/requests/").json(), [])
        # с режимом — все
        ids = {x["id"] for x in api(ADMIN, admin_mode=True).get("/api/reg/requests/").json()}
        self.assertEqual(ids, {req.id})

    def test_header_without_role_does_nothing(self):
        """Заголовок без роли — не режим: иначе его включал бы кто угодно."""
        self._submitted()
        r = api(APPROVER, admin_mode=True).get("/api/reg/requests/")
        self.assertEqual(r.json(), [])  # свои заявки, а не чужие

    # --- решение за другого ---
    def test_admin_decides_for_another_participant(self):
        req = self._submitted()
        p = self._participant(req)
        r = api(ADMIN, admin_mode=True).post(
            f"/api/reg/requests/{req.id}/decide/",
            {"participant_id": p.id, "decision": "approve"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)

        p.refresh_from_db()
        self.assertEqual(p.decision, "approved")
        # пометка: место в маршруте осталось за согласующим, виза — админа
        self.assertEqual(p.b24_user_id, APPROVER)
        self.assertEqual(p.admin_override_by_b24_id, ADMIN)

    def test_decision_without_admin_mode_still_forbidden(self):
        """Без включённого режима админ решать за других не может."""
        req = self._submitted()
        p = self._participant(req)
        r = api(ADMIN).post(
            f"/api/reg/requests/{req.id}/decide/",
            {"participant_id": p.id, "decision": "approve"}, format="json",
        )
        self.assertEqual(r.status_code, 400, r.content)
        p.refresh_from_db()
        self.assertEqual(p.decision, "waiting")

    def test_admin_mode_needs_the_role_to_decide(self):
        """Сотрудник без роли не проставит визу за другого даже с заголовком."""
        req = self._submitted()
        p = self._participant(req)
        r = api(777, admin_mode=True).post(
            f"/api/reg/requests/{req.id}/decide/",
            {"participant_id": p.id, "decision": "approve"}, format="json",
        )
        self.assertNotEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.decision, "waiting")

    def test_admin_can_close_stage_out_of_turn(self):
        """Админ закрывает и не наступивший этап — очередь его не держит."""
        req = services.create_request(
            request_type=C.TYPE_POA, organization=self.org,
            initiator_b24_id=INITIATOR, subject_name="Петров",
        )
        services.submit(req, [
            {"type": "internal", "b24_user_id": APPROVER, "order": 0, "role": C.ROLE_CFO_HEAD},
            {"type": "internal", "b24_user_id": 21, "order": 1, "role": C.ROLE_FINANCE_DIRECTOR},
        ])
        approval = services.get_approval(req)
        second = ApprovalParticipant.objects.get(round__approval=approval, order=1)

        r = api(ADMIN, admin_mode=True).post(
            f"/api/reg/requests/{req.id}/decide/",
            {"participant_id": second.id, "decision": "approve"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        second.refresh_from_db()
        self.assertEqual(second.decision, "approved")
        self.assertEqual(second.admin_override_by_b24_id, ADMIN)
        # первый по-прежнему ждёт — заявка не «перепрыгнула» его
        first = ApprovalParticipant.objects.get(round__approval=approval, order=0)
        self.assertEqual(first.decision, "waiting")
        req.refresh_from_db()
        self.assertEqual(req.status, C.STATUS_ON_APPROVAL)

    def test_override_is_audited(self):
        from core.models import AuditLog

        req = self._submitted()
        p = self._participant(req)
        api(ADMIN, admin_mode=True).post(
            f"/api/reg/requests/{req.id}/decide/",
            {"participant_id": p.id, "decision": "approve"}, format="json",
        )
        self.assertTrue(
            AuditLog.objects.filter(action="admin_override_decision").exists()
        )

    def test_normal_participant_decision_has_no_mark(self):
        """Обычное решение пометкой не помечается — иначе она обесценится."""
        req = self._submitted()
        p = self._participant(req)
        r = api(APPROVER).post(
            f"/api/reg/requests/{req.id}/decide/",
            {"participant_id": p.id, "decision": "approve"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertIsNone(p.admin_override_by_b24_id)
