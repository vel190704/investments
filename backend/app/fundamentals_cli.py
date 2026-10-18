"""CLI: python -m app.fundamentals_cli — fetch fundamentals (yfinance) now."""

import sys

from app.db import init_db, session_scope
from app.services.fundamentals import refresh_fundamentals


def main() -> int:
    from app.logging_config import configure_logging

    configure_logging()
    init_db()
    with session_scope() as s:
        r = refresh_fundamentals(s)
    print(r["summary"])
    for e in r["errors"]:
        print("  -", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
