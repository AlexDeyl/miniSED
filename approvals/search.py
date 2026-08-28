"""
Поиск по согласованиям (раздел «Согласования» / светофор).

Согласование помнят по названию, автору-инициатору, сделке из CRM и по
приложенному файлу («тот договор аренды, который скидывали PDF-кой»). Поэтому
ищем и по реквизитам, и по именам файлов — сразу в двух хранилищах: старые
файлы лежат в AgreementDocument (FileField), новые — в приложении documents.

Своего номера у согласования нет, карточку называют по id («#412»), поэтому
включён поиск по pk. Механика — общая, см. core.search.
"""

from __future__ import annotations

from core.search import document_fields, search as _search

SEARCH_FIELDS = (
    "title",
    "description",
    "crm_link",
    # участники: внешнего согласующего ищут по адресу, комментарий решения —
    # то, что реально помнят про отклонённое согласование
    "participants__email",
    "participants__name",
    "participants__comment",
)

# Имя файла в двух хранилищах: FileField исторических документов (путь внутри
# media содержит исходное имя) и версии документов приложения documents.
DOCUMENT_FIELDS = (
    ("documents__file", {}),
    ("documents__url", {}),
    *document_fields("versioned_documents"),
)


def search(qs, query: str):
    """Фильтрует queryset согласований. Пустой запрос — без изменений."""
    return _search(
        qs, query,
        fields=SEARCH_FIELDS,
        file_fields=DOCUMENT_FIELDS,
        match_pk=True,
    )
