"""
Поиск по регламентным заявкам (доверенности, МЧД, ЭЦП).

Юристу и инициатору нужно находить заявку по тому, что помнят: ФИО
представителя, номер, паспорт, организация, куда выдана доверенность. Часть
этих данных лежит в реквизитах модели, часть — в анкете (JSON-поле data), где
живут ФИО по частям, паспорт, реквизиты юрлица и цель выдачи. Отдельно ищем по
прикреплённым файлам: готовую доверенность юрист прикладывает к заявке при
исполнении, и потом её находят именно по имени файла.

Механика (И между словами, регистр, JSON, файлы) — общая для всех разделов,
см. core.search; здесь только набор полей заявки.
"""

from __future__ import annotations

from core.search import document_fields, search as _search

# Поля модели, по которым ищем (кроме анкеты — она через приведение к тексту).
SEARCH_FIELDS = (
    "number",
    "subject_name",
    "position",
    "department",
    "basis",
    "comment",
    "delivery_comment",
    "organization__short_name",
    "facility__name",
    "cfo__name",
)

# Прикреплённые файлы: название документа и оригинальное имя файла.
DOCUMENT_FIELDS = document_fields()


def search(qs, query: str):
    """Фильтрует queryset заявок по строке поиска. Пустой запрос — без изменений."""
    return _search(
        qs, query,
        fields=SEARCH_FIELDS,
        json_fields=("data",),
        file_fields=DOCUMENT_FIELDS,
    )
