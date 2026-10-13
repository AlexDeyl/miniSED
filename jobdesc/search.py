"""
Поиск по заявкам на согласование ДИ: номер, должность, ЦФО, юрлицо, объект,
комментарии и имена прикреплённых файлов (готовую ДИ ищут по имени скана).
Механика — общая, см. core.search.
"""

from __future__ import annotations

from core.search import document_fields, search as _search

SEARCH_FIELDS = (
    "number",
    "position_name",
    "description",
    "execution_comment",
    "cfo__name",
    "facility__name",
    "organization__short_name",
)

DOCUMENT_FIELDS = document_fields()


def search(qs, query: str):
    return _search(
        qs, query,
        fields=SEARCH_FIELDS,
        json_fields=("data",),
        file_fields=DOCUMENT_FIELDS,
    )
