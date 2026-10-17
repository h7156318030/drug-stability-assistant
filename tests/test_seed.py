"""示例数据生成工具（tools/seed_example.py）可在空库上运行（回归：外键启用后 tp_ref 须正确关联）"""
import sys, os, tempfile, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


print("== seed_example on an empty database ==")
proc = subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "seed_example.py")],
                      capture_output=True, text=True, encoding="utf-8", errors="replace")
check("seed tool exits with code 0", proc.returncode == 0)
check("seed reports two generated studies", proc.stdout.count("示例已生成") == 2)
if proc.returncode != 0:
    print(proc.stderr[-1500:])

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
