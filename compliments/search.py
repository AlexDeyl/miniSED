"""
Поиск по заявкам на комплименты.

Заявку помнят по компании-получателю, ФИО гостя, отелю и тому, что именно
вручали, а исполнитель — ещё и по своему комментарию. Плюс поиск по именам
прикреплённых файлов (бланк, подтверждение вручения). Механика — общая,
см. core.search.
"""

from __future__ import annotations

from core.search import document_fields, search as _search

SEARCH_FIELDS = (
    "number",
    "title",
    "company",
    "guest_name",
    "category_details",
    "description",
    "department",
    "execution_comment",
    "facility__name",
    "organization__short_name",
)

DOCUMENT_FIELDS = document_fields()


def search(qs, query: str):
    """Фильтрует queryset заявок на комплименты. Пустой запрос — без изменений."""
    return _search(
        qs, query,
        fields=SEARCH_FIELDS,
        json_fields=("data",),
        file_fields=DOCUMENT_FIELDS,
    )
