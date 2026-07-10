"""
Тесты Bitrix Connector. Весь HTTP замокан — реальных обращений к порталу нет.
"""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .client import (
    BitrixAuthError,
    BitrixClient,
    BitrixError,
    flatten_params,
    store_token,
)
from .models import BitrixApiLog, BitrixPortal, BitrixToken


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def make_portal(with_token=True, expires_in=3600):
    portal = BitrixPortal.objects.create(
        domain="portal.bitrix24.ru", member_id="m1", is_active=True
    )
    if with_token:
        BitrixToken.objects.create(
            portal=portal,
            access_token="acc-1",
            refresh_token="ref-1",
            expires_at=timezone.now() + timezone.timedelta(seconds=expires_in),
        )
    return portal


class FlattenTests(TestCase):
    def test_nested_dict_and_list(self):
        out = dict(
            flatten_params(
                {"filter": {"%TITLE": "abc"}, "select": ["ID", "TITLE"]}
            )
        )
        self.assertEqual(out["filter[%TITLE]"], "abc")
        self.assertEqual(out["select[0]"], "ID")
        self.assertEqual(out["select[1]"], "TITLE")


class StoreTokenTests(TestCase):
    def test_expires_at_computed(self):
        portal = make_portal(with_token=False)
        token = store_token(
            portal,
            {"access_token": "a", "refresh_token": "r", "expires_in": 3600},
        )
        self.assertEqual(token.access_token, "a")
        self.assertIsNotNone(token.expires_at)
        self.assertFalse(token.is_expired)


class ClientCallTests(TestCase):
    @patch("bitrix.client.requests")
    def test_successful_call_returns_result_and_logs(self, req):
        portal = make_portal()
        req.post.return_value = FakeResp({"result": [{"ID": "1"}]})

        client = BitrixClient(portal)
        result = client.call("crm.deal.list", {"filter": {"%TITLE": "x"}})

        self.assertEqual(result, [{"ID": "1"}])
        log = BitrixApiLog.objects.latest("id")
        self.assertTrue(log.ok)
        self.assertEqual(log.method, "crm.deal.list")

    @patch("bitrix.client.requests")
    def test_error_response_raises_and_logs(self, req):
        portal = make_portal()
        req.post.return_value = FakeResp(
            {"error": "QUERY_LIMIT", "error_description": "too many"}
        )
        client = BitrixClient(portal)
        with self.assertRaises(BitrixError):
            client.call("crm.deal.list")
        self.assertFalse(BitrixApiLog.objects.latest("id").ok)

    @patch("bitrix.client.requests")
    def test_expired_token_triggers_refresh_and_retry(self, req):
        portal = make_portal()
        # 1-й POST -> expired_token, 2-й POST (после refresh) -> result
        req.post.side_effect = [
            FakeResp({"error": "expired_token"}),
            FakeResp({"result": [{"ID": "7"}]}),
        ]
        # refresh (GET) -> новые токены
        req.get.return_value = FakeResp(
            {"access_token": "acc-2", "refresh_token": "ref-2", "expires_in": 3600}
        )

        client = BitrixClient(portal)
        result = client.call("crm.deal.list")

        self.assertEqual(result, [{"ID": "7"}])
        portal.refresh_from_db()
        self.assertEqual(portal.token.access_token, "acc-2")

    def test_missing_token_raises_auth_error(self):
        portal = make_portal(with_token=False)
        with self.assertRaises(BitrixAuthError):
            BitrixClient(portal).call("crm.deal.list")


class AuthEndpointTests(TestCase):
    def test_auth_creates_portal_and_token(self):
        resp = self.client.post(
            "/api/bitrix/auth/",
            {
                "domain": "new.bitrix24.ru",
                "member_id": "mm",
                "access_token": "acc",
                "refresh_token": "ref",
                "expires_in": 3600,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["connected"])
        portal = BitrixPortal.objects.get(member_id="mm")
        self.assertEqual(portal.token.access_token, "acc")

    def test_auth_requires_domain_and_token(self):
        resp = self.client.post("/api/bitrix/auth/", {"domain": "x"})
        self.assertEqual(resp.status_code, 400)


class StatusEndpointTests(TestCase):
    def test_status_connected(self):
        make_portal()
        data = self.client.get("/api/bitrix/status/").json()
        self.assertTrue(data["connected"])

    def test_status_not_connected(self):
        data = self.client.get("/api/bitrix/status/").json()
        self.assertFalse(data["connected"])


class SearchEndpointTests(TestCase):
    @patch("bitrix.client.requests")
    def test_deals_search(self, req):
        make_portal()
        req.post.return_value = FakeResp(
            {"result": [{"ID": "1", "TITLE": "Сделка"}]}
        )
        data = self.client.get("/api/bitrix/deals/?q=Сдел").json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["TITLE"], "Сделка")

    def test_deals_search_without_portal_returns_409(self):
        resp = self.client.get("/api/bitrix/deals/?q=x")
        self.assertEqual(resp.status_code, 409)

    @patch("bitrix.client.requests")
    def test_users_search(self, req):
        make_portal()
        req.post.return_value = FakeResp(
            {"result": [{"ID": "5", "NAME": "Иван"}]}
        )
        data = self.client.get("/api/bitrix/users/?q=Иван").json()
        self.assertEqual(data["results"][0]["NAME"], "Иван")

    @patch("bitrix.client.requests")
    def test_timeline_comment(self, req):
        make_portal()
        req.post.return_value = FakeResp({"result": 123})
        resp = self.client.post(
            "/api/bitrix/timeline/", {"deal_id": 10, "comment": "Согласовано"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], 123)
