"""Export the whole database (studies, users, audit log) to a JSON file.

Usage (from the project root):
    python tools/backup.py backups/stability_YYYYMMDD.json

Notes:
  - The output contains user password hashes and the audit trail. Store it securely.
  - Restore is done through the "系统维护 / System maintenance" page in the app.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import db as DB  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out = sys.argv[1]
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    DB.init()
    data = DB.export_all_json()
    with open(out, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"backup written: {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
