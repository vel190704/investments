"""CLI: python -m app.import_excel <path-to-xlsx> [--no-resolve]"""

import argparse
import sys

from app.db import init_db, session_scope
from app.importer.run import format_report, import_workbook


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import the personal investment tracker workbook.")
    ap.add_argument("path")
    ap.add_argument("--no-resolve", action="store_true",
                    help="skip ISIN / AMFI scheme-code matching (no network)")
    args = ap.parse_args(argv)
    init_db()
    try:
        with session_scope() as s:
            report = import_workbook(s, args.path)
    except FileNotFoundError:
        print(f"File not found: {args.path}", file=sys.stderr)
        return 2
    print(format_report(report))
    if report["ok"] and not args.no_resolve:
        from app.resolve.service import resolve_identifiers

        try:
            with session_scope() as s:
                res = resolve_identifiers(s)
            print(f"\nIdentifier matching: {res['summary']}")
            print("Review and confirm the proposed matches on the Mappings page (/mappings).")
            from app.services.classification import refresh_classification

            with session_scope() as s:
                print(f"Classification: {refresh_classification(s)['summary']}")
        except Exception as e:  # network problems must not fail the import
            print(f"\nIdentifier matching skipped: {e}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
