"""界面工作流测试（Streamlit AppTest）：登录、角色导航、研究创建、样品、检测值录入、示例加载、全页面渲染

全部使用临时数据目录，不会改动正式的 stability.db。
"""
import sys, os, tempfile, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_ui_wf_')  # isolated DB
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'

from streamlit.testing.v1 import AppTest
import auth as AU
import db as DB

PASS, FAIL = [], []
APP = os.path.join(ROOT, "app.py")


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


def btn(at, label):
    return next(b for b in at.button if b.label == label)


def find_input(items, label):
    return next(x for x in items if x.label == label)


def select_option_containing(at, label, text):
    sb = next(x for x in at.selectbox if x.label == label and any(text in str(o) for o in x.options))
    sb.set_value(next(o for o in sb.options if text in str(o)))


def new_app(user=None):
    at = AppTest.from_file(APP, default_timeout=180)
    if user:
        at.session_state["user"] = user
    at.run()
    return at


AU.init_auth()
DB.init()
subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "seed_example.py")],
               capture_output=True, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
print("== 1. 登录页")
at = new_app()
check("未登录时显示登录表单", any(t.label == "用户名" for t in at.text_input))
find_input(at.text_input, "用户名").input("admin")
find_input(at.text_input, "密码").input("wrong-password")
btn(at, "登录").click().run()
check("错误口令提示登录失败", any("用户名或密码错误" in e.value for e in at.error))
check("错误口令不建立会话", not at.session_state["user"])
find_input(at.text_input, "用户名").input("admin")
find_input(at.text_input, "密码").input("Test-Admin#2026")
btn(at, "登录").click().run()
check("正确口令登录后进入系统", at.session_state["user"] and at.session_state["user"]["username"] == "admin")
check("登录后无异常", len(at.exception) == 0)

# ---------------------------------------------------------------------------
print("== 2. 角色与导航")
def nav_for(role):
    at = new_app({"username": f"u_{role}", "name": role, "role": role})
    return list(at.sidebar.radio[0].options), at
admin_nav, _ = nav_for("admin")
viewer_nav, _ = nav_for("viewer")
analyst_nav, _ = nav_for("analyst")
check("管理员可见“系统维护”“用户管理”“审计日志”", {"系统维护", "用户管理", "审计日志"} <= set(admin_nav))
check("只读访客看不到管理页面", not ({"系统维护", "用户管理", "审计日志"} & set(viewer_nav)))
check("分析员看不到系统维护", "系统维护" not in analyst_nav)

# ---------------------------------------------------------------------------
print("== 3. 研究创建 → 添加样品 → 录入检测值（端到端）")
at = new_app({"username": "admin", "name": "Admin", "role": "admin"})
at.sidebar.radio[0].set_value("研究管理").run()
find_input(at.text_input, "研究名称").input("UI工作流研究")
find_input(at.text_input, "药品通用名").input("测试药")
btn(at, "创建研究").click().run()
check("创建研究表单提交后无异常", len(at.exception) == 0)
names = [s["name"] for s in DB.list_studies()]
check("研究写入数据库", "UI工作流研究" in names)
sid = next(s["study_id"] for s in DB.list_studies() if s["name"] == "UI工作流研究")

at.run()
select_option_containing(at, "选择研究", "UI工作流研究")
at.run()
find_input(at.text_input, "批号").input("B-UI-001")
btn(at, "添加样品并生成计划").click().run()
check("添加样品后无异常", len(at.exception) == 0)
study = DB.load_study(sid)
check("样品写入数据库并生成取样计划", study and len(study["samples"]) == 1 and len(study["samples"][0]["time_points"]) > 0)

at.sidebar.radio[0].set_value("数据录入").run()
select_option_containing(at, "选择研究", "UI工作流研究")
at.run()
check("数据录入页无异常", len(at.exception) == 0)
n_before = sum(len(x["measurements"]) for x in DB.load_study(sid)["samples"])
btn(at, "保存检测值").click().run()
n_after = sum(len(x["measurements"]) for x in DB.load_study(sid)["samples"])
check(f"保存检测值写入数据库（{n_before} → {n_after}）", n_after >= n_before)
check("保存检测值后无异常", len(at.exception) == 0)

# ---------------------------------------------------------------------------
print("== 4. 教学示例一键加载")
at = new_app({"username": "admin", "name": "Admin", "role": "admin"})
at.sidebar.radio[0].set_value("研究管理").run()
n_before = len(DB.list_studies())
btn(at, "加载教学示例（单抗 DS + DP）").click().run()
check("教学示例加载后研究数增加", len(DB.list_studies()) > n_before)
check("教学示例加载后无异常", len(at.exception) == 0)

# ---------------------------------------------------------------------------
print("== 5. 全部页面在各角色下渲染无异常")
ROLES = [("admin", "admin"), ("manager", "manager"), ("analyst", "analyst"), ("viewer", "viewer")]
for role, label in ROLES:
    at = new_app({"username": f"u_{label}", "name": label, "role": role})
    pages = list(at.sidebar.radio[0].options)
    bad = []
    for p in pages:
        at.sidebar.radio[0].set_value(p).run()
        if at.exception:
            bad.append((p, at.exception[0].value[:120]))
    check(f"角色 {label}：{len(pages)} 个页面渲染无异常 (失败: {bad})", not bad)

# ---------------------------------------------------------------------------
print("== 6. 用户管理与改口令（界面）")
at = new_app({"username": "admin", "name": "Admin", "role": "admin"})
at.sidebar.radio[0].set_value("用户管理").run()
find_input(at.text_input, "新用户名").input("ui_new_analyst")
find_input(at.text_input, "初始密码").input("Init#Pass2026")
find_input(at.text_input, "姓名").input("界面新用户")
select_option_containing(at, "角色", "analyst")
btn(at, "创建用户").click().run()
check("界面创建用户后无异常", len(at.exception) == 0)
check("新用户写入数据库", any(u["username"] == "ui_new_analyst" for u in AU.list_users()))
u_ok, _ = AU.verify_password("ui_new_analyst", "Init#Pass2026")
check("新用户可用初始口令登录（后端校验）", u_ok is not None)

at = new_app({"username": "admin", "name": "Admin", "role": "admin"})
find_input(at.text_input, "当前密码").input("wrong-old-password")
find_input(at.text_input, "新密码(≥8位)").input("Admin#New2026")
btn(at, "更新密码").click().run()
check("旧口令错误时改密被拒绝", any("原" in e.value or "错误" in e.value or "不正确" in e.value or "失败" in e.value for e in at.error) or any("错误" in str(x.value) for x in at.error))
u_still, _ = AU.verify_password("admin", "Test-Admin#2026")
check("改密失败后原口令仍有效", u_still is not None)

at = new_app({"username": "admin", "name": "Admin", "role": "admin"})
find_input(at.text_input, "当前密码").input("Test-Admin#2026")
find_input(at.text_input, "新密码(≥8位)").input("Admin#New2026")
btn(at, "更新密码").click().run()
u_new, _ = AU.verify_password("admin", "Admin#New2026")
check("正确旧口令时改密成功（新口令可登录）", u_new is not None)
AU.change_password("admin", "Admin#New2026", "Test-Admin#2026")  # 还原，供后续测试使用

at.sidebar.radio[0].set_value("审计日志").run()
check("审计日志页无异常", len(at.exception) == 0)

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
