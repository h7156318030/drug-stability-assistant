"""unittest wrapper: runs every tests/test_*.py script in its own process.

Run with:
    python -X utf8 -m unittest discover -s tests -p "suite_*.py"
"""
import glob
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = sorted(glob.glob(os.path.join(HERE, "test_*.py")))


class TestScripts(unittest.TestCase):
    pass


def _make_test(path):
    def test(self):
        proc = subprocess.run([sys.executable, "-X", "utf8", path],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0,
                         msg=f"{os.path.basename(path)} failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return test


for _p in SCRIPTS:
    setattr(TestScripts, "test_" + os.path.basename(_p)[:-3], _make_test(_p))


if __name__ == "__main__":
    unittest.main()
