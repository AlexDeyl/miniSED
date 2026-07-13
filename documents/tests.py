"""
Тесты версионирования документов.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from approvals.models import Agreement
from .models import Document, DocumentVersion
from . import services


def upload(name, content=b"data"):
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


class DocumentVersioningTests(TestCase):
    def test_create_and_add_versions(self):
        agreement = Agreement.objects.create(title="Договор", author_b24_id=1)
        doc = services.create_document(
            title="Договор поставки",
            linked_object=agreement,
            created_by_b24_id=1,
        )
        self.assertEqual(doc.linked_object, agreement)

        v1 = services.add_version(doc, upload("dogovor.pdf", b"v1"), uploaded_by_b24_id=1)
        doc.refresh_from_db()
        self.assertEqual(v1.version_number, 1)
        self.assertTrue(v1.is_current)
        self.assertEqual(doc.current_version_id, v1.id)
        self.assertEqual(v1.checksum, __import__("hashlib").sha256(b"v1").hexdigest())

        v2 = services.add_version(
            doc, upload("dogovor.pdf", b"v2-edited"),
            uploaded_by_b24_id=2, change_comment="после юриста",
        )
        doc.refresh_from_db()
        v1.refresh_from_db()

        # новая версия актуальна, старая сохранена но не актуальна
        self.assertEqual(v2.version_number, 2)
        self.assertTrue(v2.is_current)
        self.assertFalse(v1.is_current)
        self.assertEqual(doc.current_version_id, v2.id)
        self.assertEqual(doc.versions.count(), 2)

    def test_soft_delete_keeps_history(self):
        doc = services.create_document(title="Скан")
        services.add_version(doc, upload("scan.pdf"))
        services.soft_delete(doc)
        doc.refresh_from_db()
        self.assertTrue(doc.is_deleted)
        # версии на месте
        self.assertEqual(doc.versions.count(), 1)

    def test_unique_version_number_per_document(self):
        doc = services.create_document(title="X")
        services.add_version(doc, upload("a.pdf"))
        services.add_version(doc, upload("b.pdf"))
        numbers = list(doc.versions.values_list("version_number", flat=True))
        self.assertEqual(sorted(numbers), [1, 2])
