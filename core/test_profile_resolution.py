"""
Вход через Битрикс: профиль ищется по Битрикс ID, затем по почте. Почта может
перейти к другой учётке (личный ящик отдали групповому аккаунту службы) —
тогда чужой профиль и чужая учётка входа отдаваться не должны.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.auth_views import resolve_or_provision_profile
from core.models import UserProfile

User = get_user_model()


class ProfileResolutionTests(TestCase):
    def setUp(self):
        self.owner_user = User.objects.create(username="it@hotel.ru", email="it@hotel.ru")
        self.owner = UserProfile.objects.create(
            fio="Прокопьев", bitrix_id=2712, email="it@hotel.ru", auth_user=self.owner_user,
        )

    def test_same_bitrix_id_finds_owner(self):
        self.assertEqual(resolve_or_provision_profile(2712, "itm@hotel.ru").pk, self.owner.pk)

    def test_address_reused_by_other_bitrix_account_gets_own_profile(self):
        p = resolve_or_provision_profile(9999, "it@hotel.ru", "Служба ИТ")
        self.assertNotEqual(p.pk, self.owner.pk)
        self.assertEqual(p.bitrix_id, 9999)
        # и не делит учётку входа (токен) с прежним владельцем адреса
        self.assertNotEqual(p.auth_user_id, self.owner_user.pk)
        self.assertEqual(p.auth_user.username, "b24_9999")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.bitrix_id, 2712)

    def test_email_still_links_profile_without_bitrix_id(self):
        UserProfile.objects.create(fio="Новичок", email="new@hotel.ru")
        p = resolve_or_provision_profile(5000, "NEW@hotel.ru")
        self.assertEqual((p.fio, p.bitrix_id), ("Новичок", 5000))
