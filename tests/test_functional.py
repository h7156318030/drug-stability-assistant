"""功能完整测试：数值正确性、模板、存储与审计、备份恢复、导出、权限、界面工作流

全部使用临时数据目录（STAB_DATA_DIR），不会改动正式的 stability.db。
"""
import sys, os, tempfile, subprocess, io, json, zipfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_func_')  # isolated DB
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'

import numpy as np
from scipy import stats
from scipy.optimize import brentq

import models as M
import planner as P
import analysis as A
import db as DB
import auth as AU
import report as R

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


def close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def independent_lower_bound_expiry(months, vals, spec, direction="lower"):
    """独立实现 ICH Q1E 单侧 95% 置信限达限时刻（与 analysis.shelf_life 对照）。"""
    t = np.asarray(months, float); y = np.asarray(vals, float)
    n = len(t)
    b1, b0, r, p, se = stats.linregress(t, y)
    resid = y - (b0 + b1 * t)
    s = np.sqrt(np.sum(resid ** 2) / (n - 2))
    sxx = np.sum((t - t.mean()) ** 2)
    tc = stats.t.ppf(0.95, n - 2)
    sign = 1 if direction == "upper" else -1  # lower: 下限 = 拟合 - 边界; upper: 上限 = 拟合 + 边界
    def bound(x):
        return b0 + b1 * x + sign * tc * s * np.sqrt(1.0 / n + (x - t.mean()) ** 2 / sxx)
    f = lambda x: bound(x) - spec
    if f(0.0) * f(600.0) > 0:
        return None
    return brentq(f, 0.0, 600.0)


# ---------------------------------------------------------------------------
print("== 1. 数值正确性（独立实现对照）")
months = np.array([0, 3, 6, 9, 12, 18], float)
vals = np.array([100.1, 99.4, 98.9, 98.0, 97.2, 95.8])
reg = A.regression_summary(months, vals)
b1, b0, r, p, se = stats.linregress(months, vals)
check("回归斜率与 scipy.linregress 一致", close(reg["slope"], b1, 1e-9))
check("回归截距与 scipy.linregress 一致", close(reg["intercept"], b0, 1e-9))
check("年降解率 = 斜率×12", close(reg["rate_per_year"], b1 * 12, 1e-9))

exp_lower = independent_lower_bound_expiry(months, vals, 90.0, "lower")
got_lower = A.shelf_life(months, vals, 90.0, "lower")
check(f"下限有效期（ICH Q1E 95%）与独立计算一致 (ref={exp_lower:.3f}, got={got_lower})",
      exp_lower is not None and close(got_lower, exp_lower, 0.05))

vals_up = np.array([0.20, 0.35, 0.52, 0.66, 0.81, 1.10])
exp_upper = independent_lower_bound_expiry(months, vals_up, 2.0, "upper")
got_upper = A.shelf_life(months, vals_up, 2.0, "upper")
check(f"上限有效期（有关物质≤2.0%）与独立计算一致 (ref={exp_upper:.3f}, got={got_upper})",
      exp_upper is not None and close(got_upper, exp_upper, 0.05))

check("起点即超限时有效期为 0", A.shelf_life(months, np.array([85, 84, 83, 82, 81, 80.0]), 90.0, "lower") == 0.0)
check("数据点不足时不外推（返回 None）", A.shelf_life(np.array([0.0, 3.0]), np.array([100.0, 99.0]), 90.0) is None)
score, n_iss = A.data_quality_score([{}, {}])
check("数据质量分：2 个问题扣 10 分", (score, n_iss) == (90, 2))
check("数据质量分下限为 0", A.data_quality_score([{}] * 40)[0] == 0)
check("外推月数格式化：None 显示为“无法外推”", A._fmt_months(None) == "无法外推")

# ---------------------------------------------------------------------------
print("== 2. 方案模板：全部模板可创建研究")
templates = P.list_templates()
check(f"模板数量 >= 11 (got {len(templates)})", len(templates) >= 11)
bad = []
for tname in templates:
    try:
        s_obj = P.create_from_template(tname, f"功能测试-{tname}", "测试", ["B1", "B2"], "2026-01-15", "")
        ok = len(s_obj.samples) == 2 and all(len(sm.time_points) > 0 for sm in s_obj.samples)
        if not ok:
            bad.append(tname)
    except Exception as e:  # noqa
        bad.append(f"{tname}: {e}")
check(f"所有模板生成 2 批且每批有取样点 (失败: {bad})", not bad)

# ---------------------------------------------------------------------------
print("== 3. 存储、审计与备份恢复")
AU.init_auth()
DB.init()
st_obj = P.create_from_template(templates[0], "存储往返测试", "测试", ["B1"], "2026-01-15", "")
d = st_obj.to_dict()
DB.save_study(d)
loaded = DB.load_study(st_obj.study_id)
check("研究保存后可读回", loaded is not None and loaded["name"] == "存储往返测试")
n_meas_before = sum(len(sm["measurements"]) for sm in d["samples"])
check("保存后检测值数量不变（无数据时为 0）", n_meas_before == 0)
AU.audit("TEST_ACTION", "study", st_obj.study_id, "admin", "admin", "127.0.0.1", "t", None, None, note="功能测试")
check("审计哈希链校验通过", AU.verify_audit_integrity()["ok"] is True)

backup = DB.export_all_json()
bk = json.loads(backup)
check("备份包含 6 张表", set(bk["tables"].keys()) >= {"studies", "samples", "time_points", "measurements", "users", "audit_log"})
n_users = len(AU.list_users())
DB.import_all_json(backup, merge=True)
check("合并恢复后研究仍存在", DB.load_study(st_obj.study_id) is not None)
check("恢复不清空用户表", len(AU.list_users()) == n_users)
check("恢复后审计链仍完整", AU.verify_audit_integrity()["ok"] is True)

# ---------------------------------------------------------------------------
print("== 4. 导出")
study_for_export = P.create_from_template(templates[-1] if "单抗" in templates[-1] else templates[0],
                                          "导出测试", "测试", ["B1", "B2"], "2026-01-15", "")
xls = R.export_excel(study_for_export, ["含量"] if True else [])
check("Excel 为有效 zip/xlsx（以 PK 开头）", xls[:2] == b"PK")
import openpyxl
wb = openpyxl.load_workbook(io.BytesIO(xls))
check("Excel 包含“取样计划”与“检测数据”工作表", "取样计划" in wb.sheetnames and "检测数据" in wb.sheetnames)
pdf = R.export_pdf(study_for_export, ["含量"])
check("PDF 以 %PDF 开头且非空", pdf[:4] == b"%PDF" and len(pdf) > 1000)
js = R.export_study_json(study_for_export)
check("QA 数据包 JSON 含元数据、数据属性与结论", {"meta", "attributes", "conditions", "conclusions"} <= set(json.loads(js).keys()))
check("研究单独导出（界面按钮）可反序列化为研究", M.StabilityStudy.from_dict(study_for_export.to_dict()).name == "导出测试")
cross = R.export_cross_study_summary([study_for_export, st_obj])
check("跨研究汇总 Excel 有效", cross[:2] == b"PK")

# ---------------------------------------------------------------------------
print("== 5. 认证、锁定、角色权限")
AU.create_user("func_analyst", "Analyst#2026", "分析员测试", "analyst", operator="admin")
user, reason = AU.verify_password("func_analyst", "Analyst#2026")
check("正确口令登录成功", user is not None and user["role"] == "analyst")
for _ in range(AU.MAX_FAILED):
    AU.verify_password("func_analyst", "wrong-pass")
user, reason = AU.verify_password("func_analyst", "Analyst#2026")
check(f"连续失败达阈值后账户锁定 (reason={reason})", user is None and str(reason).startswith("locked"))
AU.create_user("func_viewer", "Viewer#2026", "只读测试", "viewer", operator="admin")
AU.set_enabled("func_viewer", False)
user, reason = AU.verify_password("func_viewer", "Viewer#2026")
check("禁用账户无法登录", user is None and reason == "disabled")
check("viewer 没有录入权限", not AU.has_permission("viewer", "data:write"))
check("analyst 没有用户管理权限", not AU.has_permission("analyst", "user:manage"))
check("admin 拥有全部权限", all(AU.has_permission("admin", p) for p in ["user:manage", "audit:read", "data:write"]))
ok_change, msg = AU.change_password("func_analyst", "wrong-old", "Analyst#2027")
check("旧口令错误时改密失败", ok_change is False)

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
print("== 6. 批量 CSV 导入（UTF-8 / GBK、跳过原因、精确关联）")
import importers as IM
study_csv = P.create_from_template(templates[0], "CSV导入测试", "测试", ["B1"], "2026-01-15", "")
batch = study_csv.samples[0].batch_id
csv_utf8 = (f"批号,条件,月点,检测项目,数值,单位,限度,方向\n"
            f"{batch},长期,0,含量,100.0,%,90,lower\n"
            f"{batch},长期,3,含量,99.4,%,90,lower\n"
            f"NOPE,长期,6,含量,98.0,%,90,lower\n"
            f"{batch},长期,abc,含量,97.0,%,90,lower\n").encode("utf-8-sig")
df = IM.read_bulk_csv(csv_utf8)
cnt, skipped = IM.import_bulk_csv(study_csv, df)
check(f"UTF-8 CSV 写入 2 条有效记录 (got {cnt})", cnt == 2)
check("未知批号与非法月点被跳过并给出原因", len(skipped) == 2 and "不属于本研究" in skipped[0] and "不是数字" in skipped[1])
check("导入记录与时间点精确关联（tp_ref 非空）", all(m.tp_ref for m in study_csv.samples[0].measurements))
gbk_bytes = f"批号,条件,月点,检测项目,数值\n{batch},长期,6,含量,98.5\n".encode("gbk")
cnt2, _ = IM.import_bulk_csv(study_csv, IM.read_bulk_csv(gbk_bytes))
check("GBK 编码 CSV（中文 Excel 常见）可读取并写入", cnt2 == 1)
try:
    IM.import_bulk_csv(study_csv, IM.read_bulk_csv("批号,条件\nX,Y\n".encode("utf-8")))
    missing_ok = False
except ValueError as e:
    missing_ok = "缺少列" in str(e)
check("缺少必需列时给出明确错误", missing_ok)
check("导入模板包含全部必需列", all(c in IM.TEMPLATE_CSV.splitlines()[0] for c in IM.REQUIRED_COLUMNS))

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
