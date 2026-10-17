"""Run every test script in tests/ in its own process and report a summary.

Usage (from the project root):
    python tests/run_all.py

Each test script creates its own temporary data directory (STAB_DATA_DIR),
so the live stability.db is never modified.
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    scripts = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    failed = []
    for path in scripts:
        name = os.path.basename(path)
        proc = subprocess.run([sys.executable, "-X", "utf8", path],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        status = "PASS" if proc.returncode == 0 else "FAIL"
        print(f"[{status}] {name}")
        if proc.returncode != 0:
            failed.append(name)
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:])
    print(f"\n{len(scripts) - len(failed)}/{len(scripts)} test scripts passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
