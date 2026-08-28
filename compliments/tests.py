"""
Тесты заявок на комплименты: маршрут по категориям, согласование, исполнение.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from approvalflow.models import Approval
from core.models import Facility, Organization
from requests_reg import constants as R
from requests_reg.models import RoleAssignment

from . import constants, routing, services
from .models import Compliment

# Кто есть кто (dev-данные): Дарья — рук. продаж, Ксения — коммерческий
# директор, ТАР — ГД, Шахов — ресторанная служба, Соколинская — помощник ГД,
# Вика — кондитерский цех.
DARIA, KSENIA, TAR, SHAHOV, SOKOL, VIKA = 17, 1595, 857, 900, 901, 902


def api(uid=None):
    c = APIClient()
    if uid is not None:
        c.credentials(HTTP_X_B24_USER=str(uid))
    return c


class BaseData(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="ООО Управление Отелями")
        self.hotel = Facility.objects.create(name="Отель Svet", organization=self.org)
        RoleAssignment.objects.create(role_code=R.ROLE_SALES_HEAD, user_b24_id=DARIA, user_name="Ткачева Дарья")
        RoleAssignment.objects.create(role_code=R.ROLE_COMMERCIAL_DIRECTOR, user_b24_id=KSENIA, user_name="Корнейчук Ксения")
        # ГД согласует по ВСЕМ юрлицам → назначение глобальное (без organization).
        RoleAssignment.objects.create(role_code=R.ROLE_FINAL_SIGNER, user_b24_id=TAR, user_name="Ткачев А.Р.")
        RoleAssignment.objects.create(role_code=R.ROLE_RESTAURANT_DIRECTOR, user_b24_id=SHAHOV, user_name="Шахов")
        RoleAssignment.objects.create(role_code=R.ROLE_CEO_ASSISTANT, user_b24_id=SOKOL, user_name="Соколинская Анастасия")
        RoleAssignment.objects.create(role_code=R.ROLE_CONFECTIONER, user_b24_id=VIKA, user_name="Вика (кондитер)")

    def _compliment(self, category=constants.CATEGORY_STAY, **kw):
        kw.setdefault("title", "Комплимент партнёру")
        kw.setdefault("company", 'ООО "Туроператор Невские Сезоны"')
        kw.setdefault("facility", self.hotel)
        kw.setdefault("organization", self.org)
        kw.setdefault("initiator_b24_id", 1)
        return services.create_compliment(category=category, **kw)


class RoutingTests(BaseData):
    def _codes(self, route):
        return [s["role_code"] for s in route]

    def test_confectionery_route(self):
        route = routing.build_route(self._compliment(constants.CATEGORY_CONFECTIONERY))
        self.assertEqual(
            self._codes(route),
            [R.ROLE_SALES_HEAD, R.ROLE_RESTAURANT_DIRECTOR, R.ROLE_CONFECTIONER],
        )
        # последний слот — исполнение, на нём решения не принимают
        self.assertEqual(route[-1]["role_class"], constants.CLASS_EXECUTOR)
        self.assertEqual(route[0]["role_class"], constants.CLASS_APPROVER)
        self.assertEqual(route[-1]["b24_user_id"], VIKA)

    def test_restaurant_route(self):
        route = routing.build_route(self._compliment(constants.CATEGORY_RESTAURANT))
        self.assertEqual(
            self._codes(route),
            [R.ROLE_SALES_HEAD, R.ROLE_COMMERCIAL_DIRECTOR, R.ROLE_FINAL_SIGNER,
             R.ROLE_RESTAURANT_DIRECTOR],
        )
        self.assertEqual(route[-1]["b24_user_id"], SHAHOV)

    def test_stay_route(self):
        route = routing.build_route(self._compliment(constants.CATEGORY_STAY))
        self.assertEqual(
            self._codes(route),
            [R.ROLE_SALES_HEAD, R.ROLE_COMMERCIAL_DIRECTOR, R.ROLE_FINAL_SIGNER,
             R.ROLE_CEO_ASSISTANT],
        )
        self.assertEqual(route[-1]["b24_user_id"], SOKOL)

    def test_ceo_flag_adds_to_confectionery(self):
        """Флажок «с ГД» добавляет коммерческого директора и ГД в кондитерку."""
        route = routing.build_route(
            self._compliment(constants.CATEGORY_CONFECTIONERY, needs_ceo=True)
        )
        codes = self._codes(route)
        self.assertIn(R.ROLE_COMMERCIAL_DIRECTOR, codes)
        self.assertIn(R.ROLE_FINAL_SIGNER, codes)
        # исполнитель по-прежнему кондитерский цех и по-прежнему последний
        self.assertEqual(codes[-1], R.ROLE_CONFECTIONER)

    def test_ceo_flag_no_duplicates(self):
        """В категориях с ГД флажок ничего не задваивает."""
        codes = self._codes(routing.build_route(
            self._compliment(constants.CATEGORY_STAY, needs_ceo=True)
        ))
        self.assertEqual(codes.count(R.ROLE_FINAL_SIGNER), 1)
        self.assertEqual(codes.count(R.ROLE_COMMERCIAL_DIRECTOR), 1)

    def test_role_without_assignment_needs_manual(self):
        RoleAssignment.objects.filter(role_code=R.ROLE_CEO_ASSISTANT).delete()
        route = routing.build_route(self._compliment(constants.CATEGORY_STAY))
        slot = next(s for s in route if s["role_code"] == R.ROLE_CEO_ASSISTANT)
        self.assertTrue(slot["needs_manual"])
        self.assertIsNone(slot["b24_user_id"])


class FlowTests(BaseData):
    def _participants(self, compliment):
        """Только согласующие: исполнение — отдельная фаза, не участник круга."""
        return [
            {"type": "internal", "b24_user_id": s["b24_user_id"], "role": s["role_code"],
             "order": i, "is_required": True}
            for i, s in enumerate(
                s for s in routing.build_route(compliment)
                if s["role_class"] == constants.CLASS_APPROVER
            )
        ]

    def _approve_all(self, compliment):
        for _ in range(6):
            pending = services.current_pending_participant(services.get_approval(compliment))
            if pending is None:
                break
            services.decide(compliment, pending.id, "approve", actor_b24_id=pending.b24_user_id)

    def test_full_cycle_stay(self):
        c = self._compliment(constants.CATEGORY_STAY)
        self.assertTrue(c.number.startswith("КМП-"))

        services.submit(c, self._participants(c), actor_b24_id=1)
        c.refresh_from_db()
        self.assertEqual(c.status, constants.STATUS_ON_APPROVAL)
        # исполнитель подставился по роли категории
        self.assertEqual(c.executor_b24_id, SOKOL)

        self._approve_all(c)
        c.refresh_from_db()
        self.assertEqual(c.status, constants.STATUS_APPROVED)
        self.assertEqual(services.get_approval(c).status, Approval.STATUS_COMPLETED)

        services.take_in_work(c, executor_b24_id=SOKOL)
        c.refresh_from_db()
        self.assertEqual(c.status, constants.STATUS_IN_WORK)
        self.assertIsNotNone(c.taken_at)

        services.execute(c, executor_b24_id=SOKOL, comment="сертификаты переданы")
        c.refresh_from_db()
        self.assertEqual(c.status, constants.STATUS_EXECUTED)
        self.assertIsNotNone(c.executed_at)
        self.assertEqual(c.execution_comment, "сертификаты переданы")

    def test_execute_without_file_allowed(self):
        """Подтверждение файлом не обязательно (решение заказчика)."""
        c = self._compliment(constants.CATEGORY_RESTAURANT)
        services.submit(c, self._participants(c), actor_b24_id=1)
        self._approve_all(c)
        services.execute(c, executor_b24_id=SHAHOV)
        c.refresh_from_db()
        self.assertEqual(c.status, constants.STATUS_EXECUTED)

    def test_reject_stops_flow(self):
        c = self._compliment(constants.CATEGORY_CONFECTIONERY)
        services.submit(c, self._participants(c), actor_b24_id=1)
        pending = services.current_pending_participant(services.get_approval(c))
        services.decide(c, pending.id, "reject", "не в этом квартале", actor_b24_id=DARIA)
        c.refresh_from_db()
        self.assertEqual(c.status, constants.STATUS_REJECTED)

    def test_cannot_cancel_after_approval(self):
        """Согласованную заявку не отменяем — её судьба не меняется."""
        c = self._compliment(constants.CATEGORY_RESTAURANT)
        services.submit(c, self._participants(c), actor_b24_id=1)
        self._approve_all(c)
        c.refresh_from_db()
        with self.assertRaises(services.ComplimentError):
            services.cancel(c, by_b24_id=1)

    def test_take_requires_approved(self):
        c = self._compliment(constants.CATEGORY_STAY)
        with self.assertRaises(services.ComplimentError):
            services.take_in_work(c, executor_b24_id=SOKOL)


class ApiTests(BaseData):
    def test_requires_auth(self):
        self.assertIn(api().get("/api/compliments/").status_code, (401, 403))

    def test_create_and_route_preview(self):
        r = api(1).post("/api/compliments/", {
            "title": "Комплимент партнёрам", "category": constants.CATEGORY_RESTAURANT,
            "company": "ООО Ромашка", "facility": self.hotel.id,
            "category_details": "2 сертификата в ресторан",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["id"]
        self.assertTrue(r.json()["number"].startswith("КМП-"))

        route = api(1).get(f"/api/compliments/{cid}/route_preview/").json()["route"]
        self.assertEqual(
            [s["role_code"] for s in route],
            [R.ROLE_SALES_HEAD, R.ROLE_COMMERCIAL_DIRECTOR, R.ROLE_FINAL_SIGNER,
             R.ROLE_RESTAURANT_DIRECTOR],
        )
        # инициатор видит весь путь, включая исполнение
        self.assertEqual(route[-1]["role_class"], constants.CLASS_EXECUTOR)

    def test_sales_head_sees_all(self):
        """Руководитель продаж согласует все заявки → видит все."""
        self._compliment(constants.CATEGORY_STAY, initiator_b24_id=555)
        self.assertEqual(len(api(777).get("/api/compliments/?scope=all").json()), 0)
        self.assertEqual(len(api(DARIA).get("/api/compliments/?scope=all").json()), 1)

    def test_execution_queue_and_actions(self):
        c = self._compliment(constants.CATEGORY_STAY)
        parts = [
            {"type": "internal", "b24_user_id": s["b24_user_id"], "role": s["role_code"], "order": i}
            for i, s in enumerate(
                s for s in routing.build_route(c) if s["role_class"] == constants.CLASS_APPROVER
            )
        ]
        services.submit(c, parts, actor_b24_id=1)
        for _ in range(4):
            pending = services.current_pending_participant(services.get_approval(c))
            if pending is None:
                break
            services.decide(c, pending.id, "approve", actor_b24_id=pending.b24_user_id)

        # помощник ГД видит заявку во вкладке «Новые»
        queue = api(SOKOL).get("/api/compliments/execution_queue/?scope=new").json()
        self.assertEqual([x["id"] for x in queue], [c.id])
        # посторонний — не видит
        self.assertEqual(api(777).get("/api/compliments/execution_queue/?scope=new").json(), [])

        self.assertEqual(api(SOKOL).post(f"/api/compliments/{c.id}/take/").status_code, 200)
        r = api(SOKOL).post(f"/api/compliments/{c.id}/execute/", {"comment": "выдано"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], constants.STATUS_EXECUTED)

    def test_executor_only_own_queue(self):
        """Чужую по категории заявку исполнитель не видит и не исполняет."""
        c = self._compliment(constants.CATEGORY_STAY)
        c.status = constants.STATUS_APPROVED
        c.executor_b24_id = SOKOL
        c.save()
        # Шахов исполняет рестораны, а не проживание → карточка для него не существует
        self.assertEqual(api(SHAHOV).post(f"/api/compliments/{c.id}/take/").status_code, 404)
        self.assertEqual(api(SHAHOV).get(f"/api/compliments/{c.id}/").status_code, 404)

    def test_executor_by_role_can_take_unassigned(self):
        """Исполнитель по роли берёт заявку, даже если персонально не назначен."""
        c = self._compliment(constants.CATEGORY_RESTAURANT)
        c.status = constants.STATUS_APPROVED
        c.save()
        r = api(SHAHOV).post(f"/api/compliments/{c.id}/take/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["executor_b24_id"], SHAHOV)

    def test_form_pdf_with_sheet(self):
        c = self._compliment(constants.CATEGORY_RESTAURANT)
        parts = [
            {"type": "internal", "b24_user_id": s["b24_user_id"], "role": s["role_code"], "order": i}
            for i, s in enumerate(
                s for s in routing.build_route(c) if s["role_class"] == constants.CLASS_APPROVER
            )
        ]
        services.submit(c, parts, actor_b24_id=1)

        r = api(1).get(f"/api/compliments/{c.id}/form_pdf/?with_sheet=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))

        r2 = api(1).get(f"/api/compliments/{c.id}/sheet_pdf/")
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(b"".join(r2.streaming_content).startswith(b"%PDF"))

    def test_meta_lists_categories(self):
        data = api(1).get("/api/compliments/meta/").json()
        self.assertEqual(len(data["categories"]), 3)
        codes = {c["code"] for c in data["categories"]}
        self.assertEqual(codes, {
            constants.CATEGORY_CONFECTIONERY,
            constants.CATEGORY_RESTAURANT,
            constants.CATEGORY_STAY,
        })


class SearchTests(BaseData):
    """Поиск по комплиментам (раздел и очередь исполнения) — как в
    доверенностях/МЧД, включая поиск по имени прикреплённого файла."""

    INITIATOR = 800

    def _compliment(self, title, number="", company="ООО Партнёр", **kw):
        kw.setdefault("category", constants.CATEGORY_STAY)
        kw.setdefault("facility", self.hotel)
        c = Compliment.objects.create(
            initiator_b24_id=self.INITIATOR, title=title, company=company, **kw,
        )
        if number:
            c.number = number
            c.save(update_fields=["number"])
        return c

    def _found(self, q, uid=INITIATOR):
        resp = api(uid).get(f"/api/compliments/?q={q}")
        self.assertEqual(resp.status_code, 200, resp.content)
        return {x["id"] for x in resp.json()}

    def test_search_by_number_company_and_guest(self):
        a = self._compliment("Торт на юбилей", number="КМП-000001",
                             company="ООО Ромашка", guest_name="Петров Пётр")
        self._compliment("Сертификат", number="КМП-000002", company="ООО Лютик")
        self.assertEqual(self._found("Ромашка"), {a.id})
        self.assertEqual(self._found("КМП-000001"), {a.id})
        self.assertEqual(self._found("Петров"), {a.id})
        self.assertEqual(self._found("Ленин"), set())

    def test_search_by_attached_file_name(self):
        from documents import services as docsvc

        c = self._compliment("Сертификат на проживание", number="КМП-000010")
        other = self._compliment("Другая заявка", number="КМП-000011")
        doc = docsvc.create_document(title="Бланк заявки", linked_object=c)
        docsvc.add_version(doc, SimpleUploadedFile("kmp-55-2026.pdf", b"blank"))

        self.assertEqual(self._found("kmp-55-2026"), {c.id})
        self.assertEqual(self._found("Бланк"), {c.id})
        self.assertNotIn(other.id, self._found("kmp-55"))
        docsvc.add_version(doc, SimpleUploadedFile("kmp-55-2026.pdf", b"blank v2"))
        self.assertEqual(len(self._found("kmp-55-2026")), 1)

    def test_search_skips_deleted_files(self):
        from django.utils import timezone
        from documents import services as docsvc

        c = self._compliment("Заявка с удалённым файлом")
        doc = docsvc.create_document(title="Скан", linked_object=c)
        docsvc.add_version(doc, SimpleUploadedFile("secret-file.pdf", b"x"))
        doc.deleted_at = timezone.now()
        doc.save(update_fields=["deleted_at"])
        self.assertEqual(self._found("secret-file"), set())

    def test_search_terms_are_and(self):
        a = self._compliment("Торт на юбилей", company="ООО Ромашка")
        self._compliment("Торт на свадьбу", company="ООО Ромашка")
        self.assertEqual(self._found("Торт юбилей"), {a.id})

    def test_search_ignores_status_tab(self):
        c = self._compliment("Исполненный торт", status=constants.STATUS_EXECUTED)
        resp = api(self.INITIATOR).get("/api/compliments/?status=draft&q=торт")
        self.assertEqual({x["id"] for x in resp.json()}, {c.id})

    def test_search_in_execution_queue_ignores_tab(self):
        """В очереди исполнения ищем по всем вкладкам: статус заранее неизвестен."""
        from documents import services as docsvc

        done = self._compliment("Сертификат гостю", category=constants.CATEGORY_STAY,
                                status=constants.STATUS_EXECUTED)
        doc = docsvc.create_document(title="Подтверждение", linked_object=done)
        docsvc.add_version(doc, SimpleUploadedFile("vruchenie-12.pdf", b"ok"))

        # Соколинская — исполнитель категории «проживание»; вкладка «Новые»
        resp = api(SOKOL).get("/api/compliments/execution_queue/?scope=new&q=vruchenie-12")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual({x["id"] for x in resp.json()}, {done.id})
