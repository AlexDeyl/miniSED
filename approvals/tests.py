"""
Тесты текущего рабочего сценария согласования скидок/документов.

Назначение: зафиксировать существующее поведение ДО рефактора Этапа 4
(универсальное ядро согласований), чтобы отследить регрессии.

Личность пользователя определяется по заголовку X-B24-User (HTTP_X_B24_USER).
"""

from django.test import TestCase, Client
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Role, UserProfile

from .models import (
    Agreement,
    Participant,
    DecisionLog,
    B24UserEmail,
)

AUTHOR = 100
APPROVER_A = 200
APPROVER_B = 300
OUTSIDER = 999


def api(uid=None):
    """APIClient с проставленным (или нет) заголовком X-B24-User."""
    client = APIClient()
    if uid is not None:
        client.credentials(HTTP_X_B24_USER=str(uid))
    return client


class Factory:
    """Хелперы создания согласований напрямую через ORM."""

    @staticmethod
    def agreement(flow=Agreement.FLOW_PARALLEL, author=AUTHOR, **kwargs):
        return Agreement.objects.create(
            title=kwargs.pop("title", "Скидка 10%"),
            author_b24_id=author,
            flow_type=flow,
            status=Agreement.STATUS_IN_PROGRESS,
            **kwargs,
        )

    @staticmethod
    def internal(agreement, uid, order=0):
        return Participant.objects.create(
            agreement=agreement,
            type=Participant.TYPE_INTERNAL,
            b24_user_id=uid,
            order_index=order,
        )

    @staticmethod
    def external(agreement, email, order=100):
        return Participant.objects.create(
            agreement=agreement,
            type=Participant.TYPE_EXTERNAL,
            email=email,
            order_index=order,
        )


class AuthTests(TestCase):
    def test_list_requires_b24_header(self):
        Factory.agreement()
        resp = api().get("/api/agreements/")
        # initial() кидает AuthenticationFailed -> 401/403
        self.assertIn(resp.status_code, (401, 403))

    def test_list_scoped_to_related_user(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, APPROVER_A)
        # автор видит своё согласование
        self.assertEqual(len(api(AUTHOR).get("/api/agreements/").json()), 1)
        # участник видит согласование
        self.assertEqual(len(api(APPROVER_A).get("/api/agreements/").json()), 1)
        # посторонний не видит ничего
        self.assertEqual(len(api(OUTSIDER).get("/api/agreements/").json()), 0)


class ParallelFlowTests(TestCase):
    def _decide(self, client, agreement, participant, decision, comment=""):
        return client.post(
            f"/api/agreements/{agreement.id}/decide/",
            {"participant_id": participant.id, "decision": decision, "comment": comment},
            format="json",
        )

    def test_all_approve_completes(self):
        a = Factory.agreement(flow=Agreement.FLOW_PARALLEL)
        p1 = Factory.internal(a, APPROVER_A)
        p2 = Factory.internal(a, APPROVER_B)

        r1 = self._decide(api(APPROVER_A), a, p1, "approve")
        self.assertEqual(r1.status_code, 200)
        a.refresh_from_db()
        # ещё один ждёт — статус в работе
        self.assertEqual(a.status, Agreement.STATUS_IN_PROGRESS)

        self._decide(api(APPROVER_B), a, p2, "approve")
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_COMPLETED)
        self.assertEqual(DecisionLog.objects.filter(agreement=a).count(), 2)

    def test_reject_sets_rejected(self):
        a = Factory.agreement()
        p1 = Factory.internal(a, APPROVER_A)

        r = self._decide(api(APPROVER_A), a, p1, "reject", comment="не согласен")
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_REJECTED)

    def test_reject_requires_comment(self):
        a = Factory.agreement()
        p1 = Factory.internal(a, APPROVER_A)

        r = self._decide(api(APPROVER_A), a, p1, "reject", comment="")
        self.assertEqual(r.status_code, 400)
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_IN_PROGRESS)

    def test_cannot_decide_for_other_participant(self):
        a = Factory.agreement()
        p1 = Factory.internal(a, APPROVER_A)
        Factory.internal(a, APPROVER_B)  # чтобы APPROVER_B видел согласование
        # APPROVER_B пытается проголосовать за участника p1 (APPROVER_A)
        r = self._decide(api(APPROVER_B), a, p1, "approve")
        self.assertEqual(r.status_code, 403)

    def test_cannot_decide_twice(self):
        a = Factory.agreement()
        p1 = Factory.internal(a, APPROVER_A)
        p2 = Factory.internal(a, APPROVER_B)
        self._decide(api(APPROVER_A), a, p1, "approve")
        r = self._decide(api(APPROVER_A), a, p1, "approve")
        self.assertEqual(r.status_code, 400)


class SequentialFlowTests(TestCase):
    def _decide(self, uid, agreement, participant, decision, comment=""):
        return api(uid).post(
            f"/api/agreements/{agreement.id}/decide/",
            {"participant_id": participant.id, "decision": decision, "comment": comment},
            format="json",
        )

    def test_out_of_turn_blocked(self):
        a = Factory.agreement(flow=Agreement.FLOW_SEQUENTIAL)
        p1 = Factory.internal(a, APPROVER_A, order=0)
        p2 = Factory.internal(a, APPROVER_B, order=1)

        # второй по очереди не может голосовать раньше первого
        r = self._decide(APPROVER_B, a, p2, "approve")
        self.assertEqual(r.status_code, 400)

    def test_in_order_completes(self):
        a = Factory.agreement(flow=Agreement.FLOW_SEQUENTIAL)
        p1 = Factory.internal(a, APPROVER_A, order=0)
        p2 = Factory.internal(a, APPROVER_B, order=1)

        self.assertEqual(self._decide(APPROVER_A, a, p1, "approve").status_code, 200)
        self.assertEqual(self._decide(APPROVER_B, a, p2, "approve").status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_COMPLETED)


class PermissionTests(TestCase):
    def test_cancel_only_by_author(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, APPROVER_A)

        # участник (не автор) не может отменить
        r = api(APPROVER_A).post(f"/api/agreements/{a.id}/cancel/")
        self.assertEqual(r.status_code, 403)

        # автор может
        r = api(AUTHOR).post(f"/api/agreements/{a.id}/cancel/")
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_CANCELED)

    def test_delete_only_by_author(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, APPROVER_A)

        r = api(APPROVER_A).delete(f"/api/agreements/{a.id}/")
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Agreement.objects.filter(id=a.id).exists())

        r = api(AUTHOR).delete(f"/api/agreements/{a.id}/")
        self.assertIn(r.status_code, (200, 204))
        self.assertFalse(Agreement.objects.filter(id=a.id).exists())


class LegalTeamVisibilityTests(TestCase):
    """Юротдел как единый получатель: согласование с участием юристов видят все
    юристы, а согласования без них — по-прежнему нет."""

    LAWYER_A = 929   # почта отдела привязана
    LAWYER_B = 1071  # привязки нет — раньше ничего не видел
    SHARED = "legal@nordhotels.ru"  # общий ящик юротдела

    def setUp(self):
        lawyer_role = Role.objects.get(code="lawyer")
        for uid, fio, email in (
            (self.LAWYER_A, "Юрист А", "lawyer.a@nordhotels.ru"),
            (self.LAWYER_B, "Юрист Б", "lawyer.b@nordhotels.ru"),
        ):
            p = UserProfile.objects.create(fio=fio, bitrix_id=uid, email=email, is_active=True)
            p.roles.add(lawyer_role)
        # общий ящик исторически привязан только к одному юристу
        B24UserEmail.objects.create(b24_user_id=self.LAWYER_A, email=self.SHARED)

    def _ids(self, uid, query=""):
        return {a["id"] for a in api(uid).get(f"/api/agreements/{query}").json()}

    def test_shared_mailbox_visible_to_whole_legal_team(self):
        a = Factory.agreement(author=AUTHOR, title="на общий ящик")
        Factory.external(a, self.SHARED)

        self.assertIn(a.id, self._ids(self.LAWYER_A))
        self.assertIn(a.id, self._ids(self.LAWYER_B))
        self.assertNotIn(a.id, self._ids(OUTSIDER))

    def test_personal_lawyer_address_visible_to_team(self):
        """Согласование на личную почту одного юриста — тоже дело отдела."""
        a = Factory.agreement(author=AUTHOR)
        Factory.external(a, "lawyer.a@nordhotels.ru")
        self.assertIn(a.id, self._ids(self.LAWYER_B))

    def test_internal_lawyer_participant_visible_to_team(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, self.LAWYER_A)
        self.assertIn(a.id, self._ids(self.LAWYER_B))

    def test_agreement_without_legal_stays_hidden(self):
        """Согласований без юристов в маршруте отдел не видит — их и не нужно."""
        a = Factory.agreement(author=AUTHOR)
        Factory.external(a, "sales@nordhotels.ru")
        Factory.internal(a, APPROVER_A)
        self.assertNotIn(a.id, self._ids(self.LAWYER_B))

    def test_email_match_is_case_insensitive(self):
        """В перенесённых данных попадаются «Legal@…» — регистр не должен
        прятать согласование от адресата."""
        a = Factory.agreement(author=AUTHOR)
        Factory.external(a, self.SHARED.capitalize())
        self.assertIn(a.id, self._ids(self.LAWYER_A))
        self.assertIn(a.id, self._ids(self.LAWYER_B))

    def test_completed_agreement_reaches_archive_tab(self):
        """Архивные вкладки (?status=) показывают и чужие согласования, где я
        участник, — раньше там были только созданные мной."""
        a = Factory.agreement(author=AUTHOR, title="завершённое")
        a.status = Agreement.STATUS_COMPLETED
        a.save(update_fields=["status"])
        Factory.external(a, self.SHARED)

        self.assertIn(a.id, self._ids(self.LAWYER_B, "?status=completed"))
        self.assertNotIn(a.id, self._ids(self.LAWYER_B, "?status=rejected"))
        # у автора архив тоже работает
        self.assertIn(a.id, self._ids(AUTHOR, "?status=completed"))

    def test_todo_not_widened_to_whole_team(self):
        """Видимость — общая, а «требует действия» остаётся адресным: решать за
        коллегу без привязки к ящику никто не обязан."""
        a = Factory.agreement(author=AUTHOR)
        Factory.external(a, self.SHARED)

        todo_a = {x["id"] for x in api(self.LAWYER_A).get("/api/agreements/todo/").json()}
        todo_b = {x["id"] for x in api(self.LAWYER_B).get("/api/agreements/todo/").json()}
        self.assertIn(a.id, todo_a)
        self.assertNotIn(a.id, todo_b)


class RegistryTests(TestCase):
    def test_my_lists_authored(self):
        mine = Factory.agreement(author=AUTHOR, title="моё")
        other = Factory.agreement(author=APPROVER_A, title="чужое")
        Factory.internal(other, AUTHOR)  # автор тут лишь участник

        data = api(AUTHOR).get("/api/agreements/my/").json()
        titles = {x["title"] for x in data}
        self.assertEqual(titles, {"моё"})

    def test_todo_lists_waiting_for_me(self):
        a = Factory.agreement(author=APPROVER_B)
        Factory.internal(a, AUTHOR)  # AUTHOR должен решить

        data = api(AUTHOR).get("/api/agreements/todo/").json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], a.id)

    def test_external_participant_matched_by_registered_email(self):
        """Внешний участник виден пользователю, если его email привязан
        к b24_user_id через B24UserEmail."""
        a = Factory.agreement(author=APPROVER_B)
        Factory.external(a, "manager@nordhotels.ru")
        B24UserEmail.objects.create(
            b24_user_id=AUTHOR, email="manager@nordhotels.ru"
        )

        data = api(AUTHOR).get("/api/agreements/todo/").json()
        self.assertEqual(len(data), 1)

    def test_decide_external_participant_by_own_email(self):
        """Отправил себе на email (внешний участник) → решаю в приложении."""
        a = Factory.agreement(author=APPROVER_B)
        p = Factory.external(a, "manager@nordhotels.ru")
        B24UserEmail.objects.create(b24_user_id=AUTHOR, email="manager@nordhotels.ru")
        ok = api(AUTHOR).post(f"/api/agreements/{a.id}/decide/",
                              {"participant_id": p.id, "decision": "approve"}, format="json")
        self.assertEqual(ok.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, Participant.STATUS_APPROVED)

    def test_decide_external_forbidden_for_non_owner(self):
        """Кто видит согласование, но не владелец этой почты — решить не может."""
        a = Factory.agreement(author=APPROVER_B)
        p = Factory.external(a, "manager@nordhotels.ru")
        # автор видит согласование, но почта не его → 403
        bad = api(APPROVER_B).post(f"/api/agreements/{a.id}/decide/",
                                   {"participant_id": p.id, "decision": "approve"}, format="json")
        self.assertEqual(bad.status_code, 403)


class ExternalApproveTests(TestCase):
    def test_external_token_approve(self):
        a = Factory.agreement(author=AUTHOR)
        p = Factory.external(a, "vendor@x.ru")
        self.assertTrue(p.external_token)

        url = reverse("external_approve", args=[p.external_token])
        # GET открывает страницу согласования
        self.assertEqual(Client().get(url).status_code, 200)

        # POST c approve фиксирует решение
        resp = Client().post(url, {"decision": "approve", "comment": ""})
        self.assertEqual(resp.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, Participant.STATUS_APPROVED)
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_COMPLETED)

    def test_external_reject_requires_comment(self):
        a = Factory.agreement(author=AUTHOR)
        p = Factory.external(a, "vendor@x.ru")
        url = reverse("external_approve", args=[p.external_token])

        Client().post(url, {"decision": "reject", "comment": ""})
        p.refresh_from_db()
        # без комментария решение не принято
        self.assertEqual(p.status, Participant.STATUS_WAITING)

    def test_unknown_token_404(self):
        self.assertEqual(
            Client().get(reverse("external_approve", args=["nope"])).status_code, 404
        )


class RestartTests(TestCase):
    def test_restart_returns_rejected_to_waiting(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        # участник отклонил
        api(APPROVER_A).post(
            f"/api/agreements/{a.id}/decide/",
            {"participant_id": p1.id, "decision": "reject", "comment": "правьте"},
            format="json",
        )
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_REJECTED)

        # перезапуск
        r = api(AUTHOR).post(f"/api/agreements/{a.id}/restart/")
        self.assertEqual(r.status_code, 200)
        p1.refresh_from_db()
        self.assertEqual(p1.status, Participant.STATUS_WAITING)
        self.assertEqual(p1.prev_status, Participant.STATUS_REJECTED)
        self.assertEqual(p1.prev_comment, "правьте")


class RoundsTests(TestCase):
    """ТЗ п.7.4-7.6: несколько кругов, повторное согласование, смена согласующих."""

    def _decide(self, uid, a, p, decision, comment=""):
        return api(uid).post(
            f"/api/agreements/{a.id}/decide/",
            {"participant_id": p.id, "decision": decision, "comment": comment},
            format="json",
        )

    def test_resubmit_creates_new_round_keeps_history(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        self._decide(APPROVER_A, a, p1, "reject", "правьте")
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_REJECTED)

        r = api(AUTHOR).post(f"/api/agreements/{a.id}/resubmit/")
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.current_round, 2)
        self.assertEqual(a.status, Agreement.STATUS_IN_PROGRESS)
        # круг 2 — свежий участник waiting; круг 1 сохранён (rejected)
        self.assertEqual(a.participants.filter(round_number=2, status="waiting").count(), 1)
        self.assertEqual(a.participants.filter(round_number=1, status="rejected").count(), 1)

    def test_resubmit_with_edited_route(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        self._decide(APPROVER_A, a, p1, "reject", "нет")
        r = api(AUTHOR).post(
            f"/api/agreements/{a.id}/resubmit/",
            {"participants": [
                {"type": "internal", "b24_user_id": APPROVER_B, "order_index": 0},
                {"type": "internal", "b24_user_id": 555, "order_index": 1},
            ]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.participants.filter(round_number=2).count(), 2)

    def test_resubmit_only_author(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        self._decide(APPROVER_A, a, p1, "reject", "нет")
        r = api(APPROVER_A).post(f"/api/agreements/{a.id}/resubmit/")
        self.assertEqual(r.status_code, 403)

    def test_resubmit_blocked_when_completed(self):
        # Завершённое согласование закрыто — повторно запустить нельзя.
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        self._decide(APPROVER_A, a, p1, "approve")
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_COMPLETED)
        r = api(AUTHOR).post(f"/api/agreements/{a.id}/resubmit/")
        self.assertEqual(r.status_code, 400)

    def test_resubmit_allowed_when_canceled(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, APPROVER_A)
        api(AUTHOR).post(f"/api/agreements/{a.id}/cancel/")
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_CANCELED)
        r = api(AUTHOR).post(f"/api/agreements/{a.id}/resubmit/")
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_IN_PROGRESS)

    def test_set_route_blocked_when_completed(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        self._decide(APPROVER_A, a, p1, "approve")
        r = api(AUTHOR).post(
            f"/api/agreements/{a.id}/set_route/",
            {"participants": [{"type": "internal", "b24_user_id": 555, "order_index": 0}]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_set_route_before_decisions(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, APPROVER_A, order=0)
        r = api(AUTHOR).post(
            f"/api/agreements/{a.id}/set_route/",
            {"participants": [
                {"type": "internal", "b24_user_id": APPROVER_B, "order_index": 0},
                {"type": "internal", "b24_user_id": 555, "order_index": 1},
            ]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        self.assertEqual(a.participants.filter(round_number=1).count(), 2)
        self.assertFalse(a.participants.filter(b24_user_id=APPROVER_A).exists())

    def test_set_route_blocked_after_decision(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        Factory.internal(a, APPROVER_B)
        self._decide(APPROVER_A, a, p1, "approve")
        r = api(AUTHOR).post(
            f"/api/agreements/{a.id}/set_route/",
            {"participants": [{"type": "internal", "b24_user_id": 555, "order_index": 0}]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_second_round_decide_completes(self):
        a = Factory.agreement(author=AUTHOR)
        p1 = Factory.internal(a, APPROVER_A)
        self._decide(APPROVER_A, a, p1, "reject", "правьте")
        api(AUTHOR).post(f"/api/agreements/{a.id}/resubmit/")
        a.refresh_from_db()
        p2 = a.participants.get(round_number=2)
        self._decide(APPROVER_A, a, p2, "approve")
        a.refresh_from_db()
        self.assertEqual(a.status, Agreement.STATUS_COMPLETED)


class SheetAndVersionedDocsTests(TestCase):
    def test_sheet_pdf(self):
        a = Factory.agreement(author=AUTHOR)
        Factory.internal(a, APPROVER_A)
        resp = api(AUTHOR).get(f"/api/agreements/{a.id}/sheet_pdf/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(b"".join(resp.streaming_content).startswith(b"%PDF"))

    def test_sheet_resolves_participant_names(self):
        from django.contrib.auth.models import User
        from core.models import UserProfile
        from approvals.sheet import _name_maps, _pname

        u = User.objects.create_user("p@x.ru", "p@x.ru", "pass12345")
        UserProfile.objects.create(fio="Пётр Иванов", bitrix_id=APPROVER_A, email="p@x.ru", auth_user=u)
        UserProfile.objects.create(fio="Внешний Гость", email="guest@x.ru")

        a = Factory.agreement(author=AUTHOR)
        p_int = Factory.internal(a, APPROVER_A)
        p_ext = Factory.external(a, "guest@x.ru")
        by_bid, by_email = _name_maps(a)
        self.assertEqual(_pname(p_int, by_bid, by_email), "Пётр Иванов")
        self.assertEqual(_pname(p_ext, by_bid, by_email), "Внешний Гость")

    def test_versioned_documents_in_detail(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from documents import services as docsvc

        a = Factory.agreement(author=AUTHOR)
        doc = docsvc.create_document(title="Договор", linked_object=a)
        docsvc.add_version(doc, SimpleUploadedFile("d.pdf", b"v1"))
        docsvc.add_version(doc, SimpleUploadedFile("d.pdf", b"v2"), change_comment="правки")

        data = api(AUTHOR).get(f"/api/agreements/{a.id}/").json()
        self.assertEqual(len(data["documents_v"]), 1)
        dv = data["documents_v"][0]
        self.assertEqual(dv["current_version_number"], 2)
        self.assertEqual(len(dv["versions"]), 2)

    def test_sheet_groups_rounds_and_versions(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from documents import services as docsvc
        from approvals.sheet import render_pdf

        a = Factory.agreement(author=AUTHOR)
        # круг 1 (отклонён) и круг 2 (текущий)
        Participant.objects.create(
            agreement=a, type=Participant.TYPE_INTERNAL, b24_user_id=APPROVER_A,
            round_number=1, order_index=0, status=Participant.STATUS_REJECTED, comment="правьте",
        )
        a.current_round = 2
        a.save(update_fields=["current_round"])
        Participant.objects.create(
            agreement=a, type=Participant.TYPE_INTERNAL, b24_user_id=APPROVER_B,
            round_number=2, order_index=0, status=Participant.STATUS_APPROVED,
        )
        # версионируемый документ с историей
        doc = docsvc.create_document(title="Договор", linked_object=a)
        docsvc.add_version(doc, SimpleUploadedFile("v1.pdf", b"one"), change_comment="первая версия")
        docsvc.add_version(doc, SimpleUploadedFile("v2.pdf", b"two"), change_comment="учтены правки")

        pdf = render_pdf(a)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 2500)


class SimpleCreateEndpointTests(TestCase):
    def test_create_with_participants(self):
        resp = api(AUTHOR).post(
            "/api/agreements/create_simple/",
            {
                "title": "Согласование договора",
                "internal_users": f"{APPROVER_A},{APPROVER_B}",
                "external_emails": "vendor@x.ru",
            },
            format="multipart",
        )
        self.assertEqual(resp.status_code, 201)
        a = Agreement.objects.get(title="Согласование договора")
        self.assertEqual(a.author_b24_id, AUTHOR)
        self.assertEqual(
            a.participants.filter(type=Participant.TYPE_INTERNAL).count(), 2
        )
        self.assertEqual(
            a.participants.filter(type=Participant.TYPE_EXTERNAL).count(), 1
        )

    def test_create_requires_auth(self):
        resp = api().post(
            "/api/agreements/create_simple/",
            {"title": "x"},
            format="multipart",
        )
        self.assertEqual(resp.status_code, 401)

    def test_create_requires_title(self):
        resp = api(AUTHOR).post(
            "/api/agreements/create_simple/", {"title": ""}, format="multipart"
        )
        self.assertEqual(resp.status_code, 400)
