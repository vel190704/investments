"""CLI: python -m app.refresh — fetch latest prices/NAVs into the cache now."""

import sys

from app.db import init_db, session_scope
from app.market.service import refresh_prices


def main() -> int:
    init_db()
    with session_scope() as s:
        r = refresh_prices(s, trigger="manual")
    print(f"{r['ok_count']} updated, {r['error_count']} unavailable")
    for x in r["results"]:
        print(f"  {'ok ' if x['ok'] else 'N/A'} {x['name']}: "
              + (f"{x['price']} ({x['source']}, {x['price_date']})" if x["ok"] else x["error"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
