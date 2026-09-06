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

    def test_users_list_only_active_with_bitrix_id(self):
        UserProfile.objects.create(fio="Иванов Иван", bitrix_id=501)
        UserProfile.objects.create(fio="Без битрикса")  # нет bitrix_id → скрыт
        UserProfile.objects.create(fio="Уволенный", bitrix_id=502, is_active=False)
        data = self.client.get("/api/core/users/").json()
        fios = {u["fio"] for u in data}
        self.assertIn("Иванов Иван", fios)
        self.assertNotIn("Без битрикса", fios)
        self.assertNotIn("Уволенный", fios)


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


class AppLinkTests(TestCase):
    """Ссылки из уведомлений: куда ведёт «Перейти к согласованию»."""

    from django.test import override_settings as _os  # локальный алиас

    @_os(BITRIX_APP_URL="https://portal.bitrix24.ru/marketplace/app/150/",
         PUBLIC_BASE_URL="https://msed.example.ru")
    def test_prefers_portal_app_page(self):
        """Когда приложение прописано в портале — ведём внутрь Битрикса."""
        from core.links import app_link, contract_route

        self.assertEqual(
            app_link(contract_route(5)),
            "https://portal.bitrix24.ru/marketplace/app/150/?to=%2Fcontracts%2F5",
        )

    @_os(BITRIX_APP_URL="", PUBLIC_BASE_URL="https://msed.example.ru")
    def test_falls_back_to_minised(self):
        from core.links import agreement_route, app_link

        self.assertEqual(
            app_link(agreement_route(7)),
            "https://msed.example.ru/app/?to=%2Fsvetofor%3Fopen%3D7",
        )

    @_os(BITRIX_APP_URL="", PUBLIC_BASE_URL="")
    def test_no_base_no_link(self):
        """Без настроек ссылки нет — уведомление уходит без неё, а не с битой."""
        from core.links import app_link, request_route

        self.assertEqual(app_link(request_route(1)), "")


class DeepLinkRouteTests(TestCase):
    """Приложение открывается сразу на нужной карточке (?to=...)."""

    def _boot(self, to):
        """Тег с window.__MINISED_BOOT__ из отданного SPA (или пустая строка).

        Проверяем именно его: слово route встречается и внутри бандла Vue."""
        html = self.client.get(f"/app/?to={to}").content.decode()
        marker = "window.__MINISED_BOOT__="
        i = html.find(marker)
        return html[i:html.find("</script>", i)] if i >= 0 else ""

    def test_boot_route_injected(self):
        self.assertIn('"route": "/contracts/5"', self._boot("/contracts/5"))

    def test_external_target_rejected(self):
        """Чужой домен параметром не подсунуть."""
        for bad in ("//evil.example.com", "https://evil.example.com", "contracts/5"):
            self.assertEqual(self._boot(bad), "", bad)


class MoneyFormatTests(TestCase):
    """Сумма в уведомлениях — как в интерфейсе, а не «100000.00»."""

    def test_formats_like_ui(self):
        from core.formatting import money

        nbsp = " "
        self.assertEqual(money("100000.00"), f"100{nbsp}000 ₽")
        self.assertEqual(money("1234.50"), f"1{nbsp}234,50 ₽")
        self.assertEqual(money(0), "0 ₽")

    def test_empty_and_garbage(self):
        from core.formatting import money

        self.assertEqual(money(None), "")
        self.assertEqual(money(""), "")
        self.assertEqual(money("не число"), "не число")


class ViewAllPermissionTests(TestCase):
    """Право сквозного просмотра.

    Списки оно расширяет ТОЛЬКО в режиме администратора (см.
    core.tests_admin_mode) — иначе у админа молча другая выдача, чем у всех.
    А вот открыть чужую карточку по прямой ссылке право позволяет всегда:
    так работают ссылки из писем и колокольчика."""

    ADMIN = 4242
    STRANGER = 4243

    def setUp(self):
        from approvals.models import Participant

        self.admin = UserProfile.objects.create(
            fio="Администратор", bitrix_id=self.ADMIN, is_active=True,
        )
        self.admin.roles.add(Role.objects.get(code="sys_admin"))
        UserProfile.objects.create(
            fio="Посторонний", bitrix_id=self.STRANGER, is_active=True,
        )
        # чужое согласование: админ ему никто
        self.agreement = Agreement.objects.create(
            title="Чужое", author_b24_id=1, flow_type="parallel", status="in_progress",
        )
        self.participant = Participant.objects.create(
            agreement=self.agreement, type="internal", b24_user_id=2, order_index=0,
        )

    def _api(self, uid):
        c = APIClient()
        c.credentials(HTTP_X_B24_USER=str(uid))
        return c

    def test_permission_seeded_on_sys_admin(self):
        self.assertTrue(self.admin.has_perm("view_all"))
        self.assertIn("view_all", [p.code for p in Permission.objects.all()])

    def test_foreign_agreements_hidden_until_admin_mode(self):
        # без режима список личный — даже у администратора
        self.assertEqual(self._api(self.ADMIN).get("/api/agreements/").json(), [])
        # с режимом — видно чужое
        c = APIClient()
        c.credentials(HTTP_X_B24_USER=str(self.ADMIN), HTTP_X_ADMIN_MODE="1")
        ids = [a["id"] for a in c.get("/api/agreements/").json()]
        self.assertEqual(ids, [self.agreement.id])
        # посторонний без права — ничего, даже с заголовком
        c2 = APIClient()
        c2.credentials(HTTP_X_B24_USER=str(self.STRANGER), HTTP_X_ADMIN_MODE="1")
        self.assertEqual(c2.get("/api/agreements/").json(), [])

    def test_admin_cannot_decide_for_others(self):
        """Право на чтение не делает администратора согласующим.

        Решать за других он может только во включённом режиме администратора,
        и такое решение помечается (core.tests_admin_mode)."""
        r = self._api(self.ADMIN).post(
            f"/api/agreements/{self.agreement.id}/decide/",
            {"participant_id": self.participant.id, "decision": "approve"},
            format="json",
        )
        self.assertEqual(r.status_code, 403)

    def test_admin_sees_foreign_requests_and_contracts(self):
        from contracts.models import Contract
        from requests_reg.models import RegulatoryRequest

        org = Organization.objects.create(short_name="УК Норд")
        req = RegulatoryRequest.objects.create(
            request_type="poa", organization=org, initiator_b24_id=1, status="on_approval",
        )
        contract = Contract.objects.create(
            organization=org, title="Чужой договор", initiator_b24_id=1,
            status="on_approval",
        )

        # В списках чужого не видно, пока не включён режим администратора…
        self.assertEqual(self._api(self.ADMIN).get("/api/reg/requests/").json(), [])
        self.assertEqual(
            self._api(self.ADMIN).get("/api/contracts/?scope=all").json(), [],
        )

        admin = APIClient()
        admin.credentials(HTTP_X_B24_USER=str(self.ADMIN), HTTP_X_ADMIN_MODE="1")
        self.assertEqual(
            [x["id"] for x in admin.get("/api/reg/requests/").json()], [req.id],
        )
        self.assertEqual(
            [x["id"] for x in admin.get("/api/contracts/?scope=all").json()],
            [contract.id],
        )

        # …но открыть карточку по прямой ссылке право позволяет и без режима:
        # так работают ссылки из писем и колокольчика.
        self.assertEqual(
            self._api(self.ADMIN).get(f"/api/reg/requests/{req.id}/").status_code, 200,
        )
        self.assertEqual(
            self._api(self.ADMIN).get(f"/api/contracts/{contract.id}/").status_code, 200,
        )

    def test_admin_may_read_legal_queue(self):
        """Очередь юротдела администратору видна (чтение), юристом он не стал."""
        r = self._api(self.ADMIN).get("/api/reg/requests/legal_queue/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._api(self.STRANGER).get(
            "/api/reg/requests/legal_queue/").status_code, 403)
