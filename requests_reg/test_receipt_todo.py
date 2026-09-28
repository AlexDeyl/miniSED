"""
Исполненная заявка ждёт инициатора в «Требует действия» рабочего места
визирования, пока он не подтвердит получение (→ «Закрыта»).
"""

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Organization

from . import constants as C
from .models import RegulatoryRequest


def api(uid):
    c = APIClient()
    c.credentials(HTTP_X_B24_USER=str(uid))
    return c


class ReceiptTodoTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    def _req(self, rtype=C.TYPE_POA, status=C.STATUS_EXECUTED, initiator=1):
        return RegulatoryRequest.objects.create(
            request_type=rtype, organization=self.org, status=status, initiator_b24_id=initiator,
        )

    def _todo(self, uid):
        return {r["id"] for r in api(uid).get("/api/reg/requests/todo/").json()}

    def test_executed_poa_in_initiator_todo_until_confirmed(self):
        req = self._req()
        self.assertIn(req.id, self._todo(1))
        self.assertNotIn(req.id, self._todo(2))  # чужому — нет

        r = api(1).post(f"/api/reg/requests/{req.id}/confirm_receipt/")
        self.assertEqual(r.json()["status"], C.STATUS_CLOSED)
        self.assertEqual(r.json()["status_display"], "Закрыта")
        self.assertNotIn(req.id, self._todo(1))

    def test_not_yet_executed_not_in_todo(self):
        for st in (C.STATUS_TO_LEGAL, C.STATUS_LEGAL_WORK, C.STATUS_SIGNING, C.STATUS_CLOSED):
            self.assertNotIn(self._req(status=st).id, self._todo(1))

    def test_other_receipt_types_included_check_excluded(self):
        for t in (C.TYPE_MCHD, C.TYPE_ECP, C.TYPE_REVOKE):
            self.assertIn(self._req(rtype=t).id, self._todo(1))
        check = self._req(rtype=C.TYPE_CHECK)
        self.assertNotIn(check.id, self._todo(1))
        self.assertEqual(api(1).post(f"/api/reg/requests/{check.id}/confirm_receipt/").status_code, 400)
