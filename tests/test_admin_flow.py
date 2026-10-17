"""管理员页面流程：系统维护页渲染；删除研究须重新输入口令（电子签名）"""
import sys, os, tempfile, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'

from streamlit.testing.v1 import AppTest
import db as DB

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


def button(at, label):
    return next(b for b in at.button if b.label == label)


def text_input_starting(at, prefix):
    return next(t for t in at.text_input if t.label.startswith(prefix))


# seed two demo studies into the isolated database
proc = subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "seed_example.py")],
                      capture_output=True, text=True, encoding="utf-8", errors="replace")
assert proc.returncode == 0, proc.stderr

at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=120)
at.session_state["user"] = {"username": "admin", "name": "Admin", "role": "admin"}
at.run()
check("home page renders without exception", len(at.exception) == 0)

at.sidebar.radio[0].set_value("系统维护").run()
check("maintenance page renders without exception", len(at.exception) == 0)
check("restore asks for password before restoring",
      any(t.label.startswith("请输入您的登录口令以确认恢复") for t in at.text_input))

at.sidebar.radio[0].set_value("研究管理").run()
check("studies page renders without exception", len(at.exception) == 0)
n_before = len(DB.list_studies())
check("two demo studies exist before delete test", n_before == 2)

# delete flow: request -> confirm with WRONG password (must not delete) -> confirm with right password
target = DB.list_studies()[0]["study_id"]
button(at, "删除该研究").click().run()
text_input_starting(at, "请输入您的登录口令以确认（电子签名）").input("wrong-password")
button(at, "✅ 确认删除").click().run()
check("wrong password does not delete the study", len(DB.list_studies()) == n_before)
check("wrong password shows an error", any("口令错误" in e.value for e in at.error))

button(at, "删除该研究").click().run()
text_input_starting(at, "请输入您的登录口令以确认（电子签名）").input("Test-Admin#2026")
button(at, "✅ 确认删除").click().run()
check("correct password deletes the study", len(DB.list_studies()) == n_before - 1)
check("deleted study is the requested one", DB.load_study(target) is None)

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
