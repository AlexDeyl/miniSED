"""
Операции с документами и версиями.
"""

from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from .models import Document, DocumentVersion


def _checksum(file) -> str:
    file.seek(0)
    sha = hashlib.sha256()
    for chunk in file.chunks():
        sha.update(chunk)
    file.seek(0)
    return sha.hexdigest()


def create_document(
    *,
    title: str,
    linked_object=None,
    document_type: str = "",
    is_confidential: bool = False,
    created_by_b24_id: int | None = None,
) -> Document:
    doc = Document(
        title=title,
        document_type=document_type,
        is_confidential=is_confidential,
        created_by_b24_id=created_by_b24_id,
    )
    if linked_object is not None:
        doc.linked_object = linked_object
    doc.save()
    return doc


@transaction.atomic
def add_version(
    document: Document,
    file,
    *,
    uploaded_by_b24_id: int | None = None,
    change_comment: str = "",
) -> DocumentVersion:
    """
    Добавляет новую версию файла и делает её актуальной.
    Предыдущие версии сохраняются в истории (is_current=False).
    """
    last = document.versions.order_by("-version_number").first()
    next_number = (last.version_number + 1) if last else 1

    document.versions.filter(is_current=True).update(is_current=False)

    version = DocumentVersion.objects.create(
        document=document,
        version_number=next_number,
        file=file,
        original_filename=getattr(file, "name", "")[:500],
        uploaded_by_b24_id=uploaded_by_b24_id,
        change_comment=change_comment,
        is_current=True,
        file_size=getattr(file, "size", None),
        mime_type=getattr(file, "content_type", "") or "",
        checksum=_checksum(file),
    )

    document.current_version = version
    document.save(update_fields=["current_version", "updated_at"])
    return version


def soft_delete(document: Document) -> None:
    """Мягкое удаление (ТЗ п.15.6): файл и история остаются, карточка скрывается."""
    document.deleted_at = timezone.now()
    document.save(update_fields=["deleted_at", "updated_at"])
