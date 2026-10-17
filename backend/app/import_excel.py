"""CLI: python -m app.import_excel <path-to-xlsx> [--no-resolve]"""

import argparse
import sys

from app.db import init_db, session_scope
from app.importer.run import format_report, import_workbook, preview_workbook


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import the personal investment tracker workbook.")
    ap.add_argument("path")
    ap.add_argument("--no-resolve", action="store_true",
                    help="skip ISIN / AMFI scheme-code matching (no network)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change; save nothing")
    args = ap.parse_args(argv)
    init_db()
    if args.dry_run:
        with session_scope() as s:
            report = preview_workbook(s, args.path)
        print("DRY RUN — nothing was saved\n" + format_report(report))
        tr = report["transactions"]
        for r in tr["added_rows"]:
            print(f"  + row {r['row']}: {r['date']} {r['type']} {r['name']} qty {r['quantity']}")
        for r in tr["removed_rows"]:
            print(f"  - {r['date']} {r['type']} {r['name']} qty {r['quantity']} (excel row {r['source_row']})")
        return 0 if report["ok"] else 1
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
