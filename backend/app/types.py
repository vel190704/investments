"""Custom column types: exact decimals (DecimalText) and UTC datetimes (UTCDateTime).

SQLite's NUMERIC affinity stores floats, so decimals are persisted as canonical text.
On Postgres this could become NUMERIC without touching callers.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, String
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


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime stored as UTC. SQLite keeps no zone and does not convert, so an IST value written or
    compared as-is would be read back 5 h 30 min off; every bound value is converted to UTC here, and values read
    back carry tzinfo=UTC. (On Postgres this is a plain timestamptz.)"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or not isinstance(value, datetime):
            return value
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
