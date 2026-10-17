"""
安全与数据完整性自查脚本（self-check），覆盖 V2.3 修复的漏洞与关键边界。
运行：python tests/test_security_selfcheck.py
（本脚本通过 AppTest / 单元测试验证，不依赖裸 import app）
"""
import os, sys, json, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'  # test-only initial password

PASS, FAIL = [], []

def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)

# ---------------------------------------------------------------------------
# 2. db 层：删除研究无孤儿数据 + 外键生效
# ---------------------------------------------------------------------------
print("== 2. db 删除级联 / 无孤儿 ==")
import db as DB
DB.init()
import auth as _AU0
_AU0.init_auth()  # create users/audit tables in the isolated test database
sid = "SELFCHECK_%s" % os.urandom(3).hex()
DB.save_study({
    "study_id": sid, "name": "自查研究", "study_type": "长期", "drug_name": "X",
    "sponsor": "", "design": "FULL", "biologic": 0, "molecule_type": "", "stage": "",
    "samples": [{
        "sample_id": "s1", "batch_id": "B1", "packaging": "瓶", "strength": "10mg", "molecule_type": "",
        "time_points": [{"tp_id": "t1", "month": 0, "planned_date": "2026-01-01",
                         "condition": "长期", "status": "done", "pulled": 0}],
        "measurements": [{"time_point_id": 0, "tp_ref": "t1", "attribute": "含量", "value": 99.0,
                          "unit": "%", "limit_spec": 90.0, "is_limit": False, "note": "",
                          "cqa_category": "", "direction": "lower", "resolution": None, "peak_purity": None}],
    }],
})
DB.delete_study(sid)
conn = DB.get_conn(); cur = conn.cursor()
n_studies = cur.execute("SELECT COUNT(*) FROM studies WHERE study_id=?", (sid,)).fetchone()[0]
n_samples = cur.execute("SELECT COUNT(*) FROM samples WHERE study_id=?", (sid,)).fetchone()[0]
n_tp = cur.execute("SELECT COUNT(*) FROM time_points WHERE sample_id='s1'").fetchone()[0]
n_meas = cur.execute("SELECT COUNT(*) FROM measurements WHERE sample_id='s1'").fetchone()[0]
cur.close(); conn.close()
check("删除后 studies 为 0", n_studies == 0)
check("删除后 samples 为 0 (无孤儿)", n_samples == 0)
check("删除后 time_points 为 0 (无孤儿)", n_tp == 0)
check("删除后 measurements 为 0 (无孤儿)", n_meas == 0)

# ---------------------------------------------------------------------------
# 3. import_all_json 保留 audit_log / users（合规）
# ---------------------------------------------------------------------------
print("\n== 3. 备份恢复不破坏审计/账号 ==")
before = json.loads(DB.export_all_json())
audit_before = len(before["tables"].get("audit_log", []))
conn = DB.get_conn(); cur = conn.cursor()
import uuid
cur.execute("INSERT INTO audit_log (log_id, ts, username, action, object_type, note) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), "2026-01-01T00:00:00", "selfcheck", "TEST", "x", "must-survive"))
conn.commit(); cur.close()
snap = DB.export_all_json()
DB.import_all_json(snap, merge=False)
after = json.loads(DB.export_all_json())
audit_after = after["tables"].get("audit_log", [])
check("恢复后 audit_log 未被清空 (含恢复记录)", len(audit_after) >= audit_before + 1)
check("恢复后 测试审计记录仍存在", any(r.get("note") == "must-survive" for r in audit_after))
check("恢复后 users 表存在", "users" in after["tables"] and len(after["tables"]["users"]) >= 1)
conn = DB.get_conn(); cur = conn.cursor()
cur.execute("DELETE FROM audit_log WHERE note='must-survive'"); conn.commit(); cur.close()

# ---------------------------------------------------------------------------
# 4. analysis.shelf_life 起点超标 → 0
# ---------------------------------------------------------------------------
print("\n== 4. shelf_life 边界 ==")
import numpy as np
import analysis as A
months = np.array([0.0, 3.0, 6.0])
sl = A.shelf_life(months, np.array([88.0, 87.0, 86.0]), 90.0, "lower")
check("起点超标返回 0.0", sl == 0.0)
sl2 = A.shelf_life(months, np.array([99.0, 97.0, 95.0]), 90.0, "lower")
check("正常降级给出正有效期", sl2 is not None and sl2 > 0)
sl3 = A.shelf_life(months, np.array([99.0, 99.1, 99.0]), 90.0, "lower")
check("无降级返回观测末期", abs(sl3 - 6.0) < 1e-6)

# ---------------------------------------------------------------------------
# 5. auth：锁定态 datetime 不崩溃 + 改密不锁定
# ---------------------------------------------------------------------------
print("\n== 5. 认证健壮性 ==")
import datetime as _dt
import auth as AU
AU.init_auth()
conn = AU._conn()[0]; cur = conn.cursor()
cur.execute("UPDATE users SET locked_until=? WHERE username='admin'",
            ((_dt.datetime.now() + _dt.timedelta(minutes=10)).isoformat(timespec="seconds"),))
conn.commit(); cur.close()
try:
    u, reason = AU.verify_password("admin", "wrongpass")
    check("锁定态 verify_password 不崩溃", reason is not None and reason.startswith("locked"))
except Exception as e:
    check("锁定态 verify_password 不崩溃 (%s)" % e, False)
conn = AU._conn()[0]; cur = conn.cursor()
cur.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE username='admin'")
conn.commit(); cur.close()
for _ in range(6):
    AU.verify_password("admin", "definitely_wrong")
conn = AU._conn()[0]; cur = conn.cursor()
cnt = cur.execute("SELECT failed_attempts FROM users WHERE username='admin'").fetchone()[0]
conn.close()
check("错误登录累计失败计数 (锁定逻辑生效)", cnt >= 5)
conn = AU._conn()[0]; cur = conn.cursor()
cur.execute("UPDATE users SET locked_until=NULL, failed_attempts=0 WHERE username='admin'")
conn.commit(); cur.close()
ok, msg = AU.change_password("admin", "Test-Admin#2026", "Test-Admin#2026-new")
check("change_password 成功", ok is True)
conn = AU._conn()[0]; cur = conn.cursor()
cnt2 = cur.execute("SELECT failed_attempts FROM users WHERE username='admin'").fetchone()[0]
conn.close()
check("change_password 未累计失败计数", cnt2 == 0)
AU.change_password("admin", "Test-Admin#2026-new", "Test-Admin#2026")

# ---------------------------------------------------------------------------
# 1 & 6. AppTest 验证 np/stats 注入（避免裸 import 触发未登录态模块级崩溃）
# ---------------------------------------------------------------------------
print("\n== 1&6. 验证 np/stats 注入 app 模块 ==")
import re
with open(os.path.join(ROOT, "app.py"), "r", encoding="utf-8") as f:
    src = f.read()
check("app.py 含 'import numpy as np'", "import numpy as np" in src)
check("app.py 含 'import scipy.stats as stats'", "import scipy.stats as stats" in src)
# 确认分析函数中使用的 np./stats. 引用在源码中存在（已被导入覆盖）
check("源码使用 np. 调用", bool(re.search(r"\bnp\.[a-zA-Z]", src)))
check("源码使用 stats. 调用", bool(re.search(r"\bstats\.[a-zA-Z]", src)))
# AppTest 加载模块无异常（验证模块可正常 import）
from streamlit.testing.v1 import AppTest
at = AppTest.from_file(os.path.join(ROOT, "app.py"))
at.run(timeout=30)
excs = list(at.exception)
check("AppTest 加载 app 模块无异常", len(excs) == 0)

print("\n通过 %d / 失败 %d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：", FAIL)
    sys.exit(1)
print("全部通过")
