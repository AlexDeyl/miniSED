"""
Отбор заявок галочками (компания, инициатор, ЦФО, статус) и варианты для
галочек (facets) — в «Регламентных заявках» и в «Работе юристов».
"""

from django.test import TestCase
from rest_framework.test import APIClient

from core.models import CFO, Organization, Role, UserProfile

from . import constants as C
from .models import RegulatoryRequest

LAWYER = 30


def api(uid):
    c = APIClient()
    c.credentials(HTTP_X_B24_USER=str(uid))
    return c


def ids(resp):
    return {r["id"] for r in resp.json()}


class FilterTests(TestCase):
    def setUp(self):
        self.uk = Organization.objects.create(short_name="УК")
        self.vv = Organization.objects.create(short_name="Введенский")
        self.sales = CFO.objects.create(name="Продажи", category="sales")
        self.buh = CFO.objects.create(name="Бухгалтерия", category="accounting")
        UserProfile.objects.create(fio="Иванова Анна", bitrix_id=1, is_active=True)
        UserProfile.objects.create(fio="Петров Пётр", bitrix_id=2, is_active=True)
        p = UserProfile.objects.create(fio="Юрист", bitrix_id=LAWYER, is_active=True)
        p.roles.add(Role.objects.get(code="lawyer"))

        def mk(org, cfo, init, status, rtype=C.TYPE_POA):
            return RegulatoryRequest.objects.create(
                request_type=rtype, organization=org, cfo=cfo,
                initiator_b24_id=init, status=status,
            ).id

        self.a = mk(self.uk, self.sales, 1, C.STATUS_TO_LEGAL)
        self.b = mk(self.vv, self.buh, 1, C.STATUS_CLOSED)
        self.c = mk(self.vv, self.sales, 2, C.STATUS_LEGAL_WORK, C.TYPE_MCHD)
        self.d = mk(self.uk, None, 2, C.STATUS_TO_LEGAL)
        self.draft = mk(self.uk, self.sales, 2, C.STATUS_DRAFT)

    def q(self, uid, url):
        return api(uid).get(url)

    # --- «Работа юристов» ---
    def test_legal_filters_combine_and_ignore_tab(self):
        base = "/api/reg/requests/legal_queue/?scope=new"
        self.assertEqual(ids(self.q(LAWYER, base)), {self.a, self.d})
        # отбор — по всем статусам, вкладка «Новые» не сужает
        self.assertEqual(ids(self.q(LAWYER, base + f"&organization={self.vv.id}")), {self.b, self.c})
        # ИЛИ внутри поля, И между полями
        self.assertEqual(ids(self.q(LAWYER, base + "&initiator=1,2&status=to_legal")), {self.a, self.d})
        self.assertEqual(ids(self.q(LAWYER, base + f"&initiator=2&cfo={self.sales.id}")), {self.c})
        # без ЦФО
        self.assertEqual(ids(self.q(LAWYER, base + "&cfo=none")), {self.d})
        # черновики чужие юристу не видны и отбором
        self.assertNotIn(self.draft, ids(self.q(LAWYER, base + "&initiator=2")))

    def test_list_items_carry_initiator_and_cfo(self):
        row = next(r for r in self.q(LAWYER, "/api/reg/requests/legal_queue/?scope=new").json()
                   if r["id"] == self.a)
        self.assertEqual((row["initiator_name"], row["cfo_name"]), ("Иванова Анна", "Продажи"))

    def test_legal_facets_counts_and_cross_filtering(self):
        f = self.q(LAWYER, "/api/reg/requests/facets/?view=legal").json()
        inits = {x["label"]: x["count"] for x in f["initiator"]}
        self.assertEqual(inits, {"Иванова Анна": 2, "Петров Пётр": 2})  # черновик не считается
        self.assertIn({"value": "none", "label": "Без ЦФО", "count": 1}, f["cfo"])
        # статусы — в порядке жизненного цикла
        self.assertEqual([(x["value"], x["count"]) for x in f["status"]],
                         [("to_legal", 2), ("legal_work", 1), ("closed", 1)])

        # отметили юрлицо — инициаторы пересчитались, а сами юрлица — нет
        f = self.q(LAWYER, f"/api/reg/requests/facets/?view=legal&organization={self.vv.id}").json()
        self.assertEqual({x["label"]: x["count"] for x in f["initiator"]},
                         {"Иванова Анна": 1, "Петров Пётр": 1})
        self.assertEqual(len(f["organization"]), 2)

    def test_legal_facets_require_lawyer(self):
        self.assertEqual(self.q(1, "/api/reg/requests/facets/?view=legal").status_code, 403)

    # --- «Регламентные заявки» (только свои) ---
    def test_my_list_filters_and_facets_stay_within_mine(self):
        self.assertEqual(ids(self.q(1, "/api/reg/requests/")), {self.a, self.b})
        self.assertEqual(ids(self.q(1, f"/api/reg/requests/?organization={self.vv.id}")), {self.b})
        self.assertEqual(ids(self.q(1, "/api/reg/requests/?status=to_legal,closed")), {self.a, self.b})
        f = self.q(1, "/api/reg/requests/facets/").json()
        self.assertEqual([x["label"] for x in f["initiator"]], ["Иванова Анна"])  # чужих нет
        self.assertEqual({x["label"] for x in f["organization"]}, {"УК", "Введенский"})
