"""第3轮：Streamlit应用集成测试（函数级+页面分支逻辑）"""
import sys, os, tempfile, json
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
import streamlit as st
# 在 import app 前模拟已登录（避免模块级 login_page+st.stop 在 bare 模式崩溃）
st.session_state.user = {"username": "admin", "role": "admin", "name": "Admin"}
import app as APP

ok = []
fail = []
def check(name, cond):
    (ok if cond else fail).append(name)

# 1. app 导入成功（装饰器/全局函数都在）
check('T3 app导入', APP is not None)

# 2. dashboard_aggregate 缓存函数可调用
DB.save_study(M.StabilityStudy('D1', 'x', '化学药', '25', '全检', biologic=False).to_dict())
agg = APP.dashboard_aggregate('testuser')
check('T3 dashboard_aggregate返回字段', 'n_study' in agg and agg['n_study'] >= 1)

# 3. ATTRIBUTE_OPTIONS 存在且非空
check('T3 ATTRIBUTE_OPTIONS', len(APP.ATTRIBUTE_OPTIONS) > 0)

# 4. load_study_obj 缓存
s = M.StabilityStudy('D2', 'y', '生物制品', '2-8', '全检', biologic=True, molecule_type='单抗')
P.add_sample_with_plan(s, 'B1', 'vial', '100', ['冷藏'], molecule_type='单抗')
DB.save_study(s.to_dict())
sobj = APP.load_study_obj(s.study_id)
check('T3 load_study_obj缓存', sobj is not None and sobj.biologic is True)

# 5. TIME_POINT_PRESETS 预设可用（planner）
check('T3 时间点预设', '标准(0/3/6/9/12/18/24月)' in P.TIME_POINT_PRESETS)

# 6. 教学QUIZ题有答案字段
for i, q in enumerate(T.QUIZ):
    check(f'T3 QUIZ[{i}]有答案', 'answer' in q and q['answer'])

# 7. 验证 _series_for 在混合条件(撞月)下的精确配对
s3 = M.StabilityStudy('D3', 'z', '生物制品', '2-8', '全检', biologic=True, molecule_type='单抗')
P.add_sample_with_plan(s3, 'B1', 'vial', '100', ['冷藏', '强制降解'], molecule_type='单抗')
sm = s3.samples[0]
for tp in sm.time_points:
    if tp.condition == '冷藏':
        sm.measurements.append(M.Measurement(tp.month, '效价', 100.0 - tp.month, 'rel%',
                                             80.0, False, '', '效价', 'lower', tp_ref=tp.tp_id))
DB.save_study(s3.to_dict())
s3l = M.StabilityStudy.from_dict(DB.load_study(s3.study_id))
# 强制降解应无数据
m_fd, v_fd, _ = A._series_for(s3l.samples[0], '效价', '强制降解')
check('T3 强制降解无撞月(精确配对)', len(v_fd) == 0)
m_c, v_c, _ = A._series_for(s3l.samples[0], '效价', '冷藏')
check('T3 冷藏精确配对8点', len(v_c) == 8)

# 8. persist 函数存在（app.py 保存入口）
check('T3 persist函数', callable(getattr(APP, 'persist', None)))

# 9. 验证 expiry_extrapolation 数据结构
sl = A.shelf_life([0,3,6,9,12], [100,97,94,91,88], 90.0, 'lower')
check('T3 有效期计算', sl is not None and sl > 0)

# 10. 验证多模型对比 fit_best_model 返回 predictions
fm = A.fit_best_model(s3l, '效价', '冷藏')
check('T3 fit_best_model多模型', fm and 'predictions' in fm and fm['best_model'])

print(f"PASS={len(ok)} FAIL={len(fail)}")
for f in fail:
    print("FAIL:", f)
if fail:
    raise SystemExit(1)
