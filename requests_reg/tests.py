"""
Тесты регламентных заявок: создание/номер, отправка на согласование через
движок, решение, синхронизация статуса, жизненный цикл выпуска, API.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import Organization
from . import constants, services
from .models import RegulatoryRequest


def api(uid=None):
    c = APIClient()
    if uid is not None:
        c.credentials(HTTP_X_B24_USER=str(uid))
    return c


def internal(uid, order=0):
    return {"type": "internal", "b24_user_id": uid, "order": order}


class ServiceTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="ООО Норд")

    def test_create_generates_number(self):
        req = services.create_request(
            request_type=constants.TYPE_ECP, organization=self.org,
            subject_name="Иванов И.И.", initiator_b24_id=1,
        )
        self.assertTrue(req.number.startswith("ЭЦП-"))
        self.assertEqual(req.status, constants.STATUS_DRAFT)

    def test_unknown_type_rejected(self):
        with self.assertRaises(services.RequestError):
            services.create_request(request_type="xxx", organization=self.org)

    def test_submit_then_approve_flows_status(self):
        req = services.create_request(
            request_type=constants.TYPE_MCHD, organization=self.org, initiator_b24_id=1,
        )
        services.submit(req, [internal(10)])
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_ON_APPROVAL)

        approval = services.get_approval(req)
        self.assertIsNotNone(approval)
        pid = approval.rounds.first().participants.first().id

        services.decide(req, pid, "approve")
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_APPROVED)

    def test_reject_sets_rejected(self):
        req = services.create_request(
            request_type=constants.TYPE_POA, organization=self.org, initiator_b24_id=1,
        )
        services.submit(req, [internal(10)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "reject", "нет оснований")
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_REJECTED)

    def test_return_and_resubmit_new_round(self):
        req = services.create_request(
            request_type=constants.TYPE_ECP, organization=self.org, initiator_b24_id=1,
        )
        services.submit(req, [internal(10)])
        services.return_for_revision(req, comment="доработать")
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_RETURNED)

        services.submit(req, [internal(10), internal(20)])
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_ON_APPROVAL)
        self.assertEqual(services.get_approval(req).rounds.count(), 2)

    def test_issue_lifecycle(self):
        req = services.create_request(
            request_type=constants.TYPE_ECP, organization=self.org, initiator_b24_id=1,
        )
        services.submit(req, [internal(10)])
        pid = services.get_approval(req).rounds.first().participants.first().id
        services.decide(req, pid, "approve")

        services.mark_in_work(req)
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_IN_WORK)

        services.mark_issued(req)
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_ISSUED)
        self.assertEqual(req.status_label(), "ЭЦП выпущена")

        services.close(req)
        req.refresh_from_db()
        self.assertEqual(req.status, constants.STATUS_CLOSED)

    def test_cannot_issue_before_approval(self):
        req = services.create_request(
            request_type=constants.TYPE_ECP, organization=self.org, initiator_b24_id=1,
        )
        with self.assertRaises(services.RequestError):
            services.mark_issued(req)


class ApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="ООО Норд")

    def test_requires_auth(self):
        self.assertEqual(api().get("/api/reg/requests/").status_code, 403)

    def test_create_and_submit_and_decide(self):
        r = api(1).post(
            "/api/reg/requests/",
            {"request_type": "ecp", "organization": self.org.id, "subject_name": "Петров"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        rid = r.json()["id"]
        self.assertTrue(r.json()["number"].startswith("ЭЦП-"))

        r = api(1).post(
            f"/api/reg/requests/{rid}/submit/",
            {"participants": [{"type": "internal", "b24_user_id": 20, "order": 0}]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "on_approval")
        pid = r.json()["approval"]["rounds"][0]["participants"][0]["id"]

        r = api(20).post(
            f"/api/reg/requests/{rid}/decide/",
            {"participant_id": pid, "decision": "approve"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "approved")

    def test_list_filter_by_type(self):
        services.create_request(request_type="ecp", organization=self.org, initiator_b24_id=1)
        services.create_request(request_type="mchd", organization=self.org, initiator_b24_id=1)
        data = api(1).get("/api/reg/requests/?type=ecp").json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["request_type"], "ecp")

    def test_types_endpoint(self):
        data = api(1).get("/api/reg/requests/types/").json()
        codes = {t["code"] for t in data["types"]}
        self.assertEqual(codes, {"ecp", "mchd", "poa"})
