"""
Тесты маршрутизации и потока согласования договоров.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from approvalflow.models import Approval
from core.models import CFO, Organization, Role, UserProfile
from requests_reg import constants as R
from requests_reg.models import RoleAssignment

from . import constants, routing, services
from .models import Contract


def api(uid=None):
    c = APIClient()
    if uid is not None:
        c.credentials(HTTP_X_B24_USER=str(uid))
    return c


class RoutingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="АО Отель Введенский")
        self.nev = Organization.objects.create(short_name="ООО Невесомость")
        self.cfo_sales = CFO.objects.create(name="Отдел продаж", category="sales")
        self.cfo_mkt = CFO.objects.create(name="Маркетинг", category="marketing")
        self.cfo_other = CFO.objects.create(name="Прочее", category="other")

        # общефирменные назначения ролей (RoleAssignment из requests_reg)
        RoleAssignment.objects.create(role_code=R.ROLE_FINANCE_DIRECTOR, user_b24_id=500, user_name="Финдир")
        RoleAssignment.objects.create(role_code=R.ROLE_CFO_HEAD, cfo=self.cfo_sales, user_b24_id=501, user_name="Рук ЦФО продаж")
        RoleAssignment.objects.create(role_code=R.ROLE_SALES_HEAD, user_b24_id=502, user_name="Рук продаж")
        RoleAssignment.objects.create(role_code=R.ROLE_COMMERCIAL_DIRECTOR, user_b24_id=503, user_name="Коммерч дир")
        # ГД юрлица «Невесомость»
        RoleAssignment.objects.create(role_code=R.ROLE_FINAL_SIGNER, organization=self.nev, user_b24_id=504, user_name="ГД Невесомость")

    def _contract(self, **kw):
        kw.setdefault("organization", self.org)
        kw.setdefault("cfo", self.cfo_sales)
        kw.setdefault("title", "Договор поставки")
        return Contract.objects.create(**kw)

    def _codes(self, route):
        return [s["role_code"] for s in route]

    def test_sales_standard(self):
        route = routing.build_route(self._contract())
        # стандартный: без юротдела И без финдиректора (оба — по условию),
        # только рук. ЦФО → подписант (рук. продаж)
        self.assertEqual(
            self._codes(route),
            [R.ROLE_CFO_HEAD, R.ROLE_SALES_HEAD],
        )
        classes = {s["role_code"]: s["role_class"] for s in route}
        self.assertEqual(classes[R.ROLE_CFO_HEAD], constants.CLASS_APPROVER)
        self.assertEqual(classes[R.ROLE_SALES_HEAD], constants.CLASS_SIGNER)
        self.assertEqual([s["order"] for s in route], [0, 1])

    def test_marketing_uses_commercial_director(self):
        route = routing.build_route(self._contract(cfo=self.cfo_mkt))
        self.assertEqual(
            self._codes(route),
            [R.ROLE_CFO_HEAD, R.ROLE_COMMERCIAL_DIRECTOR],
        )

    def test_nonstandard_adds_legal_and_finance(self):
        route = routing.build_route(self._contract(is_nonstandard=True))
        codes = self._codes(route)
        # нетиповой → добавляются и юротдел, и финдиректор (в правильном порядке)
        self.assertEqual(
            codes,
            [R.ROLE_CFO_HEAD, R.ROLE_LEGAL_DEPT, R.ROLE_FINANCE_DIRECTOR, R.ROLE_SALES_HEAD],
        )
        legal = next(s for s in route if s["role_code"] == R.ROLE_LEGAL_DEPT)
        self.assertTrue(legal["group"])
        self.assertFalse(legal["needs_manual"])

    def test_disagreement_protocol_adds_legal_and_finance(self):
        route = routing.build_route(self._contract(has_disagreement_protocol=True))
        codes = self._codes(route)
        self.assertIn(R.ROLE_LEGAL_DEPT, codes)
        self.assertIn(R.ROLE_FINANCE_DIRECTOR, codes)

    def test_legal_and_finance_absent_when_standard(self):
        codes = self._codes(routing.build_route(self._contract()))
        self.assertNotIn(R.ROLE_LEGAL_DEPT, codes)
        self.assertNotIn(R.ROLE_FINANCE_DIRECTOR, codes)

    def test_gd_added_for_nevesomost_org(self):
        route = routing.build_route(self._contract(organization=self.nev))
        gd = next((s for s in route if s["role_code"] == R.ROLE_FINAL_SIGNER), None)
        self.assertIsNotNone(gd)
        # ГД показывается (у ЮО есть назначение), но человека выбирают вручную
        self.assertTrue(gd["needs_manual"])
        self.assertIsNone(gd["b24_user_id"])
        # у другого ЮО ГД нет
        route2 = routing.build_route(self._contract(organization=self.org))
        self.assertNotIn(R.ROLE_FINAL_SIGNER, self._codes(route2))

    def test_non_legal_slots_manual(self):
        # Согласующих (кроме юротдела и финдиректора) не подтягиваем автоматом.
        route = routing.build_route(self._contract())  # продажи, стандартный
        for s in route:
            if s["role_code"] in (R.ROLE_LEGAL_DEPT, R.ROLE_FINANCE_DIRECTOR):
                continue
            self.assertTrue(s["needs_manual"], s["role_code"])
            self.assertFalse(s["resolved"], s["role_code"])

    def test_finance_director_auto(self):
        # Финдиректор подставляется автоматически (как юротдел), без ручного выбора.
        route = routing.build_route(self._contract(is_nonstandard=True))
        fin = next(s for s in route if s["role_code"] == R.ROLE_FINANCE_DIRECTOR)
        self.assertTrue(fin["resolved"])
        self.assertFalse(fin["needs_manual"])
        self.assertEqual(fin["b24_user_id"], 500)
        # рук. ЦФО — по-прежнему ручной
        head = next(s for s in route if s["role_code"] == R.ROLE_CFO_HEAD)
        self.assertTrue(head["needs_manual"])


class FlowTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="АО Отель Введенский")
        self.cfo = CFO.objects.create(name="Отдел продаж", category="sales")
        RoleAssignment.objects.create(role_code=R.ROLE_FINANCE_DIRECTOR, user_b24_id=500)
        RoleAssignment.objects.create(role_code=R.ROLE_CFO_HEAD, cfo=self.cfo, user_b24_id=501)
        RoleAssignment.objects.create(role_code=R.ROLE_SALES_HEAD, user_b24_id=502)

    # Инициатор выбирает людей вручную (роли больше не подтягиваются автоматом).
    ROLE_USER = {
        R.ROLE_CFO_HEAD: 501, R.ROLE_SALES_HEAD: 502,
        R.ROLE_FINANCE_DIRECTOR: 500, R.ROLE_COMMERCIAL_DIRECTOR: 503,
    }

    def _participants(self, contract):
        parts = []
        for s in services.build_route(contract):
            uid = None if s["group"] else self.ROLE_USER.get(s["role_code"], 999)
            parts.append({
                "type": "internal", "b24_user_id": uid,
                "role": s["role_code"], "order": s["order"], "is_required": True,
            })
        return parts

    def test_full_sequential_approval(self):
        contract = services.create_contract(
            organization=self.org, cfo=self.cfo, title="Договор", initiator_b24_id=1,
        )
        self.assertTrue(contract.number.startswith("ДОГ-"))

        approval = services.submit(contract, self._participants(contract), actor_b24_id=1)
        contract.refresh_from_db()
        self.assertEqual(contract.status, constants.STATUS_ON_APPROVAL)

        # последовательно согласуем каждого ожидающего
        for _ in range(5):
            pending = services.current_pending_participant(services.get_approval(contract))
            if pending is None:
                break
            services.decide(contract, pending.id, "approve", actor_b24_id=pending.b24_user_id)

        contract.refresh_from_db()
        approval.refresh_from_db()
        self.assertEqual(approval.status, Approval.STATUS_COMPLETED)
        self.assertEqual(contract.status, constants.STATUS_APPROVED)

    def test_reject_sets_rejected(self):
        contract = services.create_contract(
            organization=self.org, cfo=self.cfo, title="Договор", initiator_b24_id=1,
        )
        services.submit(contract, self._participants(contract), actor_b24_id=1)
        pending = services.current_pending_participant(services.get_approval(contract))
        services.decide(contract, pending.id, "reject", "не согласен", actor_b24_id=pending.b24_user_id)
        contract.refresh_from_db()
        self.assertEqual(contract.status, constants.STATUS_REJECTED)


class ApiTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="АО Отель Введенский")
        self.cfo = CFO.objects.create(name="Отдел продаж", category="sales")
        RoleAssignment.objects.create(role_code=R.ROLE_FINANCE_DIRECTOR, user_b24_id=500)
        RoleAssignment.objects.create(role_code=R.ROLE_SALES_HEAD, user_b24_id=502)

    def test_requires_auth(self):
        self.assertIn(api().get("/api/contracts/").status_code, (401, 403))

    def test_create_and_route_preview(self):
        r = api(1).post("/api/contracts/", {
            "title": "Договор поставки", "organization": self.org.id,
            "cfo": self.cfo.id, "amount": "150000.00", "is_nonstandard": True,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        self.assertTrue(r.json()["number"].startswith("ДОГ-"))

        route = api(1).get(f"/api/contracts/{cid}/route_preview/").json()["route"]
        codes = [s["role_code"] for s in route]
        # нестандартный → юр-этап присутствует
        self.assertIn(R.ROLE_LEGAL_DEPT, codes)
        self.assertIn(R.ROLE_SALES_HEAD, codes)

    def test_sheet_pdf_endpoint(self):
        contract = services.create_contract(
            organization=self.org, cfo=self.cfo, title="Договор", initiator_b24_id=1,
        )
        # до отправки листа ещё нет
        self.assertEqual(api(1).get(f"/api/contracts/{contract.id}/sheet_pdf/").status_code, 400)

        services.submit(contract, [
            {"type": "internal", "b24_user_id": 502, "role": R.ROLE_SALES_HEAD, "order": 0},
        ], actor_b24_id=1)
        resp = api(1).get(f"/api/contracts/{contract.id}/sheet_pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(resp.streaming_content).startswith(b"%PDF"))

    def test_list_only_own(self):
        api(1).post("/api/contracts/", {
            "title": "Мой", "organization": self.org.id, "cfo": self.cfo.id,
        }, format="json")
        # другой пользователь своих договоров не видит
        self.assertEqual(len(api(2).get("/api/contracts/").json()), 0)
        self.assertEqual(len(api(1).get("/api/contracts/").json()), 1)

    def _submitted_contract(self, approver=502):
        contract = services.create_contract(
            organization=self.org, cfo=self.cfo, title="Договор", initiator_b24_id=1,
        )
        services.submit(contract, [
            {"type": "internal", "b24_user_id": approver, "role": R.ROLE_SALES_HEAD, "order": 0},
        ], actor_b24_id=1)
        return contract

    def test_list_scope_participant(self):
        """Согласующий видит договор во вкладках (scope=participant/all)."""
        contract = self._submitted_contract(approver=502)

        # по умолчанию (свои) — у согласующего пусто
        self.assertEqual(len(api(502).get("/api/contracts/").json()), 0)

        ids = [c["id"] for c in api(502).get("/api/contracts/?scope=participant").json()]
        self.assertEqual(ids, [contract.id])
        ids_all = [c["id"] for c in api(502).get("/api/contracts/?scope=all").json()]
        self.assertEqual(ids_all, [contract.id])

        # посторонний не видит ни в одном режиме
        self.assertEqual(len(api(777).get("/api/contracts/?scope=all").json()), 0)

        # инициатор видит свой договор и в mine, и в all (без дублей)
        self.assertEqual(len(api(1).get("/api/contracts/?scope=all").json()), 1)

    def test_submit_comment_saved_on_round(self):
        """Инициатор поясняет согласующим, что изменилось: комментарий ложится
        на круг, который он открыл, и виден в карточке."""
        r = api(1).post("/api/contracts/", {
            "title": "Договор", "organization": self.org.id, "cfo": self.cfo.id,
        }, format="json")
        cid = r.json()["id"]
        participants = [{"type": "internal", "b24_user_id": 502,
                         "role": R.ROLE_SALES_HEAD, "order": 0}]

        api(1).post(f"/api/contracts/{cid}/submit/",
                    {"participants": participants, "comment": "  Первый круг  "},
                    format="json")
        rounds = api(1).get(f"/api/contracts/{cid}/").json()["approval"]["rounds"]
        self.assertEqual(rounds[0]["opening_comment"], "Первый круг")

        # отклоняем и отправляем повторно — новый круг со своим комментарием
        pid = rounds[0]["participants"][0]["id"]
        api(502).post(f"/api/contracts/{cid}/decide/",
                      {"participant_id": pid, "decision": "reject", "comment": "нет"},
                      format="json")
        api(1).post(f"/api/contracts/{cid}/submit/",
                    {"participants": participants, "comment": "Снизили сумму"},
                    format="json")
        rounds = api(1).get(f"/api/contracts/{cid}/").json()["approval"]["rounds"]
        self.assertEqual([rd["opening_comment"] for rd in rounds],
                         ["Первый круг", "Снизили сумму"])

    def test_submit_without_comment_leaves_round_clean(self):
        """Комментарий необязателен — отправка в один клик работает как раньше."""
        contract = self._submitted_contract()
        rounds = api(1).get(f"/api/contracts/{contract.id}/").json()["approval"]["rounds"]
        self.assertEqual(rounds[0]["opening_comment"], "")

    def test_lawyers_see_each_others_contracts(self):
        """Юрист видит договоры, юр-этап которых закрыл другой юрист.

        Раньше решение по групповому юр-этапу проставляло b24_user_id решавшего,
        и договор исчезал из вкладок остальных сотрудников юротдела — из-за
        этого не отлавливались дубли."""
        lawyer_role = Role.objects.get(code="lawyer")
        for uid, fio in ((30, "Юрист Первый"), (31, "Юрист Второй")):
            p = UserProfile.objects.create(fio=fio, bitrix_id=uid, is_active=True)
            p.roles.add(lawyer_role)

        contract = services.create_contract(
            organization=self.org, cfo=self.cfo, title="Нетиповой", initiator_b24_id=1,
            is_nonstandard=True,
        )
        services.submit(contract, [
            {"type": "internal", "b24_user_id": None, "role": R.ROLE_LEGAL_DEPT, "order": 0},
        ], actor_b24_id=1)
        # юр-этап закрывает юрист 30
        participant = services.current_pending_participant(services.get_approval(contract))
        services.decide(contract, participant.id, "approve", actor_b24_id=30)

        def ids(uid, scope):
            return [c["id"] for c in api(uid).get(f"/api/contracts/?scope={scope}").json()]

        # оба юриста видят договор и как «свой» юр-этап, и во вкладке «Все»
        for uid in (30, 31):
            self.assertEqual(ids(uid, "participant"), [contract.id])
            self.assertEqual(ids(uid, "all"), [contract.id])

    def test_lawyer_sees_contracts_without_legal_stage(self):
        """Типовой договор юр-этапа не имеет, но юрист видит его во вкладке «Все»
        (иначе дубли по типовым договорам не найти). Чужой черновик — не видит."""
        p = UserProfile.objects.create(fio="Юрист", bitrix_id=30, is_active=True)
        p.roles.add(Role.objects.get(code="lawyer"))

        draft = services.create_contract(
            organization=self.org, cfo=self.cfo, title="Черновик", initiator_b24_id=1,
        )
        sent = self._submitted_contract(approver=502)

        ids = [c["id"] for c in api(30).get("/api/contracts/?scope=all").json()]
        self.assertIn(sent.id, ids)
        self.assertNotIn(draft.id, ids)

    def test_detail_documents_include_versions(self):
        """Карточка отдаёт историю версий — на ней строится блок документов."""
        contract = self._submitted_contract()
        r = api(1).post("/api/documents/", {
            "title": "Договор.docx", "linked_type": "contracts.contract",
            "linked_id": str(contract.id),
            "file": SimpleUploadedFile("d.docx", b"v1", content_type="application/octet-stream"),
        })
        self.assertEqual(r.status_code, 201, r.content)
        doc_id = r.json()["id"]
        api(1).post(f"/api/documents/{doc_id}/versions/", {
            "file": SimpleUploadedFile("d.docx", b"v2", content_type="application/octet-stream"),
            "change_comment": "правки юриста",
        })

        doc = api(1).get(f"/api/contracts/{contract.id}/").json()["documents"][0]
        self.assertEqual(doc["current_version_number"], 2)
        self.assertEqual([v["version_number"] for v in doc["versions"]], [1, 2])
        self.assertEqual(doc["versions"][1]["change_comment"], "правки юриста")
        self.assertIn(f"/api/documents/{doc_id}/versions/", doc["download_url"])


class SearchTests(TestCase):
    """Поиск по договорам — как в доверенностях/МЧД, включая поиск по имени
    прикреплённого файла (подписанный скан ищут именно по нему)."""

    INITIATOR = 700

    def setUp(self):
        self.org = Organization.objects.create(short_name="АО Отель Введенский")

    def _contract(self, title, number="", **kw):
        c = Contract.objects.create(
            organization=self.org, initiator_b24_id=self.INITIATOR,
            title=title, **kw,
        )
        if number:
            c.number = number
            c.save(update_fields=["number"])
        return c

    def _found(self, q, uid=INITIATOR):
        resp = api(uid).get(f"/api/contracts/?q={q}")
        self.assertEqual(resp.status_code, 200, resp.content)
        return {x["id"] for x in resp.json()}

    def test_search_by_number_title_and_org(self):
        a = self._contract("Договор аренды помещения", number="ДГ-000001")
        self._contract("Договор поставки белья", number="ДГ-000002")
        self.assertEqual(self._found("аренды"), {a.id})
        self.assertEqual(self._found("ДГ-000001"), {a.id})
        self.assertEqual(self._found("Ленин"), set())

    def test_search_by_attached_file_name(self):
        from documents import services as docsvc

        c = self._contract("Договор на клининг", number="ДГ-000010")
        other = self._contract("Другой договор", number="ДГ-000011")
        doc = docsvc.create_document(title="Подписанный скан", linked_object=c)
        docsvc.add_version(doc, SimpleUploadedFile("dogovor-99-2026.pdf", b"scan"))

        self.assertEqual(self._found("dogovor-99-2026"), {c.id})
        self.assertEqual(self._found("Подписанный"), {c.id})
        self.assertNotIn(other.id, self._found("dogovor-99"))
        # несколько версий файла не задваивают договор в выдаче
        docsvc.add_version(doc, SimpleUploadedFile("dogovor-99-2026.pdf", b"scan v2"))
        self.assertEqual(len(self._found("dogovor-99-2026")), 1)

    def test_search_skips_deleted_files(self):
        from django.utils import timezone
        from documents import services as docsvc

        c = self._contract("Договор с удалённым файлом")
        doc = docsvc.create_document(title="Скан", linked_object=c)
        docsvc.add_version(doc, SimpleUploadedFile("secret-file.pdf", b"x"))
        doc.deleted_at = timezone.now()
        doc.save(update_fields=["deleted_at"])
        self.assertEqual(self._found("secret-file"), set())

    def test_search_terms_are_and(self):
        a = self._contract("Договор аренды помещения")
        self._contract("Договор аренды автомобиля")
        self.assertEqual(self._found("аренды помещения"), {a.id})

    def test_search_ignores_status_tab(self):
        c = self._contract("Согласованный клининг", status=constants.STATUS_APPROVED)
        resp = api(self.INITIATOR).get("/api/contracts/?status=draft&q=клининг")
        self.assertEqual({x["id"] for x in resp.json()}, {c.id})

    def test_search_stays_within_my_contracts(self):
        Contract.objects.create(
            organization=self.org, initiator_b24_id=999, title="Чужой клининг",
        )
        self.assertEqual(self._found("клининг"), set())
