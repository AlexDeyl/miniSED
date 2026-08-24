"""
Тесты движка согласований: круги, решения, последовательность, возврат,
повторная отправка, правка маршрута, лист согласования PDF.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from approvals.models import Agreement
from .models import Approval, ApprovalParticipant, ApprovalRound
from . import services
from .sheet import generate_sheet, render_pdf, _who


def api(uid=None):
    client = APIClient()
    if uid is not None:
        client.credentials(HTTP_X_B24_USER=str(uid))
    return client


def internal(uid, order=0, role=""):
    return {"type": "internal", "b24_user_id": uid, "order": order, "role": role}


def make_approval(flow=Approval.FLOW_PARALLEL, linked=None):
    ap = Approval.objects.create(
        approval_type="discount",
        title="Скидка 10%",
        flow_type=flow,
        initiator_b24_id=1,
    )
    if linked is not None:
        ap.linked_object = linked
        ap.save()
    return ap


class SubmitTests(TestCase):
    def test_submit_opens_first_round(self):
        ap = make_approval()
        rnd = services.submit(ap, [internal(10), internal(20)])
        ap.refresh_from_db()
        self.assertEqual(ap.status, Approval.STATUS_IN_PROGRESS)
        self.assertEqual(ap.current_round, 1)
        self.assertEqual(rnd.participants.count(), 2)
        self.assertIsNotNone(ap.submitted_at)

    def test_opening_comment_and_note(self):
        """Пояснение инициатора хранится на круге, который он открыл, и
        подписывается по-разному для первого и повторного круга."""
        ap = make_approval()
        services.submit(ap, [internal(10)], comment="Первичная отправка")
        rnd = services.get_current_round(ap)
        self.assertEqual(rnd.opening_comment, "Первичная отправка")
        self.assertEqual(
            services.opening_note(rnd.participants.first()),
            "Комментарий инициатора: Первичная отправка",
        )

        services.decide(rnd.participants.first(), "reject", "нет")
        services.start_new_round(ap, [internal(10)], comment="  Снизили сумму  ")
        rnd2 = services.get_current_round(ap)
        self.assertEqual(rnd2.round_number, 2)
        self.assertEqual(rnd2.opening_comment, "Снизили сумму")
        self.assertEqual(
            services.opening_note(rnd2.participants.first()),
            "Комментарий инициатора при повторном направлении: Снизили сумму",
        )
        # круг без пояснения — пустая строка, вызывающему достаточно `if note:`
        services.decide(rnd2.participants.first(), "reject", "нет")
        services.start_new_round(ap, [internal(10)])
        rnd3 = services.get_current_round(ap)
        self.assertEqual(services.opening_note(rnd3.participants.first()), "")

    def test_submit_twice_forbidden(self):
        ap = make_approval()
        services.submit(ap, [internal(10)])
        with self.assertRaises(services.ApprovalError):
            services.submit(ap, [internal(20)])


class ParallelDecisionTests(TestCase):
    def test_all_approve_completes(self):
        ap = make_approval()
        rnd = services.submit(ap, [internal(10), internal(20)])
        p1, p2 = list(rnd.participants.order_by("order"))

        services.decide(p1, "approve")
        ap.refresh_from_db()
        self.assertEqual(ap.status, Approval.STATUS_IN_PROGRESS)

        services.decide(p2, "approve")
        ap.refresh_from_db()
        rnd.refresh_from_db()
        self.assertEqual(ap.status, Approval.STATUS_COMPLETED)
        self.assertEqual(rnd.result, ApprovalRound.RESULT_APPROVED)
        self.assertIsNotNone(ap.completed_at)

    def test_reject_sets_rejected_and_requires_comment(self):
        ap = make_approval()
        rnd = services.submit(ap, [internal(10)])
        p1 = rnd.participants.first()

        with self.assertRaises(services.ApprovalError):
            services.decide(p1, "reject", "")

        services.decide(p1, "reject", "не согласен")
        ap.refresh_from_db()
        self.assertEqual(ap.status, Approval.STATUS_REJECTED)

    def test_cannot_decide_twice(self):
        ap = make_approval()
        rnd = services.submit(ap, [internal(10), internal(20)])
        p1 = rnd.participants.first()
        services.decide(p1, "approve")
        with self.assertRaises(services.ApprovalError):
            services.decide(p1, "approve")


class SequentialDecisionTests(TestCase):
    def test_out_of_turn_blocked(self):
        ap = make_approval(flow=Approval.FLOW_SEQUENTIAL)
        rnd = services.submit(ap, [internal(10, order=0), internal(20, order=1)])
        p1, p2 = list(rnd.participants.order_by("order"))
        with self.assertRaises(services.ApprovalError):
            services.decide(p2, "approve")
        # первый может
        services.decide(p1, "approve")
        services.decide(p2, "approve")
        ap.refresh_from_db()
        self.assertEqual(ap.status, Approval.STATUS_COMPLETED)


class RoundsTests(TestCase):
    def test_return_and_new_round_keeps_history(self):
        ap = make_approval()
        r1 = services.submit(ap, [internal(10)])

        services.return_for_revision(ap, by_b24_id=1, comment="доработайте")
        ap.refresh_from_db()
        r1.refresh_from_db()
        self.assertEqual(ap.status, Approval.STATUS_RETURNED)
        self.assertEqual(r1.result, ApprovalRound.RESULT_RETURNED)

        # повторная отправка -> новый круг №2, история №1 сохранена
        r2 = services.start_new_round(ap, [internal(10), internal(20)])
        ap.refresh_from_db()
        self.assertEqual(ap.current_round, 2)
        self.assertEqual(ap.rounds.count(), 2)
        self.assertEqual(r2.round_number, 2)

    def test_new_round_forbidden_when_in_progress(self):
        ap = make_approval()
        services.submit(ap, [internal(10)])
        with self.assertRaises(services.ApprovalError):
            services.start_new_round(ap, [internal(20)])


class RouteChangeTests(TestCase):
    def test_change_route_logs_snapshots(self):
        ap = make_approval()
        services.submit(ap, [internal(10), internal(20)])

        log = services.change_route(
            ap, [internal(10), internal(30), internal(40)],
            by_b24_id=1, reason="добавил финдиректора",
        )
        self.assertEqual(len(log.old_route_snapshot), 2)
        self.assertEqual(len(log.new_route_snapshot), 3)
        self.assertEqual(services.get_current_round(ap).participants.count(), 3)

    def test_change_route_blocked_after_decision(self):
        ap = make_approval()
        rnd = services.submit(ap, [internal(10), internal(20)])
        services.decide(rnd.participants.first(), "approve")
        with self.assertRaises(services.ApprovalError):
            services.change_route(ap, [internal(30)], reason="поздно")


class LinkedObjectTests(TestCase):
    def test_approval_links_to_agreement(self):
        agreement = Agreement.objects.create(title="Договор", author_b24_id=1)
        ap = make_approval(linked=agreement)
        self.assertEqual(ap.linked_object, agreement)


class SheetPdfTests(TestCase):
    def _completed_approval(self):
        ap = make_approval(flow=Approval.FLOW_SEQUENTIAL)
        r1 = services.submit(
            ap, [internal(10, 0, "initiator"), internal(20, 1, "approver")]
        )
        # круг 1: первый согласовал, затем вернули на доработку
        services.decide(r1.participants.order_by("order").first(), "approve", "ок")
        services.return_for_revision(ap, comment="правки")
        # круг 2: повторная отправка и полное согласование -> completed
        r2 = services.start_new_round(ap, [internal(20, 0, "approver")])
        services.decide(r2.participants.first(), "approve", "теперь ок")
        ap.refresh_from_db()
        return ap

    def test_render_pdf_bytes(self):
        ap = self._completed_approval()
        pdf = render_pdf(ap)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 800)

    def test_generate_sheet_saves_file(self):
        ap = self._completed_approval()
        sheet = generate_sheet(ap, generated_by_b24_id=1)
        self.assertTrue(sheet.generated_file.name.endswith(".pdf"))
        self.assertEqual(sheet.format, "pdf")
        sheet.generated_file.seek(0)
        self.assertTrue(sheet.generated_file.read(4) == b"%PDF")


class ApiTests(TestCase):
    AUTHOR = 1
    APPROVER = 20

    def test_requires_auth(self):
        self.assertIn(api().get("/api/approvalflow/approvals/").status_code, (401, 403))

    def test_create_submit_decide_flow(self):
        # создать черновик
        r = api(self.AUTHOR).post(
            "/api/approvalflow/approvals/",
            {"approval_type": "discount", "title": "Скидка", "flow_type": "parallel"},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        ap_id = r.json()["id"]

        # отправить с участниками
        r = api(self.AUTHOR).post(
            f"/api/approvalflow/approvals/{ap_id}/submit/",
            {"participants": [{"type": "internal", "b24_user_id": self.APPROVER, "order": 0}]},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "in_progress")
        participant_id = data["rounds"][0]["participants"][0]["id"]

        # согласующий принимает решение
        r = api(self.APPROVER).post(
            f"/api/approvalflow/approvals/{ap_id}/decide/",
            {"participant_id": participant_id, "decision": "approve"},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "completed")

    def test_decide_forbidden_for_non_participant(self):
        ap = Approval.objects.create(title="x", initiator_b24_id=self.AUTHOR)
        rnd = services.submit(ap, [internal(self.APPROVER)])
        pid = rnd.participants.first().id
        # чужой пользователь (не тот участник)
        r = api(999).post(
            f"/api/approvalflow/approvals/{ap.id}/decide/",
            {"participant_id": pid, "decision": "approve"},
            format="json",
        )
        # 999 не участник -> согласование не в его выборке -> 404
        self.assertIn(r.status_code, (403, 404))

    def test_list_scoped_to_user(self):
        mine = Approval.objects.create(title="моё", initiator_b24_id=self.AUTHOR)
        Approval.objects.create(title="чужое", initiator_b24_id=555)
        data = api(self.AUTHOR).get("/api/approvalflow/approvals/").json()
        self.assertEqual({a["title"] for a in data}, {"моё"})

    def test_generate_and_download_sheet(self):
        ap = Approval.objects.create(title="x", initiator_b24_id=self.AUTHOR)
        services.submit(ap, [internal(self.APPROVER)])
        r = api(self.AUTHOR).post(
            f"/api/approvalflow/approvals/{ap.id}/generate_sheet/"
        )
        self.assertEqual(r.status_code, 201)
        url = r.json()["file_url"]
        resp = api(self.AUTHOR).get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")


class SheetWhoTests(TestCase):
    """Отображение согласующего в листе: групповой юрслот vs реальный юрист."""

    def test_group_legal_unassigned_shows_department(self):
        p = ApprovalParticipant(type="internal", role="legal_dept", b24_user_id=None)
        self.assertEqual(_who(p, {}, {}), "Юридический отдел")

    def test_group_legal_resolved_shows_actual_lawyer(self):
        p = ApprovalParticipant(type="internal", role="legal_dept", b24_user_id=30)
        self.assertEqual(_who(p, {30: "Юрист Юрьев"}, {}), "Юрист Юрьев")

    def test_internal_resolved_by_name(self):
        p = ApprovalParticipant(type="internal", role="cfo_head", b24_user_id=5)
        self.assertEqual(_who(p, {5: "Иван Иванов"}, {}), "Иван Иванов")
