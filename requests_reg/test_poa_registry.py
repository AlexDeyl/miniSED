"""
Нумерация доверенностей по маскам юрлиц и реестр доверенностей и МЧД
(ТЗ «Нумерация доверенностей и реестр доверенностей»).
"""

from datetime import date, timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Organization, Role, UserProfile
from documents import services as docsvc

from . import constants as C
from . import registry, services
from .models import PoaNumbering, PoaRegistryChange, PoaRegistryEntry, RegulatoryRequest, RoleAssignment

INITIATOR, LAWYER, ADMIN, OUTSIDER, DEV = 1, 30, 50, 60, 1535


def api(uid):
    c = APIClient()
    c.credentials(HTTP_X_B24_USER=str(uid))
    return c


class MaskTests(TestCase):
    def test_masks_from_tz(self):
        d = date(2026, 9, 15)
        cases = {
            'АО "Отель Введенский"': "Д-07/26",
            'АО СЗ "Отель Введенский"': "Д-СЗ/07-2026",
            "АО «СЗ «Отель Введенский»": "Д-СЗ/07-2026",
            'ООО "Мир Эстейт"': "Д-07/09-2026МЭ",
            "АО Блюхера 6": "Д-Б6/07-2026",
            'ООО "Управление Отелями"': "Д-УО/07-2026",
            'ООО "Невесомость"': "Д-Н-26/07",
        }
        for name, expected in cases.items():
            org = Organization(short_name=name)
            self.assertEqual(registry.format_number(registry.default_mask(org), 7, d), expected, name)

    def test_three_digit_and_default_mask(self):
        self.assertEqual(registry.format_number("Д-Н-{ГГ}/{ХХ}", 123, date(2027, 1, 2)), "Д-Н-27/123")
        self.assertEqual(registry.default_mask(Organization(short_name="ООО Новое")), C.POA_DEFAULT_MASK)

    def test_mask_validation(self):
        self.assertIsNone(registry.mask_error("Д-{ХХ}/{ГГ}"))
        self.assertIsNotNone(registry.mask_error("Д-/{ГГ}"))
        self.assertIsNotNone(registry.mask_error("Д-{ХХ}/{YY}"))


class RegistryFlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name='ООО "Невесомость"')
        self.other = Organization.objects.create(short_name='ООО "Управление Отелями"')
        law = UserProfile.objects.create(fio="Юрист Иванова", bitrix_id=LAWYER, email="l@x.ru", is_active=True)
        law.roles.add(Role.objects.get(code="lawyer"))
        adm = UserProfile.objects.create(fio="Админ", bitrix_id=ADMIN, email="a@x.ru", is_active=True)
        adm.roles.add(Role.objects.get(code="sys_admin"))
        UserProfile.objects.create(fio="Посторонний", bitrix_id=OUTSIDER, email="o@x.ru", is_active=True)

    def _to_legal(self, org=None, rtype=C.TYPE_POA, **data):
        return RegulatoryRequest.objects.create(
            request_type=rtype, organization=org or self.org, status=C.STATUS_TO_LEGAL,
            initiator_b24_id=INITIATOR, subject_name="Соколинский Владислав Борисович",
            number="ДОВ-000001", data=data,
        )

    def _take(self, req):
        r = api(LAWYER).post(f"/api/reg/requests/{req.id}/take/")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    # --- присвоение номера при «Взять в работу» ---
    def test_take_assigns_number_and_fills_registry(self):
        req = self._to_legal(
            target_org="КППИР", powers=["court"], power_templates=["ПОЧТА"],
            term_type="period", term_to="2027-03-31",
        )
        body = self._take(req)
        yy = timezone.localdate().year % 100
        self.assertEqual(body["poa_number"], f"Д-Н-{yy:02d}/01")
        e = PoaRegistryEntry.objects.get(request=req)
        self.assertEqual(e.kind, C.REGISTRY_POA)
        self.assertEqual(e.organization, self.org)
        self.assertEqual(e.representative, "Соколинский Владислав Борисович")
        self.assertEqual(e.code, "ПОЧТА")
        self.assertIn("КППИР", e.powers)
        self.assertIn("Почта России", e.powers)
        self.assertEqual(e.valid_until, date(2027, 3, 31))
        self.assertEqual(e.issue_date, timezone.localdate())

    def test_sequence_shared_by_poa_and_mchd_per_org(self):
        n1 = self._take(self._to_legal())["poa_number"]
        n2 = self._take(self._to_legal(rtype=C.TYPE_MCHD))["poa_number"]
        n3 = self._take(self._to_legal(org=self.other))["poa_number"]
        y = timezone.localdate().year
        self.assertEqual([n1[-2:], n2[-2:]], ["01", "02"])
        self.assertEqual(n3, f"Д-УО/01-{y}")
        self.assertEqual(PoaRegistryEntry.objects.get(number=n2).kind, C.REGISTRY_MCHD)

    def test_new_year_resets_counter(self):
        PoaNumbering.objects.create(organization=self.org, mask="Д-Н-{ГГ}/{ХХ}", year=2025, last_seq=40)
        self.assertEqual(registry.allocate_number(self.org, date(2026, 1, 10))[0], "Д-Н-26/01")

    def test_manual_counter_and_taken_number_skipped(self):
        y = timezone.localdate().year
        r = api(LAWYER).patch("/api/reg/poa-registry/numbering/",
                              {"organization": self.org.id, "last_seq": 15}, format="json")
        self.assertEqual(r.status_code, 200)
        row = next(x for x in r.json() if x["organization"] == self.org.id)
        self.assertEqual(row["next_number"], f"Д-Н-{y % 100:02d}/16")
        # 16 уже внесён в реестр руками — берём 17
        PoaRegistryEntry.objects.create(kind=C.REGISTRY_POA, organization=self.org,
                                        number=f"Д-Н-{y % 100:02d}/16")
        self.assertEqual(self._take(self._to_legal())["poa_number"], f"Д-Н-{y % 100:02d}/17")

    def test_bad_mask_rejected(self):
        r = api(LAWYER).patch("/api/reg/poa-registry/numbering/",
                              {"organization": self.org.id, "mask": "Д-Н/{ГГ}"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_ecp_and_check_not_registered(self):
        ecp = RegulatoryRequest.objects.create(request_type=C.TYPE_ECP, organization=self.org)
        self.assertIsNone(registry.register_request(ecp))

    def test_sfr_mchd_registered_on_dev_take(self):
        RoleAssignment.objects.create(role_code=C.ROLE_SFR_EXECUTOR, user_b24_id=DEV)
        req = RegulatoryRequest.objects.create(
            request_type=C.TYPE_MCHD, organization=self.org, status=C.STATUS_TO_DEV,
            data={"power_templates": ["СФР"]},
        )
        services.dev_take_in_work(req, by_b24_id=DEV)
        self.assertEqual(PoaRegistryEntry.objects.get(request=req).kind, C.REGISTRY_MCHD)

    def test_executed_revocation_marks_entry(self):
        poa = self._to_legal()
        self._take(poa)
        rev = RegulatoryRequest.objects.create(
            request_type=C.TYPE_REVOKE, organization=self.org, status=C.STATUS_LEGAL_WORK,
            source_request=poa, data={"revoke_reason": "dismissal", "revoke_date": "2026-10-01"},
        )
        doc = docsvc.create_document(title="Уведомление", linked_object=rev, created_by_b24_id=LAWYER)
        docsvc.add_version(doc, SimpleUploadedFile("n.pdf", b"%PDF"), uploaded_by_b24_id=LAWYER)
        services.execute(rev, delivery_method="edo")
        e = PoaRegistryEntry.objects.get(request=poa)
        self.assertEqual(e.revoked_at, date(2026, 10, 1))
        self.assertEqual(registry.validity(e, date(2026, 10, 2)), C.VALIDITY_REVOKED)

    # --- доступ ---
    def test_access_only_legal_and_admin_reads(self):
        self.assertEqual(api(OUTSIDER).get("/api/reg/poa-registry/").status_code, 403)
        self.assertEqual(api(LAWYER).get("/api/reg/poa-registry/").status_code, 200)
        self.assertEqual(api(ADMIN).get("/api/reg/poa-registry/").status_code, 200)
        r = api(ADMIN).post("/api/reg/poa-registry/",
                            {"kind": "poa", "organization": self.org.id}, format="json")
        self.assertEqual(r.status_code, 403)

    # --- правка и журнал правок ---
    def test_edit_logged_and_history_for_superuser_only(self):
        req = self._to_legal()
        self._take(req)
        e = PoaRegistryEntry.objects.get(request=req)
        r = api(LAWYER).patch(f"/api/reg/poa-registry/{e.id}/",
                              {"powers": "КППИР (Алкогольная лицензия)", "code": e.code}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["powers"], "КППИР (Алкогольная лицензия)")
        ch = PoaRegistryChange.objects.get(entry=e, field="powers")
        self.assertEqual((ch.new_value, ch.changed_by_b24_id), ("КППИР (Алкогольная лицензия)", LAWYER))
        # неизменённая графа в журнал не попадает
        self.assertFalse(PoaRegistryChange.objects.filter(entry=e, field="code").exists())
        self.assertEqual(api(LAWYER).get(f"/api/reg/poa-registry/{e.id}/history/").status_code, 404)
        hist = api(ADMIN).get(f"/api/reg/poa-registry/{e.id}/history/").json()
        self.assertEqual(hist[0]["changed_by_name"], "Юрист Иванова")
        self.assertEqual(hist[0]["field_display"], "Полномочия")

    def test_manual_entry_with_number_and_delete_rules(self):
        r = api(LAWYER).post("/api/reg/poa-registry/", {
            "kind": "mchd", "organization": self.other.id, "representative": "Шкилева Э. М.",
            "issue_date": "2026-10-05", "assign_number": True,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["number"], "Д-УО/01-2026")
        self.assertEqual(r.json()["request_status_display"], "Внесена вручную")
        self.assertEqual(api(LAWYER).delete(f"/api/reg/poa-registry/{r.json()['id']}/").status_code, 204)
        req = self._to_legal()
        self._take(req)
        e = PoaRegistryEntry.objects.get(request=req)
        self.assertEqual(api(LAWYER).delete(f"/api/reg/poa-registry/{e.id}/").status_code, 403)

    def test_filters_and_status_column(self):
        today = timezone.localdate()
        mk = lambda **kw: PoaRegistryEntry.objects.create(organization=self.org, **kw)  # noqa: E731
        expired = mk(kind="poa", valid_until=today - timedelta(days=1))
        soon = mk(kind="mchd", valid_until=today + timedelta(days=10))
        ok = mk(kind="poa", valid_until=today + timedelta(days=300), representative="Шаурин")
        def ids(qs):
            return {x["id"] for x in api(LAWYER).get(f"/api/reg/poa-registry/?{qs}").json()}
        self.assertEqual(ids("validity=expired"), {expired.id})
        self.assertEqual(ids("validity=expiring"), {soon.id})
        self.assertEqual(ids("validity=active"), {ok.id})
        self.assertEqual(ids("kind=mchd"), {soon.id})
        self.assertEqual(ids("q=Шаурин"), {ok.id})

        req = self._to_legal()
        self._take(req)
        row = next(x for x in api(LAWYER).get("/api/reg/poa-registry/").json() if x["request"] == req.id)
        self.assertEqual(row["request_status_display"], "В работе у юристов")

    def test_export_xlsx(self):
        self._take(self._to_legal())
        r = api(LAWYER).get("/api/reg/poa-registry/export/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b"".join(r.streaming_content).startswith(b"PK"))

    def test_backfill_command_without_numbers(self):
        from django.core.management import call_command

        old = RegulatoryRequest.objects.create(
            request_type=C.TYPE_POA, organization=self.org, status=C.STATUS_CLOSED,
            subject_name="Старый", executed_at=timezone.now(),
        )
        with mock.patch("sys.stdout"):
            call_command("poa_registry_backfill")
            call_command("poa_registry_backfill")
        e = PoaRegistryEntry.objects.get(request=old)
        self.assertEqual(e.number, "")
        self.assertEqual(PoaRegistryEntry.objects.filter(request=old).count(), 1)
