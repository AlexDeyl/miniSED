"""
Поиск по договорам.

Договор ищут по номеру, названию, контрагенту из названия, юрлицу/ЦФО и по
приложенному файлу: подписанный скан прикладывают к карточке, и дальше её
находят именно по имени файла. Механика — общая, см. core.search.
"""

from __future__ import annotations

from core.search import document_fields, search as _search

SEARCH_FIELDS = (
    "number",
    "title",
    "comment",
    "crm_link",
    "organization__short_name",
    "cfo__name",
)

DOCUMENT_FIELDS = document_fields()


def search(qs, query: str):
    """Фильтрует queryset договоров. Пустой запрос — без изменений."""
    return _search(
        qs, query,
        fields=SEARCH_FIELDS,
        json_fields=("data",),
        file_fields=DOCUMENT_FIELDS,
    )
