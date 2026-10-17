"""第1轮：核心分析函数单元测试"""
import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'  # test-only initial password

import models as M
import analysis as A
import numpy as np
from scipy import stats

ok = []
fail = []

def check(name, cond):
    (ok if cond else fail).append(name)

# ---- 构造化药研究：3批长期效价下降 ----
def make_chem():
    s = M.StabilityStudy('ST1', '化药片', '化学药', '25°C', '全检', biologic=False)
    months = [0, 3, 6, 9, 12]
    for b in ['B1', 'B2', 'B3']:
        sm = M.Sample(b, '铝塑', '10mg')
        tps = [M.TimePoint(m, '', '长期') for m in months]
        sm.time_points = tps
        sm.measurements = []
        base = 100.0
        for m, tp in zip(months, tps):
            val = base - 1.5 * m  # 每月降1.5%
            sm.measurements.append(
                M.Measurement(m, '效价', round(val, 2), limit_spec=90.0, direction='lower', tp_ref=tp.tp_id))
        s.samples.append(sm)
    return s

# ---- 构造生物制品：效价下降(生物阈值10%) ----
def make_bio():
    s = M.StabilityStudy('ST2', '单抗液', '生物制品', '2-8°C', '全检', biologic=True, molecule_type='单抗')
    months = [0, 3, 6, 9, 12]
    sm = M.Sample('BIO1', '预充针', '100mg/mL')
    tps = [M.TimePoint(m, '', '冷藏') for m in months]
    sm.time_points = tps
    sm.measurements = [
        M.Measurement(m, '效价', round(100.0 - 8.0 * (m/12), 2), limit_spec=80.0, direction='lower', tp_ref=tp.tp_id)
        for m, tp in zip(months, tps)]
    s.samples.append(sm)
    return s

# 测试1：回归
s = make_chem()
months, vals, _ = A._series_for(s.samples[0], '效价', '长期')
reg = A.regression_summary(months, vals)
check('R1回归斜率≈-1.5', abs(reg['slope'] - (-1.5)) < 1e-6)
check('R1回归R2=1', reg['r2'] > 0.999)

# 测试2：有效期
sl = A.shelf_life(months, vals, 90.0, 'lower')
# 100-1.5t=90 -> t=6.67
check('R2有效期≈6.67月', sl is not None and abs(sl - 6.67) < 0.2)

# 测试3：批间合并
pr = A.pooled_regression(s, '效价', '长期')
check('R3批间合并n_batches=3', pr['n_batches'] == 3)

# 测试4：显著变化(化药5%)
sc = A.significant_change_assessment(s, '效价', '长期')
check('R4化药显著变化(>5%)', sc is not None and sc['change_pct'] > 5.0)

# 测试5：生物显著变化(10%)——构造下降>10%触发
b = make_bio()
# 覆写测量值：12月降15% (>10%阈值)
for m in b.samples[0].measurements:
    if m.time_point_id == 12:
        m.value = 85.0  # 相对0月下降15%
    elif m.time_point_id == 9:
        m.value = 88.0
bio_sc = A.biologic_significant_change(b, '效价', '冷藏')
check('R5生物显著变化change_type字段', bio_sc is not None and 'change_type' in bio_sc)
# 反向验证：未达阈值应返回 none 类型而非 None
b2 = make_bio()
bio_none = A.biologic_significant_change(b2, '效价', '冷藏')
check('R5b未达阈值返回change_type=none', bio_none is not None and bio_none['change_type'] == '无显著变化(none)')

# 测试6：批间合并外推
pe = A.pooled_expiry_extrapolation(b, '效价', '冷藏')
check('R6合并外推返回poolable', 'poolable' in pe)

# 测试7：LOO稳健性
loo = A.leave_one_out_expiry(s, '效价', '长期', 90.0, 'lower')
check('R7LOO返回full_estimate', loo is not None and 'full_estimate' in loo)

# 测试8：MAD离群
vals8 = np.array([100, 98, 97, 96, 50, 95])  # 50是离群
out = A.mad_outlier_detection(vals8)
check('R8MAD检出离群', 4 in out)

# 测试9：拟合最优模型
fm = A.fit_best_model(s, '效价', '长期', 90.0, 'lower')
check('R9fit_best_model最优', fm is not None and 'best_model' in fm)

# 测试10：可比性(同研究自身应等效)
eq = A.comparability_equivalence(s, s, '效价', '长期')
check('R10可比性同研究完全等效', eq['equivalent'] is True)

# 输出
print(f"PASS={len(ok)} FAIL={len(fail)}")
for f in fail:
    print("FAIL:", f)
if fail:
    raise SystemExit(1)
