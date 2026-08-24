"""Форматирование значений для писем и уведомлений (человекочитаемый вид)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


def money(value) -> str:
    """Сумма как в интерфейсе: «100 000 ₽», с копейками — только если они есть.

    Пустая строка для None/нечисла — вызывающему достаточно `if money(...)`."""
    if value is None or value == "":
        return ""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    quantized = amount.quantize(Decimal("0.01"))
    text = f"{quantized:,.2f}".replace(",", " ")  # неразрывный пробел
    if text.endswith(".00"):
        text = text[:-3]
    return f"{text.replace('.', ',')} ₽"
