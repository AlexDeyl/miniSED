"""
Тесты ядра: сид ролей/прав, RBAC, полиморфные внешние связи, аудит, API.
"""

from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from approvals.models import Agreement
from .constants import ALL_PERMISSIONS, ALL_ROLES
from .models import (
    AuditLog,
    ExternalLink,
    Facility,
    IntegrationEvent,
    Organization,
    Permission,
    Role,
    UserProfile,
)
from .services import emit_event, log_action


class SeedTests(TestCase):
    """Сид применяется автоматически (миграция 0002) для тестовой БД."""

    def test_permissions_and_roles_seeded(self):
        self.assertEqual(Permission.objects.count(), len(ALL_PERMISSIONS))
        self.assertEqual(Role.objects.count(), len(ALL_ROLES))

    def test_sys_admin_has_all_system_perms(self):
        role = Role.objects.get(code="sys_admin")
        self.assertEqual(
            role.permissions.filter(category="system").count(),
            role.permissions.count(),
        )
        self.assertTrue(role.permissions.filter(code="manage_security").exists())


class RbacTests(TestCase):
    def test_user_has_perm_via_role(self):
        user = UserProfile.objects.create(fio="Иванов И.И.", bitrix_id=100)
        user.roles.add(Role.objects.get(code="initiator"))

        self.assertTrue(user.has_perm("request_create"))
        self.assertFalse(user.has_perm("manage_users"))

    def test_inactive_user_has_no_perm(self):
        user = UserProfile.objects.create(fio="Петров", bitrix_id=101, is_active=False)
        user.roles.add(Role.objects.get(code="sys_admin"))
        self.assertFalse(user.has_perm("manage_security"))


class ExternalLinkTests(TestCase):
    def test_generic_link_to_agreement(self):
        agreement = Agreement.objects.create(title="Скидка", author_b24_id=1)
        link = ExternalLink.objects.create(
            linked_object=agreement,
            source=ExternalLink.SOURCE_BITRIX,
            entity_type=ExternalLink.ENTITY_DEAL,
            external_id="42",
            external_url="https://portal.bitrix24.ru/crm/deal/details/42/",
            title="Сделка №42",
            snapshot_json={"OPPORTUNITY": "100000"},
        )
        # обратный доступ через тот же generic-механизм
        self.assertEqual(link.linked_object, agreement)
        self.assertEqual(link.snapshot_json["OPPORTUNITY"], "100000")

        # находим связи объекта по content_type/object_id
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(Agreement)
        found = ExternalLink.objects.filter(content_type=ct, object_id=agreement.id)
        self.assertEqual(found.count(), 1)


class AuditTests(TestCase):
    def test_log_action_records_target_and_actor(self):
        user = UserProfile.objects.create(fio="Сидоров", bitrix_id=200)
        org = Organization.objects.create(short_name="ООО Ромашка")

        entry = log_action(
            "organization_created",
            actor=user,
            target=org,
            new_value={"short_name": "ООО Ромашка"},
        )
        self.assertEqual(entry.action, "organization_created")
        self.assertEqual(entry.target, org)
        self.assertEqual(entry.actor, user)
        self.assertEqual(entry.object_repr, "ООО Ромашка")
        self.assertEqual(AuditLog.objects.count(), 1)


class IntegrationEventTests(TestCase):
    def test_emit_event(self):
        agreement = Agreement.objects.create(title="x", author_b24_id=1)
        ev = emit_event(
            "approval_created",
            related=agreement,
            target_system="bitrix24",
            payload={"id": agreement.id},
        )
        self.assertEqual(ev.event_type, "approval_created")
        self.assertEqual(ev.status, IntegrationEvent.STATUS_NEW)
        self.assertEqual(ev.related_object, agreement)


class DirectoryApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(short_name="ООО А", inn="1234567890")
        self.other = Organization.objects.create(short_name="ООО Б")
        Facility.objects.create(name="Отель 1", organization=self.org)
        Facility.objects.create(name="Отель 2", organization=self.other)

    def test_organizations_list(self):
        data = self.client.get("/api/core/organizations/").json()
        self.assertEqual(len(data), 2)

    def test_facilities_filter_by_organization(self):
        data = self.client.get(
            f"/api/core/facilities/?organization={self.org.id}"
        ).json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Отель 1")
        self.assertEqual(data[0]["organization_name"], "ООО А")

    def test_roles_list_includes_permissions(self):
        data = self.client.get("/api/core/roles/").json()
        self.assertEqual(len(data), len(ALL_ROLES))
        sys_admin = next(r for r in data if r["code"] == "sys_admin")
        self.assertIn("manage_security", sys_admin["permissions"])

    def test_inactive_organization_hidden(self):
        Organization.objects.create(short_name="Скрытая", is_active=False)
        data = self.client.get("/api/core/organizations/").json()
        names = {o["short_name"] for o in data}
        self.assertNotIn("Скрытая", names)


class AuthTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User

        self.user = User.objects.create_user(
            username="ivanov@nord.ru", email="ivanov@nord.ru", password="secret123"
        )
        self.profile = UserProfile.objects.create(
            fio="Иванов И.И.", email="ivanov@nord.ru", bitrix_id=1099, auth_user=self.user
        )
        self.profile.roles.add(Role.objects.get(code="initiator"))
        self.client = APIClient()

    def test_login_returns_token_and_profile(self):
        r = self.client.post(
            "/api/auth/login/", {"email": "ivanov@nord.ru", "password": "secret123"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.json())
        self.assertEqual(r.json()["bitrix_id"], 1099)
        self.assertIn("initiator", r.json()["roles"])

    def test_login_wrong_password(self):
        r = self.client.post(
            "/api/auth/login/", {"email": "ivanov@nord.ru", "password": "nope"},
            format="json",
        )
        self.assertEqual(r.status_code, 401)

    def test_me_with_token(self):
        token = self.client.post(
            "/api/auth/login/", {"email": "ivanov@nord.ru", "password": "secret123"},
            format="json",
        ).json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        r = self.client.get("/api/auth/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["fio"], "Иванов И.И.")

    def test_token_resolves_identity_without_bitrix_header(self):
        """Авторизованный пользователь MiniSED виден API как b24-пользователь."""
        token = self.client.post(
            "/api/auth/login/", {"email": "ivanov@nord.ru", "password": "secret123"},
            format="json",
        ).json()["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        # эндпоинт требует b24-личность; без X-B24-User, только по токену
        r = self.client.get("/api/reg/requests/")
        self.assertEqual(r.status_code, 200)


class BitrixLoginTests(TestCase):
    """Вход через Битрикс = тот же аккаунт (связка bitrix_id/email)."""

    def _mock_user_current(self, bid, email, last="Тест", name="Юзер"):
        class R:
            def json(self_inner):
                return {"result": {"ID": str(bid), "EMAIL": email, "LAST_NAME": last, "NAME": name}}
        return R()

    @patch("core.auth_views.requests")
    def test_bitrix_login_matches_existing_profile_by_bitrix_id(self, req):
        from django.contrib.auth.models import User
        u = User.objects.create_user("ivanov@nord.ru", "ivanov@nord.ru", "secret123")
        profile = UserProfile.objects.create(fio="Иванов", bitrix_id=1099, email="ivanov@nord.ru", auth_user=u)

        req.get.return_value = self._mock_user_current(1099, "ivanov@nord.ru")
        r = self.client.post("/api/auth/bitrix/", {"access_token": "acc", "domain": "portal.bitrix24.ru"}, format="json")
        self.assertEqual(r.status_code, 200)
        # тот же аккаунт: id профиля совпал
        self.assertEqual(r.json()["id"], profile.id)
        self.assertEqual(r.json()["bitrix_id"], 1099)
        # токен = токен того же django-User
        from rest_framework.authtoken.models import Token
        self.assertEqual(r.json()["token"], Token.objects.get(user=u).key)

    @patch("core.auth_views.requests")
    def test_bitrix_login_links_by_email_and_sets_bitrix_id(self, req):
        from django.contrib.auth.models import User
        u = User.objects.create_user("petrov@nord.ru", "petrov@nord.ru", "secret123")
        profile = UserProfile.objects.create(fio="Петров", email="petrov@nord.ru", auth_user=u)  # без bitrix_id

        req.get.return_value = self._mock_user_current(2222, "petrov@nord.ru")
        r = self.client.post("/api/auth/bitrix/", {"access_token": "acc", "domain": "p.bitrix24.ru"}, format="json")
        self.assertEqual(r.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.bitrix_id, 2222)  # долинковали
        self.assertEqual(r.json()["id"], profile.id)

    @patch("core.auth_views.requests")
    def test_bitrix_login_provisions_new_account(self, req):
        req.get.return_value = self._mock_user_current(3333, "new@nord.ru", last="Новый", name="Гость")
        r = self.client.post("/api/auth/bitrix/", {"access_token": "acc", "domain": "p.bitrix24.ru"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(bitrix_id=3333).exists())
        self.assertIn("token", r.json())
