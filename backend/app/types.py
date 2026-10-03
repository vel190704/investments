"""Exact decimal column type.

SQLite's NUMERIC affinity stores floats, so decimals are persisted as canonical text.
On Postgres this could become NUMERIC without touching callers.
"""

from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


def decimal_to_str(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


class DecimalText(TypeDecorator):
    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return decimal_to_str(Decimal(value))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)
