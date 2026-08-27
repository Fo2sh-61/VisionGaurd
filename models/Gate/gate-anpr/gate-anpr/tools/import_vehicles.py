#!/usr/bin/env python3
"""
Bulk-import registered vehicles from Excel or CSV, from the command line.

The dashboard has an upload button that does the same thing; this is for the
first big load and for scripted syncs from an existing residents system.

    python tools/import_vehicles.py residents.xlsx
    python tools/import_vehicles.py residents.csv --dry-run
    python tools/import_vehicles.py --template vehicles_template.xlsx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anpr import db, plate_text                     # noqa: E402
from anpr.web.app import _read_csv, _read_xlsx      # noqa: E402


def make_template(path: Path) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "vehicles"
    headers = ["plate", "owner_name", "phone", "unit", "category",
               "car_make", "car_color", "valid_until", "notes"]
    arabic = ["رقم اللوحة", "اسم المالك", "الهاتف", "الوحدة/الشقة", "الفئة",
              "الماركة", "اللون", "صالح حتى", "ملاحظات"]
    ws.append(headers)
    ws.append(arabic)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2E5C8A")
    for c in ws[2]:
        c.font = Font(italic=True, color="777777")
    ws.append(["ب ج د ١٢٣٤", "محمد فؤاد", "01000000000", "A-12", "resident",
               "Toyota", "أبيض", "", ""])
    ws.append(["س ن م ٥٦٧", "شركة الصيانة", "01111111111", "", "staff",
               "Hyundai", "أزرق", "", "عقد سنوي"])
    ws.append(["ل م ن ٧٨٩", "زائر", "", "B-3", "visitor", "", "",
               "2026-12-31", "تصريح مؤقت"])
    ws["A8"] = "الفئات المسموحة / categories:"
    ws["A9"] = "resident (ساكن) | staff (موظف) | visitor (زائر) | vip | blacklist (محظور)"
    ws["A11"] = "ملاحظة: يمكن كتابة الأرقام بالعربية أو الإنجليزية — النظام يوحّدها."
    for i, w in enumerate([20, 24, 16, 14, 12, 14, 12, 14, 26], start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    wb.save(path)
    print(f"✓ template -> {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help=".xlsx or .csv to import")
    ap.add_argument("--template", metavar="PATH",
                    help="write an empty import template and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and validate, write nothing")
    args = ap.parse_args()

    if args.template:
        return make_template(Path(args.template))
    if not args.file:
        ap.print_help()
        return 1

    p = Path(args.file)
    if not p.exists():
        print(f"not found: {p}")
        return 1
    raw = p.read_bytes()
    rows = (_read_xlsx(raw) if p.suffix.lower() in (".xlsx", ".xlsm")
            else _read_csv(raw))
    print(f"parsed {len(rows)} rows from {p.name}")

    if args.dry_run:
        bad = 0
        for i, r in enumerate(rows[:2000], start=2):
            norm = plate_text.normalize(r.get("plate", ""))
            flag = ""
            if not norm:
                flag, bad = "  ✗ unreadable plate", bad + 1
            elif not plate_text.is_wellformed(norm):
                flag, bad = "  ⚠ unusual format", bad + 1
            print(f"  {i:>4}  {plate_text.display(norm) or r.get('plate'):<18}"
                  f"{r.get('owner_name', ''):<20}{flag}")
        print(f"\ndry run: {len(rows) - bad} clean, {bad} need attention")
        return 0

    res = db.bulk_import(db.connect(), rows)
    print(f"\n✓ imported {res['imported']}   ✗ failed {res['failed']}")
    for prob in res["problems"][:40]:
        print("   " + prob)
    if len(res["problems"]) > 40:
        print(f"   … and {len(res['problems']) - 40} more")
    return 0 if not res["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
