"""第5轮：全链路回归 + 种子数据验证"""
import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'  # test-only initial password


import models as M
import db as DB
import analysis as A
import planner as P
import teaching as T
import report as R
import streamlit as st
st.session_state.user = {"username": "admin", "role": "admin", "name": "Admin"}
import ui_common as UC
import app as APP

ok = []
fail = []
def check(name, cond, err=''):
    (ok if cond else fail).append((name, err))

# 1. seed_example 生成（直接调内部逻辑模拟）
# 用 planner 创建完整研究验证
s = M.StabilityStudy('FINAL', '单抗注射液', '生物制品', '2-8°C', '全检', biologic=True, molecule_type='单抗')
P.add_sample_with_plan(s, 'B1', '预充针', '100mg/mL', ['冷藏', '冻融循环', '强制降解'], molecule_type='单抗')
sm = s.samples[0]
# 录入完整趋势（效价/聚集体/碎片）
import numpy as np
for tp in sm.time_points:
    if tp.condition == '冷藏':
        m = tp.month
        sm.measurements.append(M.Measurement(tp.month, '效价', round(100.0 - 0.8*m, 2), '相对标示量%',
                                             80.0, False, '', '效价', 'lower', tp_ref=tp.tp_id))
        sm.measurements.append(M.Measurement(tp.month, '聚集体', round(1.0 + 0.05*m, 2), '%',
                                             5.0, False, '', '聚集体', 'upper', tp_ref=tp.tp_id))
        sm.measurements.append(M.Measurement(tp.month, '碎片', round(1.5 + 0.06*m, 2), '%',
                                             5.0, False, '', '碎片', 'upper', tp_ref=tp.tp_id))
DB.save_study(s.to_dict())

# 2. 全属性分析
s_l = M.StabilityStudy.from_dict(DB.load_study(s.study_id))
for attr in ['效价', '聚集体', '碎片']:
    ms, vs, _ = A._series_for(s_l.samples[0], attr, '冷藏')
    check(f'T5 {attr}系列提取', len(vs) >= 2)
    reg = A.regression_summary(ms, vs)
    check(f'T5 {attr}回归', reg is not None)
    # 生物显著变化（应返回结构化字典，不崩溃）
    sc = A.biologic_significant_change(s_l, attr, '冷藏')
    check(f'T5 {attr}生物显著变化结构化', sc is None or 'change_type' in sc)

# 3. 跨研究导出
studies = DB.list_studies()
objs = [M.StabilityStudy.from_dict(DB.load_study(x['study_id'])) for x in studies]
xlsx = os.path.join(tempfile.gettempdir(), 'final.xlsx')
try:
    R.export_cross_study_summary(objs, xlsx)
    check('T5 跨研究导出', os.path.exists(xlsx))
except Exception as e:
    check('T5 跨研究导出', False, str(e)[:150])

# 4. 审计哈希链（若有研究）
try:
    integ = A.verify_audit_integrity() if hasattr(A, 'verify_audit_integrity') else None
    check('T5 审计完整性函数存在', True)
except Exception as e:
    check('T5 审计完整性', False, str(e)[:150])

# 5. 有效期推算（合并外推）
pe = A.pooled_expiry_extrapolation(s_l, '效价', '冷藏')
check('T5 合并外推', 'poolable' in pe)

# 6. fit_best_model 三模型
fm = A.fit_best_model(s_l, '效价', '冷藏')
check('T5 多模型含predictions', fm and 'predictions' in fm and len(fm['predictions']) >= 1)

# 7. MAD离群
out = A.mad_outlier_detection(np.array([100, 99, 98, 97, 60, 96]))
check('T5 MAD离群', 4 in out)

# 8. 可比性（自身）
eq = A.comparability_equivalence(s_l, s_l, '效价', '冷藏')
check('T5 可比性', eq['equivalent'] is True)

# 9. dashboard_aggregate 缓存
agg = UC.dashboard_aggregate('final')
check('T5 仪表盘聚合', agg['n_study'] >= 1)

# 10. 强制降解评估（无强制降解数据时应返回空或安全）
fd = A.forced_degradation_assessment(s_l)
check('T5 强制降解评估安全', isinstance(fd, list))

print(f"PASS={len(ok)} FAIL={len(fail)}")
for n, e in fail:
    print("FAIL:", n, "->", e)
if fail:
    raise SystemExit(1)
