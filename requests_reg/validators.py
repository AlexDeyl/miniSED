"""
Проверка идентификаторов представителя (ИНН, СНИЛС).

Нужны для МЧД: машиночитаемая доверенность подаётся в формате ФНС, где
представитель-физлицо идентифицируется именно ИНН и СНИЛС, а не паспортом.
Опечатка в них вскрывается уже на стороне ФНС, когда доверенность отклоняют, —
поэтому проверяем не только длину, но и контрольные разряды: они считаются
детерминированно и ловят перестановку цифр, самую частую ошибку при вводе.

Для бумажной доверенности (TYPE_POA) эти поля не нужны — там представителя
удостоверяет паспорт.
"""

from __future__ import annotations

from django.utils import timezone

from . import constants

# Веса контрольных разрядов ИНН физлица (12 цифр), по приказу ФНС.
_INN12_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def digits(value: str | None) -> str:
    """Только цифры: пользователь вводит СНИЛС с дефисами и пробелом."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _control(nums: list[int], weights) -> int:
    return sum(n * w for n, w in zip(nums, weights)) % 11 % 10


def is_valid_inn(value: str | None) -> bool:
    """ИНН физического лица — 12 цифр с двумя контрольными разрядами."""
    d = digits(value)
    if len(d) != 12:
        return False
    nums = [int(c) for c in d]
    return (
        _control(nums[:10], _INN12_W11) == nums[10]
        and _control(nums[:11], _INN12_W12) == nums[11]
    )


def is_valid_snils(value: str | None) -> bool:
    """СНИЛС — 11 цифр: 9 значащих + 2 контрольных.

    Контрольное число = сумма девяти цифр с весами 9…1 по модулю 101; 100 и 101
    записываются как 00 (правило ПФР)."""
    d = digits(value)
    if len(d) != 11:
        return False
    # Номера до 001-001-998 контрольного числа не имеют (историческое правило ПФР).
    if int(d[:9]) <= 1001998:
        return True
    checksum = sum(int(c) * (9 - i) for i, c in enumerate(d[:9])) % 101
    if checksum in (100, 101):
        checksum = 0
    return checksum == int(d[9:])


def format_snils(value: str | None) -> str:
    """СНИЛС в человеческом виде: XXX-XXX-XXX YY."""
    d = digits(value)
    if len(d) != 11:
        return (value or "").strip()
    return f"{d[0:3]}-{d[3:6]}-{d[6:9]} {d[9:]}"


def identifiers_required(created_at=None) -> bool:
    """Подпадает ли заявка под требование ИНН/СНИЛС.

    Требование ввели, когда часть заявок уже была подана, а редактировать
    анкету поданной заявки в интерфейсе нельзя: примени правило задним числом —
    и такую заявку станет невозможно ни отправить, ни исправить, только
    пересоздать. Поэтому смотрим на дату создания; None (заявки ещё нет) —
    это новая заявка, к ней правило применяется.
    """
    if created_at is None:
        return True
    return timezone.localtime(created_at).date() >= constants.MCHD_IDENTIFIERS_REQUIRED_FROM


def mchd_rep_error(data) -> str | None:
    """Ошибка анкеты МЧД по ИНН/СНИЛС представителя, либо None.

    Возвращает текст, а не исключение: вызывающие оборачивают его в формат
    своего слоя (DRF-ошибка при сохранении, RequestError при отправке)."""
    rep = (data or {}).get("rep") or {}

    inn = (rep.get("inn") or "").strip()
    if not inn:
        return "Для МЧД укажите ИНН представителя."
    if not is_valid_inn(inn):
        return "Проверьте ИНН представителя: должно быть 12 цифр, контрольный разряд не сходится."

    snils = (rep.get("snils") or "").strip()
    if not snils:
        return "Для МЧД укажите СНИЛС представителя."
    if not is_valid_snils(snils):
        return "Проверьте СНИЛС представителя: должно быть 11 цифр, контрольное число не сходится."
    return None
