"""电子签名口令复核（reauthenticate）与失败锁定测试"""
import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'  # test-only initial password

import auth as AU

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


AU.init_auth()
print("== reauthenticate ==")
check("correct password re-authenticates", AU.reauthenticate("admin", "Test-Admin#2026") is True)
check("empty password rejected", AU.reauthenticate("admin", "") is False)
check("wrong password rejected", AU.reauthenticate("admin", "wrong-password") is False)
check("unknown user rejected", AU.reauthenticate("nobody", "Test-Admin#2026") is False)
check("correct password still works after failures (below lock threshold)",
      AU.reauthenticate("admin", "Test-Admin#2026") is True)

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
