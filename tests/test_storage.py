"""第2轮：端到端数据流测试（存储层+模板+导出）"""
import sys, os, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_test_')  # isolated DB; never touch the live stability.db
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'  # test-only initial password


# 用独立测试数据库目录
TEST_DIR = tempfile.mkdtemp(prefix='stab_test_')

import models as M
import db as DB
DB.init()  # create tables in the isolated test database
import analysis as A
import report as R
import planner as P
import teaching as T

ok = []
fail = []
def check(name, cond):
    (ok if cond else fail).append(name)

# 1. 创建研究并存库
s = M.StabilityStudy('E2E', '单抗', '生物制品', '2-8°C', '全检', biologic=True, molecule_type='单抗')
P.add_sample_with_plan(s, 'B1', 'vial', '100mg', ['冷藏', '强制降解'], molecule_type='单抗')
check('E2E样品已加(含2条件)', len(s.samples) == 1 and len(s.samples[0].time_points) > 0)
DB.save_study(s.to_dict())
check('E2E存库成功', DB.load_study(s.study_id) is not None)

# 2. 加载并验证完整性
s2 = M.StabilityStudy.from_dict(DB.load_study(s.study_id))
check('E2E加载后批号一致', s2.samples[0].batch_id == 'B1')
check('E2E时间点保留', len(s2.samples[0].time_points) == len(s.samples[0].time_points))
check('E2E生物制品标记', s2.biologic is True)

# 3. 录入测量值（模拟UI：tp.month作为time_point_id, tp_ref精确配对）
sm = s2.samples[0]
cnt = 0
for tp in sm.time_points:
    if tp.condition == '冷藏':
        val = 100.0 - 1.0 * tp.month
        sm.measurements.append(M.Measurement(tp.month, '效价', round(val,2), '相对标示量%',
                                             80.0, False, '', '效价', 'lower', tp_ref=tp.tp_id))
        cnt += 1
check('E2E冷藏测量值录入', cnt > 0)
DB.save_study(s2.to_dict())

# 4. 加载后分析（验证tp_ref配对）
s3 = M.StabilityStudy.from_dict(DB.load_study(s2.study_id))
print('  DEBUG s3 tp_ids=', [tp.tp_id for tp in s3.samples[0].time_points][:3])
print('  DEBUG s3 meas tp_ref=', [m.tp_ref for m in s3.samples[0].measurements][:3])
print('  DEBUG s3 n_meas=', len(s3.samples[0].measurements))
for m in s3.samples[0].measurements[:12]:
    print('    meas tpid=', repr(m.time_point_id), 'attr=', m.attribute)
months, vals, tps = A._series_for(s3.samples[0], '效价', '冷藏')
print('  DEBUG cnt=', cnt, 'loaded vals=', len(vals), 'months=', list(months))
print('  DEBUG s3 meas[0]=', s3.samples[0].measurements[0].__dict__)
sc3 = A.biologic_significant_change(s3, '效价', '冷藏')
print('  DEBUG sc3=', sc3)
for c in set(tp.condition for tp in s3.samples[0].time_points):
    mm, vv, _ = A._series_for(s3.samples[0], '效价', c)
    print('  DEBUG cond', c, 'nvals', len(vv))
    scc = A.biologic_significant_change(s3, '效价', c)
    print('  DEBUG sc', c, '=', scc)
check('E2E加载后_系列提取', len(vals) == cnt and len(months) == cnt)
reg = A.regression_summary(months, vals)
check('E2E回归斜率≈-1', abs(reg['slope'] - (-1.0)) < 0.01)

# 5. 跨研究汇总导出(Excel)
studies = DB.list_studies()
check('E2E全库至少1研究', len(studies) >= 1)
# 构造第二个研究用于跨研究
s4 = M.StabilityStudy('E2E2', '化药', '化学药', '25°C', '全检', biologic=False)
P.add_sample_with_plan(s4, 'C1', '铝塑', '10mg', ['长期'])
DB.save_study(s4.to_dict())
studies = DB.list_studies()
objs = [M.StabilityStudy.from_dict(DB.load_study(s['study_id'])) for s in studies]
try:
    xlsx_path = os.path.join(TEST_DIR, 'x.xlsx')
    R.export_cross_study_summary(objs, xlsx_path)
    check('E2E跨研究Excel导出', os.path.exists(xlsx_path))
except Exception as e:
    import traceback
    check('E2E跨研究Excel导出', False)
    print('  export err:', e)
    traceback.print_exc()

# 6. 教学quiz存在
check('E2E教学QUIZ≥5题', len(T.QUIZ) >= 5)

# 7. 时间点预设
check('E2E时间点预设≥5套', len(P.TIME_POINT_PRESETS) >= 5)

# 输出
print(f"PASS={len(ok)} FAIL={len(fail)}")
for f in fail:
    print("FAIL:", f)
if fail:
    raise SystemExit(1)
