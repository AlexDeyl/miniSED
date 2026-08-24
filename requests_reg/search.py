"""
Поиск по регламентным заявкам.

Юристу и инициатору нужно находить заявку по тому, что помнят: ФИО
представителя, номер, паспорт, организация, куда выдана доверенность. Часть
этих данных лежит в реквизитах модели, часть — в анкете (JSON-поле data), где
живут ФИО по частям, паспорт, реквизиты юрлица и цель выдачи. Поэтому анкету
приводим к тексту и ищем и по ней тоже. Отдельно ищем по прикреплённым файлам:
готовую доверенность юрист прикладывает к заявке при исполнении, и потом её
находят именно по имени файла.

Несколько слов — это И: «иванов доверенность» найдёт заявку, где есть оба.

Регистр: в бою Postgres, icontains → ILIKE, кириллица ищется без учёта регистра
и в анкете тоже (jsonb::text отдаёт настоящий UTF-8). В SQLite (локальные
тесты) ни того, ни другого нет — LIKE регистронезависим только для ASCII, а
JSON хранится с экранированием, поэтому такие проверки помечены skipUnless.
"""

from __future__ import annotations

from django.db.models import Q, TextField
from django.db.models.functions import Cast

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

# Прикреплённые файлы: название документа и оригинальное имя файла. Готовую
# доверенность юрист прикладывает к заявке при исполнении, и дальше её ищут
# именно по имени файла.
DOCUMENT_FIELDS = (
    "documents__title",
    "documents__versions__original_filename",
)

# Больше слов в запросе — это уже не поиск; ограничиваем, чтобы не плодить JOIN.
MAX_TERMS = 6


def search(qs, query: str):
    """Фильтрует queryset заявок по строке поиска. Пустой запрос — без изменений."""
    query = (query or "").strip()
    if not query:
        return qs

    # data — JSONField; в тексте анкеты попадаются и ключи, но для поиска по
    # ФИО/паспорту/ИНН этого достаточно, а отдельный индекс тут не нужен.
    qs = qs.annotate(_anketa_text=Cast("data", TextField()))
    for term in query.split()[:MAX_TERMS]:
        condition = Q(_anketa_text__icontains=term)
        for field in SEARCH_FIELDS:
            condition |= Q(**{f"{field}__icontains": term})
        for field in DOCUMENT_FIELDS:
            # Условия в одном Q — значит про ОДИН и тот же документ: удалённый
            # (soft delete) файл находиться не должен.
            condition |= Q(**{
                f"{field}__icontains": term,
                "documents__deleted_at__isnull": True,
            })
        qs = qs.filter(condition)
    # JOIN по документам/версиям размножает строки — схлопываем.
    return qs.distinct()
