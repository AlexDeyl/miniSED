"""
Общий поиск по спискам разделов (согласования, договоры, комплименты,
регламентные заявки).

Сначала поиск появился в регламентных заявках (доверенности/МЧД): юристу и
инициатору нужно находить карточку по тому, что помнят — ФИО, номер, паспорт,
организация. Требование к остальным разделам ровно то же, включая главное:
искать И ПО ИМЕНИ ПРИКРЕПЛЁННОГО ФАЙЛА. Готовый документ (доверенность, скан
подписанного договора) прикладывают к карточке при исполнении, и дальше его
ищут именно по имени файла, а не по реквизитам.

Поэтому механика вынесена сюда, а разделы объявляют только свой набор полей:
`fields` — обычные поля модели (можно с JOIN через `__`),
`json_fields` — JSON-поля (анкета, доп. поля): приводим к тексту и ищем в нём,
`file_fields` — пути до текстовых полей файлов вместе с доп. условиями
(например «документ не удалён»),
`match_pk` — искать по номеру карточки, если раздел нумерует карточки по id.

Несколько слов — это И: «иванов договор» найдёт карточку, где есть оба.

Регистр: в бою Postgres, icontains → ILIKE, кириллица ищется без учёта регистра
и в JSON тоже (jsonb::text отдаёт настоящий UTF-8). В SQLite (локальные тесты)
ни того, ни другого нет — LIKE регистронезависим только для ASCII, а JSON
хранится с экранированием, поэтому такие проверки помечены skipUnless.
"""

from __future__ import annotations

from urllib.parse import unquote_to_bytes

from django.db.models import Q, TextField
from django.db.models.functions import Cast

# Больше слов в запросе — это уже не поиск; ограничиваем, чтобы не плодить JOIN.
MAX_TERMS = 6


def query_param(request, name, default=""):
    """GET-параметр с устойчивым декодированием кириллицы.

    Периметр (openresty) перекодирует кириллицу в query-строке из UTF-8 в CP1251,
    поэтому читаем СЫРЫЕ байты query и пробуем UTF-8, затем CP1251 (иначе Django
    декодирует cp1251-байты как UTF-8 и получается мусор).

    QUERY_STRING по WSGI — это байты, декодированные как latin-1, поэтому перед
    раскодированием %XX возвращаем строку в байты тем же latin-1. Иначе клиент,
    приславший кириллицу в query БЕЗ процентного кодирования, доезжал мусором.
    """
    qs = request.META.get("QUERY_STRING", "") or ""
    prefix = name + "="
    for part in qs.split("&"):
        if part.startswith(prefix):
            value = part[len(prefix):].replace("+", " ")
            try:
                raw = unquote_to_bytes(value.encode("latin-1"))
            except UnicodeEncodeError:  # не из WSGI (тесты, внутренние вызовы)
                raw = unquote_to_bytes(value)
            for enc in ("utf-8", "cp1251"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
    return default


def document_fields(prefix: str = "documents", deleted_field: str = "deleted_at"):
    """Поля прикреплённого документа приложения `documents` (GenericRelation).

    Ищем и по названию документа, и по оригинальному имени загруженного файла.
    Условия для ОДНОГО поля собраны в общий словарь: значит, они про один и тот
    же документ, и удалённый (soft delete) файл в результаты не вытащит.
    """
    extra = {f"{prefix}__{deleted_field}__isnull": True} if deleted_field else {}
    return (
        (f"{prefix}__title", extra),
        (f"{prefix}__versions__original_filename", extra),
    )


def search(
    qs,
    query: str,
    *,
    fields=(),
    json_fields=(),
    file_fields=(),
    match_pk: bool = False,
    max_terms: int = MAX_TERMS,
):
    """Фильтрует queryset по строке поиска. Пустой запрос — без изменений."""
    query = (query or "").strip()
    if not query:
        return qs

    # JSON-поля: в тексте попадаются и ключи, но для поиска по ФИО/паспорту/ИНН
    # этого достаточно, а отдельный индекс тут не нужен.
    json_aliases = []
    for i, path in enumerate(json_fields):
        alias = f"_search_json_{i}"
        qs = qs.annotate(**{alias: Cast(path, TextField())})
        json_aliases.append(alias)

    text_fields = list(fields) + json_aliases
    for term in query.split()[:max_terms]:
        condition = Q()
        if match_pk:
            # карточку без собственного номера ищут по «#12» / «12» / «№12»
            digits = term.lstrip("#№")
            if digits.isdigit():
                condition |= Q(pk=int(digits))
        for path in text_fields:
            condition |= Q(**{f"{path}__icontains": term})
        for path, extra in file_fields:
            condition |= Q(**{f"{path}__icontains": term, **extra})
        qs = qs.filter(condition)
    # JOIN по участникам/документам/версиям размножает строки — схлопываем.
    return qs.distinct()
