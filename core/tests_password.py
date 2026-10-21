"""
Пароль для входа по почте — на случай, когда Битрикс24 недоступен.

Общего пароля по умолчанию нет: вошедший задаёт/меняет свой пароль сам,
а забывший — получает на почту одноразовую ссылку.
"""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import UserProfile

User = get_user_model()

GOOD = "Zelenyi-Sad-2026"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PUBLIC_BASE_URL="https://sed.example.ru",
)
class PasswordTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        # вошёл через Битрикс — пароля нет
        self.user = User.objects.create(username="ivanov@hotel.ru", email="ivanov@hotel.ru")
        self.user.set_unusable_password()
        self.user.save()
        self.profile = UserProfile.objects.create(
            fio="Иванов Иван", bitrix_id=501, email="ivanov@hotel.ru", auth_user=self.user,
        )

    def auth(self, user=None):
        token, _ = Token.objects.get_or_create(user=user or self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def login(self, email, password):
        return APIClient().post("/api/auth/login/", {"email": email, "password": password})

    # --- смена пароля --------------------------------------------------------
    def test_me_reports_missing_password(self):
        self.auth()
        self.assertFalse(self.client.get("/api/auth/me/").data["has_password"])

    def test_first_password_set_without_old_one(self):
        self.auth()
        r = self.client.post("/api/auth/password/change/",
                             {"new_password": GOOD, "new_password2": GOOD})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.login("ivanov@hotel.ru", GOOD).status_code, 200)
        self.assertTrue(self.client.get("/api/auth/me/").data["has_password"])

    def test_change_requires_current_password(self):
        self.user.set_password(GOOD)
        self.user.save()
        self.auth()
        r = self.client.post("/api/auth/password/change/", {
            "old_password": "wrong", "new_password": "Drugoi-Parol-77", "new_password2": "Drugoi-Parol-77",
        })
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/auth/password/change/", {
            "old_password": GOOD, "new_password": "Drugoi-Parol-77", "new_password2": "Drugoi-Parol-77",
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.login("ivanov@hotel.ru", "Drugoi-Parol-77").status_code, 200)

    def test_weak_or_mismatched_password_rejected(self):
        self.auth()
        for new, again in (("1234", "1234"), (GOOD, GOOD + "x")):
            r = self.client.post("/api/auth/password/change/",
                                 {"new_password": new, "new_password2": again})
            self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_change_needs_login(self):
        r = self.client.post("/api/auth/password/change/",
                             {"new_password": GOOD, "new_password2": GOOD})
        self.assertIn(r.status_code, (401, 403))

    # --- восстановление ------------------------------------------------------
    def _reset_link(self):
        self.assertEqual(len(mail.outbox), 1)
        m = re.search(r"/reset-password/([^/\s]+)/([^/\s]+)", mail.outbox[0].body)
        self.assertIn("https://sed.example.ru/app/?to=/reset-password/", mail.outbox[0].body)
        return m.group(1), m.group(2)

    def test_reset_flow_sets_password_and_logs_in(self):
        r = self.client.post("/api/auth/password/reset/", {"email": "Ivanov@Hotel.ru"})
        self.assertEqual(r.status_code, 200)
        uid, token = self._reset_link()

        r = self.client.post("/api/auth/password/reset/confirm/", {
            "uid": uid, "token": token, "new_password": GOOD, "new_password2": GOOD,
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data["token"])
        self.assertEqual(self.login("ivanov@hotel.ru", GOOD).status_code, 200)

        # ссылка одноразовая
        r = self.client.post("/api/auth/password/reset/confirm/", {
            "uid": uid, "token": token, "new_password": "Eshche-Odin-55", "new_password2": "Eshche-Odin-55",
        })
        self.assertEqual(r.status_code, 400)

    def test_reset_unknown_email_same_answer_no_mail(self):
        known = self.client.post("/api/auth/password/reset/", {"email": "ivanov@hotel.ru"})
        unknown = self.client.post("/api/auth/password/reset/", {"email": "nobody@hotel.ru"})
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_rate_limited_per_address(self):
        self.client.post("/api/auth/password/reset/", {"email": "ivanov@hotel.ru"})
        self.client.post("/api/auth/password/reset/", {"email": "ivanov@hotel.ru"})
        self.assertEqual(len(mail.outbox), 1)

    def test_reset_bad_token_rejected(self):
        self.client.post("/api/auth/password/reset/", {"email": "ivanov@hotel.ru"})
        uid, _ = self._reset_link()
        r = self.client.post("/api/auth/password/reset/confirm/", {
            "uid": uid, "token": "bad-token", "new_password": GOOD, "new_password2": GOOD,
        })
        self.assertEqual(r.status_code, 400)

    def test_reset_for_inactive_profile_sends_nothing(self):
        self.profile.is_active = False
        self.profile.save()
        self.client.post("/api/auth/password/reset/", {"email": "ivanov@hotel.ru"})
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_for_employee_who_never_logged_in(self):
        UserProfile.objects.create(fio="Петров Пётр", bitrix_id=777, email="petrov@hotel.ru")
        self.client.post("/api/auth/password/reset/", {"email": "petrov@hotel.ru"})
        uid, token = self._reset_link()
        r = self.client.post("/api/auth/password/reset/confirm/", {
            "uid": uid, "token": token, "new_password": GOOD, "new_password2": GOOD,
        })
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["bitrix_id"], 777)
        self.assertEqual(self.login("petrov@hotel.ru", GOOD).status_code, 200)

    def test_login_by_email_when_username_is_b24(self):
        u = User.objects.create(username="b24_900", email="")
        u.set_password(GOOD)
        u.save()
        UserProfile.objects.create(fio="Сидоров", bitrix_id=900, email="sidorov@hotel.ru", auth_user=u)
        self.assertEqual(self.login("sidorov@hotel.ru", GOOD).status_code, 200)
