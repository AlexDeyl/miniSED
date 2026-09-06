"""
Просмотр документа по токен-ссылке (страница согласования из письма).

Главное здесь — граница доступа: токен открывает документы ТОЛЬКО своей
карточки. Поэтому в каждом сценарии рядом с «своё видно» стоит «чужое не
видно», иначе ссылка из письма превратилась бы в универсальный ключ к
хранилищу.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from approvalflow.models import ApprovalParticipant
from approvals.models import Agreement, AgreementDocument, Participant
from contracts.models import Contract
from contracts import services as contract_services
from core.models import Organization
from documents import services as docsvc
from requests_reg import constants as C, services as reg_services


class ExternalDocumentAccessTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(short_name="УК Норд")

    # --- вспомогательное ---
    def _request_with_doc(self, subject="Петров", filename="doverennost.pdf"):
        req = reg_services.create_request(
            request_type=C.TYPE_POA, organization=self.org,
            initiator_b24_id=1, subject_name=subject,
        )
        reg_services.submit(req, [
            {"type": "internal", "b24_user_id": 20, "order": 0, "role": C.ROLE_CFO_HEAD},
        ])
        approval = reg_services.get_approval(req)
        participant = ApprovalParticipant.objects.filter(round__approval=approval).first()
        doc = docsvc.create_document(title="Скан доверенности", linked_object=req)
        docsvc.add_version(doc, SimpleUploadedFile(filename, b"%PDF-1.4 test"))
        return req, participant, doc

    # --- страница согласования показывает документы ---
    def test_request_page_lists_documents(self):
        """Регрессия: список собирался по несуществующему полю Document.file и
        всегда был пустым — участник согласовывал вслепую."""
        req, participant, doc = self._request_with_doc()
        r = self.client.get(f"/external/reg/approve/{participant.external_token}/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"/external/doc/{participant.external_token}/{doc.id}/",
                      r.content.decode())

    def test_contract_page_does_not_link_api(self):
        """Договоры вели на /api/documents/…, а он требует X-B24-User —
        браузер из почты его не шлёт, и вместо файла приходил отказ."""
        contract = Contract.objects.create(
            organization=self.org, title="Договор аренды", initiator_b24_id=1,
        )
        contract_services.submit(contract, [
            {"type": "internal", "b24_user_id": 20, "order": 0, "role": "cfo_head"},
        ])
        approval = contract_services.get_approval(contract)
        participant = ApprovalParticipant.objects.filter(round__approval=approval).first()
        doc = docsvc.create_document(title="Проект договора", linked_object=contract)
        docsvc.add_version(doc, SimpleUploadedFile("dogovor.pdf", b"%PDF-1.4"))

        body = self.client.get(
            f"/external/contract/approve/{participant.external_token}/"
        ).content.decode()
        self.assertIn(f"/external/doc/{participant.external_token}/{doc.id}/", body)
        self.assertNotIn("/api/documents/", body)

    # --- сама выдача файла ---
    def test_file_served_without_any_auth(self):
        """Ссылку открывает браузер из почты — без заголовков и сессии."""
        req, participant, doc = self._request_with_doc()
        r = self.client.get(f"/external/doc/{participant.external_token}/{doc.id}/")
        self.assertEqual(r.status_code, 200)
        # инлайн: документ нужно посмотреть, а не скачать
        self.assertIn("inline", r["Content-Disposition"])

    def test_api_endpoint_still_requires_auth(self):
        """Обычный API документов остаётся закрытым — мы его не ослабили."""
        req, participant, doc = self._request_with_doc()
        version = doc.current_version
        r = self.client.get(f"/api/documents/{doc.id}/versions/{version.id}/download/")
        self.assertIn(r.status_code, (401, 403))

    # --- граница доступа ---
    def test_foreign_document_not_reachable(self):
        """Токен одной заявки не открывает документ другой — перебор id бесполезен."""
        _, participant, _ = self._request_with_doc(subject="Петров")
        _, _, foreign_doc = self._request_with_doc(subject="Сидоров", filename="other.pdf")
        r = self.client.get(f"/external/doc/{participant.external_token}/{foreign_doc.id}/")
        self.assertEqual(r.status_code, 404)

    def test_unknown_token_rejected(self):
        _, _, doc = self._request_with_doc()
        r = self.client.get(f"/external/doc/no-such-token/{doc.id}/")
        self.assertEqual(r.status_code, 404)

    def test_deleted_document_not_served(self):
        req, participant, doc = self._request_with_doc()
        doc.deleted_at = timezone.now()
        doc.save(update_fields=["deleted_at"])
        r = self.client.get(f"/external/doc/{participant.external_token}/{doc.id}/")
        self.assertEqual(r.status_code, 404)

    def test_missing_document_id(self):
        _, participant, _ = self._request_with_doc()
        r = self.client.get(f"/external/doc/{participant.external_token}/999999/")
        self.assertEqual(r.status_code, 404)

    # --- старый движок согласований ---
    def test_agreement_legacy_file_by_token(self):
        agreement = Agreement.objects.create(
            title="Согласование", author_b24_id=1, flow_type="parallel",
            status="in_progress",
        )
        part = Participant.objects.create(
            agreement=agreement, type="external", email="x@example.com", order_index=0,
        )
        doc = AgreementDocument.objects.create(
            agreement=agreement, type="file",
            file=SimpleUploadedFile("smeta.pdf", b"%PDF-1.4"),
        )
        r = self.client.get(f"/external/file/{part.external_token}/{doc.id}/")
        self.assertEqual(r.status_code, 200)

        other = Agreement.objects.create(
            title="Чужое", author_b24_id=1, flow_type="parallel", status="in_progress",
        )
        other_doc = AgreementDocument.objects.create(
            agreement=other, type="file",
            file=SimpleUploadedFile("foreign.pdf", b"%PDF-1.4"),
        )
        r = self.client.get(f"/external/file/{part.external_token}/{other_doc.id}/")
        self.assertEqual(r.status_code, 404)
