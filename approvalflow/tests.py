"""
Тесты движка согласований: круги, решения, последовательность, возврат,
повторная отправка, правка маршрута, лист согласования PDF.
"""

from django.test import TestCase

from approvals.models import Agreement
from .models import Approval, ApprovalParticipant, ApprovalRound
from . import services
from .sheet import generate_sheet, render_pdf


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
