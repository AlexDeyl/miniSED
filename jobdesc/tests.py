"""
Тесты заявок на согласование ДИ: маршрут по ЦФО/юрлицу/флажку, автозакрытие
этапа инициатора, круги, исполнение отделом персонала, синхронизация отдела
из Битрикса.
"""

from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from approvalflow.models import ApprovalParticipant
from core.models import CFO, Facility, Organization
from requests_reg import constants as R
from requests_reg.models import RoleAssignment

from . import constants as K
from . import hr_staff, routing, services
from .models import HrStaff, JobDescription

# Кто есть кто: кадровик-инициатор, руководитель ЦФО, коммерческий директор,
# главбух, техдиректор, операционный, ресторанная служба, финдиректор,
# снабжение, рук. отдела персонала, подписанты юрлиц.
HR, HR2, CFO_HEAD, KSENIA, ACC, TECH, OPS, SHAHOV, FIN, MTS, HR_HEAD, TAR, SINITSYNA = (
    501, 502, 600, 1595, 601, 602, 603, 867, 915, 991, 947, 857, 865,
)
OUTSIDER = 777


def api(uid=None):
    c = APIClient()
    if uid is not None:
        c.credentials(HTTP_X_B24_USER=str(uid))
    return c


class BaseData(TestCase):
    def setUp(self):
        self.uk = Organization.objects.create(short_name='ООО "Управление Отелями"')
        self.nev = Organization.objects.create(short_name='ООО "Невесомость"')
        self.hotel = Facility.objects.create(name="Отель Svet", organization=self.uk)
        self.cfo = {
            cat: CFO.objects.create(name=f"ЦФО {cat}", category=cat)
            for cat in ("sales", "accounting", "its_it", "sgh", "restaurant", "finance", "mts", "other")
        }
        for c in self.cfo.values():
            RoleAssignment.objects.create(role_code=R.ROLE_CFO_HEAD, cfo=c, user_b24_id=CFO_HEAD, user_name="Рук. ЦФО")
        for code, uid in (
            (R.ROLE_COMMERCIAL_DIRECTOR, KSENIA), (R.ROLE_CHIEF_ACCOUNTANT, ACC),
            (R.ROLE_TECH_DIRECTOR, TECH), (R.ROLE_OPS_DIRECTOR, OPS),
            (R.ROLE_RESTAURANT_DIRECTOR, SHAHOV), (R.ROLE_FINANCE_DIRECTOR, FIN),
            (R.ROLE_PROCUREMENT_HEAD, MTS), (R.ROLE_HR_HEAD, HR_HEAD),
        ):
            RoleAssignment.objects.create(role_code=code, user_b24_id=uid, user_name=f"#{uid}")
        RoleAssignment.objects.create(role_code=R.ROLE_FINAL_SIGNER, organization=self.uk, user_b24_id=TAR, user_name="Ткачев")
        RoleAssignment.objects.create(role_code=R.ROLE_FINAL_SIGNER, organization=self.nev, user_b24_id=SINITSYNA, user_name="Синицына")
        HrStaff.objects.create(b24_user_id=HR, fio="Кадровик Анна")
        HrStaff.objects.create(b24_user_id=HR2, fio="Кадровик Олег")

    def _jd(self, cat="other", org=None, **kw):
        kw.setdefault("position_name", "Менеджер по продажам")
        kw.setdefault("initiator_b24_id", HR)
        return services.create_jobdesc(
            organization=org or self.uk, cfo=self.cfo[cat], facility=self.hotel, **kw
        )

    @staticmethod
    def _codes(route):
        return [s["role_code"] for s in route]

    def _participants(self, jd, manual=None):
        """Участники из предпросмотра; пустые «при наличии» не отправляются."""
        manual = manual or {}
        out = []
        for s in routing.build_route(jd):
            uid = manual.get(s["role_code"], s["b24_user_id"])
            if not uid and not s["group"]:
                continue
            out.append({"type": "internal", "b24_user_id": uid, "role": s["role_code"]})
        return [{**p, "order": i} for i, p in enumerate(out)]


class RoutingTests(BaseData):
    def test_base_route(self):
        codes = self._codes(routing.build_route(self._jd("other")))
        self.assertEqual(codes, [
            R.ROLE_HR_SPECIALIST, R.ROLE_CFO_HEAD, R.ROLE_ADMIN_HEAD, R.ROLE_FUNCTIONAL_HEAD,
            R.ROLE_HR_HEAD, R.ROLE_FINAL_SIGNER,
        ])

    def test_hr_initiator_is_first_approver(self):
        slot = routing.build_route(self._jd())[0]
        self.assertEqual(slot["b24_user_id"], HR)
        self.assertTrue(slot["auto_by_initiator"])

    def test_non_hr_initiator_picks_hr_manually(self):
        slot = routing.build_route(self._jd(initiator_b24_id=OUTSIDER))[0]
        self.assertIsNone(slot["b24_user_id"])
        self.assertTrue(slot["needs_manual"])
        self.assertTrue(slot["hr_pick"])

    def test_optional_heads_are_not_mandatory(self):
        route = routing.build_route(self._jd())
        for code in (R.ROLE_ADMIN_HEAD, R.ROLE_FUNCTIONAL_HEAD):
            slot = next(s for s in route if s["role_code"] == code)
            self.assertTrue(slot["optional"])
            self.assertFalse(slot["needs_manual"])

    def test_category_extras(self):
        cases = {
            "sales": R.ROLE_COMMERCIAL_DIRECTOR,
            "accounting": R.ROLE_CHIEF_ACCOUNTANT,
            "its_it": R.ROLE_TECH_DIRECTOR,
            "sgh": R.ROLE_OPS_DIRECTOR,
            "restaurant": R.ROLE_RESTAURANT_DIRECTOR,
            "finance": R.ROLE_FINANCE_DIRECTOR,
            "mts": R.ROLE_PROCUREMENT_HEAD,
        }
        for cat, role in cases.items():
            with self.subTest(cat=cat):
                codes = self._codes(routing.build_route(self._jd(cat)))
                self.assertIn(role, codes)
                # доп. согласующий — между функциональным руководителем и рук. отдела персонала
                self.assertLess(codes.index(R.ROLE_FUNCTIONAL_HEAD), codes.index(role))
                self.assertLess(codes.index(role), codes.index(R.ROLE_HR_HEAD))

    def test_its_it_goes_to_tech_not_ops(self):
        codes = self._codes(routing.build_route(self._jd("its_it")))
        self.assertIn(R.ROLE_TECH_DIRECTOR, codes)
        self.assertNotIn(R.ROLE_OPS_DIRECTOR, codes)

    def test_nevesomost_adds_restaurant_director(self):
        codes = self._codes(routing.build_route(self._jd("other", org=self.nev)))
        self.assertIn(R.ROLE_RESTAURANT_DIRECTOR, codes)

    def test_nonstandard_adds_legal_and_finance(self):
        route = routing.build_route(self._jd("other", is_nonstandard=True))
        codes = self._codes(route)
        self.assertLess(codes.index(R.ROLE_LEGAL_DEPT), codes.index(R.ROLE_FINANCE_DIRECTOR))
        self.assertLess(codes.index(R.ROLE_FINANCE_DIRECTOR), codes.index(R.ROLE_HR_HEAD))
        self.assertTrue(next(s for s in route if s["role_code"] == R.ROLE_LEGAL_DEPT)["group"])

    def test_nonstandard_finance_category_no_duplicate(self):
        codes = self._codes(routing.build_route(self._jd("finance", is_nonstandard=True)))
        self.assertEqual(codes.count(R.ROLE_FINANCE_DIRECTOR), 1)

    def test_signer_by_organization(self):
        route = routing.build_route(self._jd("other", org=self.nev))
        self.assertEqual(route[-1]["role_code"], R.ROLE_FINAL_SIGNER)
        self.assertEqual(route[-1]["b24_user_id"], SINITSYNA)

    def test_signer_without_org_assignment_is_manual(self):
        """Глобальный ГД не подставляется: у каждого юрлица свой подписант."""
        org = Organization.objects.create(short_name="АГКМ")
        RoleAssignment.objects.create(role_code=R.ROLE_FINAL_SIGNER, user_b24_id=TAR)
        slot = routing.build_route(self._jd("other", org=org))[-1]
        self.assertTrue(slot["needs_manual"])

    def test_same_person_once(self):
        """Руководитель ЦФО он же коммерческий директор — один этап."""
        RoleAssignment.objects.filter(role_code=R.ROLE_CFO_HEAD, cfo=self.cfo["sales"]).update(user_b24_id=KSENIA)
        route = routing.build_route(self._jd("sales"))
        self.assertNotIn(R.ROLE_COMMERCIAL_DIRECTOR, self._codes(route))
        head = next(s for s in route if s["role_code"] == R.ROLE_CFO_HEAD)
        self.assertEqual(head["merged_roles"], [R.ROLE_NAMES[R.ROLE_COMMERCIAL_DIRECTOR]])


class FlowTests(BaseData):
    def _submit(self, jd, **kw):
        return services.submit(jd, self._participants(jd, **kw), actor_b24_id=jd.initiator_b24_id)

    def _decide_all(self, jd):
        while True:
            p = services.current_pending_participant(services.get_approval(jd))
            if p is None:
                return
            services.decide(jd, p.id, "approve", actor_b24_id=p.b24_user_id)
            jd.refresh_from_db()

    def test_initiator_step_auto_approved(self):
        jd = self._jd()
        self._submit(jd)
        jd.refresh_from_db()
        self.assertEqual(jd.status, K.STATUS_ON_APPROVAL)
        first = services.get_approval(jd).rounds.get().participants.order_by("order").first()
        self.assertEqual(first.decision, ApprovalParticipant.DECISION_APPROVED)
        self.assertEqual(first.decision_comment, services.AUTO_APPROVE_COMMENT)
        # очередь сразу у руководителя ЦФО
        self.assertEqual(services.current_pending_participant(services.get_approval(jd)).b24_user_id, CFO_HEAD)

    def test_non_hr_initiator_not_auto_approved(self):
        jd = self._jd(initiator_b24_id=OUTSIDER)
        self._submit(jd, manual={R.ROLE_HR_SPECIALIST: HR2})
        pending = services.current_pending_participant(services.get_approval(jd))
        self.assertEqual(pending.b24_user_id, HR2)

    def test_full_flow_to_hr_and_close(self):
        jd = self._jd()
        self._submit(jd)
        self._decide_all(jd)
        self.assertEqual(jd.status, K.STATUS_TO_HR)

        services.take_in_work(jd, executor_b24_id=HR2)
        services.set_status(jd, K.STATUS_SIGNING, by_b24_id=HR2)
        self.assertEqual(jd.status, K.STATUS_SIGNING)

        with self.assertRaises(services.JobDescError):  # нет файла ДИ
            services.execute(jd, executor_b24_id=HR2, transfer_method="email")
        jd.documents.create(title="ДИ.pdf", document_type=K.DOC_TYPE_FINAL)
        with self.assertRaises(services.JobDescError):  # нет способа передачи
            services.execute(jd, executor_b24_id=HR2, transfer_method="")
        services.execute(jd, executor_b24_id=HR2, transfer_method="email")
        self.assertEqual(jd.status, K.STATUS_EXECUTED)

        services.acknowledge(jd, by_b24_id=HR)
        self.assertEqual(jd.status, K.STATUS_CLOSED)
        self.assertIsNotNone(jd.received_at)

    def test_return_and_new_round_auto_approves_again(self):
        jd = self._jd()
        self._submit(jd)
        services.return_for_revision(jd, by_b24_id=CFO_HEAD, comment="Поправьте обязанности")
        jd.refresh_from_db()
        self.assertEqual(jd.status, K.STATUS_RETURNED)
        self._submit(jd)
        jd.refresh_from_db()
        approval = services.get_approval(jd)
        self.assertEqual(approval.current_round, 2)
        first = approval.rounds.get(round_number=2).participants.order_by("order").first()
        self.assertEqual(first.decision, ApprovalParticipant.DECISION_APPROVED)

    def test_legal_group_needs_lawyer(self):
        jd = self._jd(is_nonstandard=True)
        self._submit(jd)
        jd.refresh_from_db()
        services.decide(jd, services.current_pending_participant(services.get_approval(jd)).id,
                        "approve", actor_b24_id=CFO_HEAD)
        legal = services.current_pending_participant(services.get_approval(jd))
        self.assertTrue(services.is_group_legal(legal))
        with mock.patch("jobdesc.services.is_lawyer", return_value=False):
            with self.assertRaises(services.JobDescError):
                services.decide(jd, legal.id, "approve", actor_b24_id=OUTSIDER)
        with mock.patch("jobdesc.services.is_lawyer", return_value=True):
            services.decide(jd, legal.id, "approve", actor_b24_id=4242)
        legal.refresh_from_db()
        self.assertEqual(legal.b24_user_id, 4242)

    def test_duplicates_in_participants_collapsed(self):
        jd = self._jd()
        parts = self._participants(jd)
        parts.insert(2, {"type": "internal", "b24_user_id": CFO_HEAD, "role": "", "order": 2})
        services.submit(jd, parts, actor_b24_id=HR)
        ids = list(services.get_approval(jd).rounds.get().participants.values_list("b24_user_id", flat=True))
        self.assertEqual(len(ids), len(set(ids)))


class ApiTests(BaseData):
    def test_create_preview_submit(self):
        r = api(HR).post("/api/jobdesc/", {
            "position_name": "Горничная", "organization": self.uk.id,
            "cfo": self.cfo["sgh"].id, "facility": self.hotel.id,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        jd_id = r.json()["id"]
        self.assertTrue(r.json()["number"].startswith("ДИ-"))

        route = api(HR).get(f"/api/jobdesc/{jd_id}/route_preview/").json()["route"]
        self.assertIn(R.ROLE_OPS_DIRECTOR, self._codes(route))
        parts = [
            {"b24_user_id": s["b24_user_id"], "role": s["role_code"], "order": i}
            for i, s in enumerate(x for x in route if x["b24_user_id"])
        ]
        r = api(HR).post(f"/api/jobdesc/{jd_id}/submit/", {"participants": parts}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], K.STATUS_ON_APPROVAL)

        # руководителю ЦФО — в «Требует действия», постороннему карточка не видна
        self.assertEqual([x["id"] for x in api(CFO_HEAD).get("/api/jobdesc/todo/").json()], [jd_id])
        self.assertEqual(api(OUTSIDER).get(f"/api/jobdesc/{jd_id}/").status_code, 404)

    def test_cfo_of_other_org_rejected(self):
        foreign = CFO.objects.create(name="СГХ Невесомость", organization=self.nev, category="sgh")
        r = api(HR).post("/api/jobdesc/", {
            "position_name": "Горничная", "organization": self.uk.id, "cfo": foreign.id,
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_hr_queue_and_execution(self):
        jd = self._jd()
        services.submit(jd, self._participants(jd), actor_b24_id=HR)
        FlowTests._decide_all(self, jd)

        self.assertEqual(api(OUTSIDER).get("/api/jobdesc/hr_queue/").status_code, 403)
        new = api(HR2).get("/api/jobdesc/hr_queue/?scope=new").json()
        self.assertEqual([x["id"] for x in new], [jd.id])

        self.assertEqual(api(HR2).post(f"/api/jobdesc/{jd.id}/take/").status_code, 200)
        api(HR2).post("/api/documents/", {
            "title": "ДИ горничной", "linked_type": "jobdesc.jobdescription",
            "linked_id": jd.id, "document_type": K.DOC_TYPE_FINAL,
            "file": SimpleUploadedFile("di.pdf", b"%PDF-1.4"),
        })
        r = api(HR2).post(f"/api/jobdesc/{jd.id}/execute/", {"transfer_method": "in_person"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], K.STATUS_EXECUTED)

        # инициатору — в «Требует действия» до подтверждения
        self.assertIn(jd.id, [x["id"] for x in api(HR).get("/api/jobdesc/todo/").json()])
        self.assertEqual(api(HR2).post(f"/api/jobdesc/{jd.id}/acknowledge/").status_code, 403)
        r = api(HR).post(f"/api/jobdesc/{jd.id}/acknowledge/")
        self.assertEqual(r.json()["status"], K.STATUS_CLOSED)

    def test_meta_flags_hr(self):
        self.assertTrue(api(HR).get("/api/jobdesc/meta/").json()["is_hr_staff"])
        self.assertFalse(api(OUTSIDER).get("/api/jobdesc/meta/").json()["is_hr_staff"])


class HrSyncTests(TestCase):
    DEPARTMENTS = [
        {"ID": "1", "NAME": "Управляющая компания", "PARENT": ""},
        {"ID": "10", "NAME": "Отдел по работе с персоналом", "PARENT": "1"},
        {"ID": "11", "NAME": "Группа подбора", "PARENT": "10"},
        {"ID": "20", "NAME": "Отдел продаж", "PARENT": "1"},
    ]
    USERS = {
        "10": [{"ID": "947", "LAST_NAME": "Юшманова", "NAME": "Лариса", "WORK_POSITION": "Руководитель"}],
        "11": [{"ID": "1200", "LAST_NAME": "Петрова", "NAME": "Ирина", "WORK_POSITION": "Рекрутер"}],
    }

    def _client(self):
        client = mock.Mock()

        def call(method, params):
            if method == "department.get":
                return self.DEPARTMENTS
            return self.USERS.get(str(params["FILTER"]["UF_DEPARTMENT"]), [])

        client.call.side_effect = call
        return client

    def test_sync_takes_department_with_children(self):
        result = hr_staff.sync(self._client())
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            set(HrStaff.objects.values_list("b24_user_id", flat=True)), {947, 1200}
        )
        self.assertTrue(hr_staff.is_hr_staff(1200))

    def test_sync_deactivates_left_but_keeps_manual(self):
        HrStaff.objects.create(b24_user_id=5, fio="Ушла", source=HrStaff.SOURCE_BITRIX)
        HrStaff.objects.create(b24_user_id=6, fio="Добавлен руками", source=HrStaff.SOURCE_MANUAL)
        hr_staff.sync(self._client())
        self.assertFalse(HrStaff.objects.get(b24_user_id=5).is_active)
        self.assertTrue(HrStaff.objects.get(b24_user_id=6).is_active)

    def test_no_department_found(self):
        self.DEPARTMENTS = [{"ID": "1", "NAME": "Отдел продаж", "PARENT": ""}]
        with self.assertRaises(hr_staff.HrSyncError):
            hr_staff.sync(self._client())
