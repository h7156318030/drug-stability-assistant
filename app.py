"""
药品稳定性研究管理与分析系统 —— Streamlit 应用入口（含登录鉴权 + 审计）

运行：
    pip install -r requirements.txt
    python tools/seed_example.py      # 可选：示例数据
    streamlit run app.py
访问： http://localhost:8501

多用户 / 权限 / 21 CFR Part 11：
    - 首次启动自动创建管理员 admin；口令取自环境变量 STAB_ADMIN_PASSWORD，
      未设置时在控制台输出一次性随机口令（登录后请立即修改）
    - 数据目录：环境变量 STAB_DATA_DIR（默认项目根目录，即 stability.db 所在处）
    - 后端可切换 PostgreSQL：设置环境变量 DATABASE_URL=postgresql://...
    - 所有写操作记录不可篡改审计日志（操作人/时间/IP/前后值）
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime
from typing import Dict, List, Optional

import numpy as np
import scipy.stats as stats

import models as M
import planner as P
import analysis as A
import db as DB
import report as R
import fonts as F
import auth as AU
import ui_theme as UI
import importers as IM

UI.setup_page()   # 必须是第一个 Streamlit 调用
UI.inject_css()

F.setup_chinese_font()
DB.init()
AU.init_auth()

CHEM_CONDITIONS = ["长期", "加速", "中间", "光照"]
BIO_CONDITIONS = ["冷藏", "冷冻-20", "冷冻-80"]
ALL_CONDITIONS = CHEM_CONDITIONS + BIO_CONDITIONS
ATTRIBUTE_OPTIONS = [a.value for a in M.TestAttribute]
BIO_CQA_ATTRS = list(M.BIO_CQA_DIRECTION.keys())
MOLECULE_OPTIONS = [m.value for m in M.MoleculeType]


@st.cache_data(ttl=60, show_spinner=False)
def load_study_obj(study_id: str) -> M.StabilityStudy:
    return M.StabilityStudy.from_dict(DB.load_study(study_id))


@st.cache_data(ttl=120, show_spinner=False)
def dashboard_aggregate(username: str) -> Dict:
    """R49：仪表盘指标聚合（缓存，避免每次刷新全库重算）。"""
    studies = DB.list_studies()
    n_study = len(studies)
    n_sample = 0
    n_meas = 0
    bio = 0
    bio_sig_n = 0
    for s in studies:
        st_obj = load_study_obj(s["study_id"])
        n_sample += len(st_obj.samples)
        for sm in st_obj.samples:
            n_meas += len(sm.measurements)
        if st_obj.biologic:
            bio += 1
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    for attr in {m.attribute for m in sm.measurements}:
                        sc = A.biologic_significant_change(st_obj, attr, cond)
                        if sc and sc.get("is_significant"):
                            bio_sig_n += 1
    return {"n_study": n_study, "n_sample": n_sample, "n_meas": n_meas,
            "bio": bio, "bio_sig_n": bio_sig_n}


def render_interactive_trend(study: M.StabilityStudy, attr: str, limit_spec=None, direction=""):
    """交互式降解趋势图（plotly）：多批叠加 + 回归线 + 限度线 + 95%置信带。"""
    fig = go.Figure()
    xs_grid = []
    for s in study.samples:
        for cond in set(tp.condition for tp in s.time_points):
            months, vals, _ = A._series_for(s, attr, cond)
            if len(vals) >= 1:
                fig.add_trace(go.Scatter(
                    x=months, y=vals, mode="markers+lines", name=f"{s.batch_id}-{cond}",
                    hovertemplate=f"{s.batch_id}-{cond}<br>月=%{{x}}<br>{attr}=%{{y}}<extra></extra>"))
                reg = A.regression_summary(months, vals)
                if reg and reg["n"] >= 2:
                    xr = [float(months.min()), float(months.max())]
                    yr = [reg["intercept"] + reg["slope"] * x for x in xr]
                    fig.add_trace(go.Scatter(
                        x=xr, y=yr, mode="lines", line=dict(dash="dash", width=1),
                        showlegend=False, hoverinfo="skip"))
                    # R47：95% 预测区间带（基于回归残差）
                    try:
                        xs_arr = np.asarray(months, dtype=float)
                        ys_arr = np.asarray(vals, dtype=float)
                        n = len(xs_arr)
                        if n >= 3 and reg.get("residual_std", 0) > 0:
                            xbar = xs_arr.mean()
                            sxx = ((xs_arr - xbar) ** 2).sum()
                            xg = np.linspace(xs_arr.min(), xs_arr.max(), 30)
                            se_pred = reg["residual_std"] * np.sqrt(1 + 1.0 / n +
                                                                   (xg - xbar) ** 2 / sxx)
                            tval = stats.t.ppf(0.975, n - 2)
                            yhat = reg["intercept"] + reg["slope"] * xg
                            upper = yhat + tval * se_pred
                            lower = yhat - tval * se_pred
                            fig.add_trace(go.Scatter(x=xg, y=upper, mode="lines",
                                        line=dict(width=0), showlegend=False, hoverinfo="skip"))
                            fig.add_trace(go.Scatter(x=xg, y=lower, mode="lines",
                                        line=dict(width=0), fill="tonexty",
                                        fillcolor="rgba(200,200,200,0.25)", name=f"{s.batch_id}-{cond} 95%PI",
                                        hoverinfo="skip"))
                    except Exception:
                        pass
                    xs_grid.extend([float(months.min()), float(months.max())])
    # 限度线
    if limit_spec is not None and direction:
        try:
            lim = float(limit_spec)
            fig.add_hline(y=lim, line=dict(color="red", dash="dot"),
                          annotation_text=f"限度 ({direction}) {lim}", annotation_position="bottom right")
        except (TypeError, ValueError):
            pass
    # R19：在图中标注推算有效期（95% 单侧下限竖线）——需限度且长期数据
    if limit_spec is not None and direction and xs_grid:
        try:
            lim = float(limit_spec)
            # 取长期条件合并数据推算
            xs_all, ys_all = [], []
            for s in study.samples:
                months, vals, _ = A._series_for(s, attr, "长期")
                if len(vals) >= 3:
                    xs_all.extend(list(months))
                    ys_all.extend(list(vals))
            if len(xs_all) >= 3:
                e = A.expiry_recommendation(np.asarray(xs_all), np.asarray(ys_all), lim, direction)
                te = e.get("lower_bound_95") if isinstance(e, dict) else None
                if te and te > 0 and te <= max(xs_grid) * 2:
                    fig.add_vline(x=te, line=dict(color="orange", dash="dash"),
                                  annotation_text=f"推算有效期≈{te:.1f}月", annotation_position="top")
        except Exception:
            pass
    fig.update_layout(title=f"{study.drug_name or study.name} — {attr} 降解趋势（交互）",
                      xaxis_title="时间 (月)", yaxis_title=attr,
                      hovermode="x unified", height=420, legend=dict(font=dict(size=9)),
                      margin=dict(l=40, r=20, t=40, b=40))
    st.plotly_chart(fig)


def persist(study: M.StabilityStudy, actor: dict, action: str, before: dict = None):
    d = study.to_dict()
    # 模板元数据（limits/attrs/conditions/note）持久化到 meta_json
    meta = {}
    for k in ("_template_limits", "_template_attrs", "_template_conditions", "_template_note"):
        if hasattr(study, k):
            meta[k[10:]] = getattr(study, k)
    if meta:
        d["meta_json"] = json.dumps(meta, ensure_ascii=False)
    DB.save_study(d)
    ip = st.session_state.get("client_ip", "")
    AU.audit(action, "study", study.study_id, actor.get("username", ""), actor.get("role", ""),
             ip, st.session_state.get("session_id", ""), before, d,
             note=study.name)
    # R21：数据变更后清除缓存，保证展示最新
    load_study_obj.clear()


def seed_teaching_examples(actor: dict) -> int:
    """R15：生成生物制品教学示例（单抗 DS + DP），含 CQA 降解数据。返回加载研究数。"""
    rng = np.random.default_rng(2026)
    # ---- 单抗原液 DS（冷冻-80，强制降解，冻融循环）----
    ds = M.StabilityStudy("教学示例-单抗原液DS", "原料药", "教学单抗",
                          sponsor="教学", design="全检", biologic=True,
                          molecule_type="单抗", stage="III期临床")
    for bid in ("DS-B1", "DS-B2", "DS-B3"):
        P.add_sample_with_plan(ds, bid, "原液瓶", "", ["冷冻-80", "强制降解", "冻融循环"])
    # 填充冷冻-80 长期 CQA 数据（缓慢降解）
    months = np.array([0, 3, 6, 9, 12, 18, 24, 36])
    for sm in ds.samples:
        base = {"效价": 100.0, "聚集体": 1.5, "碎片": 3.0, "脱酰胺": 2.0, "氧化": 1.0, "电荷异质体": 12.0}
        for attr, b0 in base.items():
            for i, mo in enumerate(months):
                tp = next((t for t in sm.time_points if t.condition == "冷冻-80" and t.month == mo), None)
                if tp is None:
                    continue
                if attr == "效价":
                    val = b0 - 0.6 * i + rng.normal(0, 0.3)
                elif attr in ("聚集体", "碎片"):
                    val = b0 + 0.12 * i + rng.normal(0, 0.08)
                else:
                    val = b0 + 0.05 * i + rng.normal(0, 0.05)
                sm.measurements.append(M.Measurement(tp.month, attr, round(float(val), 2),
                                   "相对标示量%" if attr == "效价" else "%",
                                   b0 - 3 if attr == "效价" else (b0 * 1.6 if attr == "聚集体" else None),
                                   False, "", "", "lower" if attr == "效价" else "upper", tp_ref=tp.tp_id))
    # 冻融循环（5次）
    ft_months = [0, 1, 2, 3, 5]
    for sm in ds.samples:
        for i, cyc in enumerate(ft_months):
            tp = next((t for t in sm.time_points if t.condition == "冻融循环" and t.month == cyc), None)
            if tp is None:
                continue
            sm.measurements.append(M.Measurement(tp.month, "效价", round(100.0 - 0.8 * i, 2), "相对标示量%",
                                  80.0, False, "", "", "lower", tp_ref=tp.tp_id))
            sm.measurements.append(M.Measurement(tp.month, "聚集体", round(1.5 + 0.3 * i, 2), "%",
                                  5.0, False, "", "", "upper", tp_ref=tp.tp_id))
    persist(ds, actor, "STUDY_CREATE_TPL")

    # ---- 单抗制剂 DP（冷藏，强制降解，冻融，使用中，运输）----
    dp = M.StabilityStudy("教学示例-单抗制剂DP", "制剂", "教学单抗注射液",
                          sponsor="教学", design="全检", biologic=True,
                          molecule_type="单抗", stage="III期临床",
                          related_study_id=ds.study_id, related_study_type="原液→制剂联动(Q5C)")
    for bid in ("DP-B1", "DP-B2", "DP-B3"):
        P.add_sample_with_plan(dp, bid, "注射剂瓶", "", ["冷藏", "强制降解", "冻融循环", "使用中", "运输"])
    dp_months = np.array([0, 3, 6, 9, 12, 18, 24])
    for sm in dp.samples:
        base = {"效价": 100.0, "聚集体": 1.5, "碎片": 3.0, "脱酰胺": 2.0, "氧化": 1.0, "电荷异质体": 12.0}
        for attr, b0 in base.items():
            for i, mo in enumerate(dp_months):
                tp = next((t for t in sm.time_points if t.condition == "冷藏" and t.month == mo), None)
                if tp is None:
                    continue
                if attr == "效价":
                    val = b0 - 0.9 * i + rng.normal(0, 0.4)
                elif attr in ("聚集体", "碎片"):
                    val = b0 + 0.2 * i + rng.normal(0, 0.1)
                else:
                    val = b0 + 0.08 * i + rng.normal(0, 0.06)
                sm.measurements.append(M.Measurement(tp.month, attr, round(float(val), 2),
                                   "相对标示量%" if attr == "效价" else "%",
                                   b0 - 3 if attr == "效价" else (b0 * 1.6 if attr == "聚集体" else None),
                                   False, "", "", "lower" if attr == "效价" else "upper", tp_ref=tp.tp_id))
    # 使用中（复溶后 0/1/2/7/14/28 天）
    inuse = [0, 1, 2, 7, 14, 28]
    for sm in dp.samples:
        for i, d_ in enumerate(inuse):
            tp = next((t for t in sm.time_points if t.condition == "使用中" and t.month == d_), None)
            if tp is None:
                continue
            sm.measurements.append(M.Measurement(tp.month, "效价", round(100.0 - 0.5 * i, 2), "相对标示量%", 80.0, False, "", "", "lower", tp_ref=tp.tp_id))
    persist(dp, actor, "STUDY_CREATE_TPL")
    return 2


def client_ip() -> str:
    try:
        return st.context.headers.get("X-Forwarded-For", "").split(",")[0] or "local"
    except Exception:
        return "local"


# ----------------------------------------------------------------------------
# 会话初始化
# ----------------------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "session_id" not in st.session_state:
    st.session_state.session_id = os.urandom(8).hex()
if "client_ip" not in st.session_state:
    st.session_state.client_ip = client_ip()


# ----------------------------------------------------------------------------
# 登录页
# ----------------------------------------------------------------------------
def login_page():
    UI.login_brand()
    with st.form("login"):
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")
        if st.form_submit_button("登录"):
            user, reason = AU.verify_password(u, p)
            if user:
                st.session_state.user = dict(user)
                AU.audit("LOGIN", "session", "", u, user["role"],
                         st.session_state.client_ip, st.session_state.session_id, note="登录成功")
                st.rerun()
            else:
                msg = "用户名或密码错误，或账户已禁用。"
                if reason and reason.startswith("locked"):
                    msg = f"账户已锁定，请 {reason.split(':')[1]} 分钟后再试。"
                elif reason == "no_user":
                    msg = "用户名不存在。"
                elif reason == "disabled":
                    msg = "账户已禁用，请联系管理员。"
                st.error(msg)


if not st.session_state.user:
    login_page()
    st.stop()


user = st.session_state.user
# 防御：任何导致 user 为 None 的路径（如会话失效/裸导入）不至于整页 TypeError 崩溃白屏
if not user:
    st.stop()  # 真实 streamlit 下终止脚本
role = user["role"] if user else "viewer"  # 裸模式 st.stop 不生效时仍有默认，避免崩溃
name = user.get("name", "") if user else ""
uname = user.get("username", "") if user else ""


def check_perm(perm: str) -> bool:
    return AU.has_permission(role, perm)


def require(perm: str):
    if not check_perm(perm):
        st.error("权限不足：当前角色无权执行此操作。")
        st.stop()


# ----------------------------------------------------------------------------
# 侧边栏导航
# ----------------------------------------------------------------------------
UI.sidebar_brand(name, AU.ROLE_LABELS.get(role, role))
if st.sidebar.button("退出登录"):
    AU.audit("LOGOUT", "session", "", uname, role,
             st.session_state.client_ip, st.session_state.session_id, note="退出登录")
    st.session_state.user = None
    st.rerun()
if role == "admin":
    st.sidebar.caption("⚠ 若仍在使用初始口令，请立即在下方『修改密码』中更换。")

with st.sidebar.expander("🔑 修改密码"):
    old_p = st.text_input("当前密码", type="password", key="oldp")
    new_p = st.text_input("新密码(≥8位)", type="password", key="newp")
    if st.button("更新密码"):
        ok, why = AU.change_password(user["username"], old_p, new_p)
        if ok:
            AU.audit("PWD_CHANGE", "user", user["username"], user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id)
            st.success("密码已更新。")
        else:
            st.error(f"修改失败：{why}")

nav_options = ["仪表盘", "研究管理", "数据录入", "分析与时序图", "有效期推算", "横向比较", "质量告警", "生物CQA", "光稳定性", "统计汇总", "导出报告", "设计建议", "教学指南", "可比性"]
if check_perm("audit:read"):
    nav_options.append("审计日志")
if check_perm("user:manage"):
    nav_options.append("用户管理")
if user and user.get("role") == "admin":
    nav_options.append("系统维护")
page = st.sidebar.radio("导航", nav_options)

studies = DB.list_studies()


# ----------------------------------------------------------------------------
# 仪表盘
# ----------------------------------------------------------------------------
if page == "仪表盘":
    st.header("📊 稳定性研究仪表盘")
    with st.expander("💡 使用提示（学习模式）", expanded=False):
        st.markdown("本系统支持生物制品(ICH Q5C/Q6B)全流程稳定性研究：**原液(DS)/制剂(DP)联动、"
                    "强制降解、冻融循环、使用中(in-use)、运输稳定性**，并提供显著变化专属阈值"
                    "(效价>10%)、批间合并 Bootstrap 置信区间、留一法稳健性、多模型 AIC/BIC 选择。"
                    "建议新用户先到『教学指南』页学习法规术语与合规清单，再到『研究管理』加载教学示例。")
    if not studies:
        st.info("暂无研究数据。")
    else:
        df_idx = pd.DataFrame(studies)
        agg = dashboard_aggregate(user["username"])  # R49：缓存聚合
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("研究总数", agg["n_study"])
        col2.metric("样品总数", agg["n_sample"])
        col3.metric("生物制品研究", agg["bio"])
        # R25：生物CQA显著变化数（全库）
        bio_sig_n = agg["bio_sig_n"]
        col4.metric("生物CQA显著变化", bio_sig_n)
        # R38：生物 CQA 合格率进度条
        cqa_total = 0
        cqa_pass = 0
        for s in studies:
            st_obj = load_study_obj(s["study_id"])
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    for attr in {m.attribute for m in sm.measurements}:
                        sc = A.biologic_significant_change(st_obj, attr, cond)
                        if sc:
                            cqa_total += 1
                            ct = sc.get("change_type", "")
                            if ct in ("无显著变化(none)",):
                                cqa_pass += 1
        if cqa_total:
            rate = cqa_pass / cqa_total
            st.subheader("🟢 生物 CQA 合格率")
            st.progress(rate)
            st.caption(f"合格（无显著变化）{cqa_pass}/{cqa_total} = {rate*100:.0f}%")
        # R25：近期到期预警（推算有效期 ≤ 18 月的研究批次）
        expiring = []
        for s in studies:
            st_obj = load_study_obj(s["study_id"])
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    if cond not in (M.StorageCondition.LONG_TERM.value, "长期"):
                        continue
                    for attr in {m.attribute for m in sm.measurements}:
                        dl = M.default_limit_for(attr)
                        if not dl:
                            continue
                        try:
                            e = A.expiry_recommendation(np.asarray([m.time_point_id for m in sm.measurements if m.attribute == attr and m.value is not None]),
                                                        np.asarray([m.value for m in sm.measurements if m.attribute == attr and m.value is not None]),
                                                        dl[1], dl[0])
                            te = e.get("lower_bound_95") if isinstance(e, dict) else None
                            if te is not None and te <= 18:
                                expiring.append({"研究": st_obj.name, "批号": sm.batch_id,
                                                 "CQA": attr, "推算有效期(月)": round(te, 1)})
                        except Exception:
                            continue
        if expiring:
            st.warning(f"⏰ 近期到期预警（推算有效期≤18月）：{len(expiring)} 项")
            with st.expander("查看明细"):
                st.dataframe(pd.DataFrame(expiring), width='stretch')
        # 阶段分布（仅生物制品）
        bio_studies = [s for s in studies if load_study_obj(s["study_id"]).biologic]
        if bio_studies:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("生物制品临床阶段分布")
                stage_cnt = {}
                for s in bio_studies:
                    stg = load_study_obj(s["study_id"]).stage or "未指定"
                    stage_cnt[stg] = stage_cnt.get(stg, 0) + 1
                fig_s = go.Figure(go.Bar(x=list(stage_cnt.keys()), y=list(stage_cnt.values()), text=list(stage_cnt.values()), textposition="auto"))
                fig_s.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_s)
        # 图表化概览
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("研究类型分布")
            types = df_idx["study_type"].value_counts() if "study_type" in df_idx else pd.Series(dtype=int)
            if not types.empty:
                fig_t = go.Figure(go.Pie(labels=types.index.tolist(), values=types.values.tolist(), hole=0.4))
                fig_t.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_t)
            else:
                st.caption("无数据")
        with c2:
            st.subheader("化学药 / 生物制品占比")
            bio = int(df_idx.get("biologic", pd.Series([0])).sum()) if "biologic" in df_idx else 0
            chem = len(studies) - bio
            fig_b = go.Figure(go.Bar(x=["化学药", "生物制品"], y=[chem, bio],
                                     text=[chem, bio], textposition="auto"))
            fig_b.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_b)
        # 近90天待取样柱状
        plan_rows = []
        today = date.today()
        for s in studies:
            study = load_study_obj(s["study_id"])
            for r in P.plan_summary(study):
                try:
                    pd_date = date.fromisoformat(r["计划日期"])
                except Exception:
                    continue
                if today <= pd_date <= today.fromordinal(today.toordinal() + 90) and r["已取样"] == "否":
                    plan_rows.append(pd_date.month)
        if plan_rows:
            st.subheader("未来90天待取样（按月）")
            mc = pd.Series(plan_rows).value_counts().sort_index()
            fig_m = go.Figure(go.Bar(x=[f"{m}月" for m in mc.index], y=mc.values.tolist()))
            fig_m.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_m)
        st.subheader("研究列表")
        cols = ["study_id", "name", "drug_name", "study_type", "design",
                "biologic", "molecule_type", "start_date", "updated_at"]
        cols = [c for c in cols if c in df_idx.columns]
        st.dataframe(df_idx[cols], width='stretch')
        st.subheader("近期取样计划（未来90天）")
        rows = []
        today = date.today()
        for s in studies:
            study = load_study_obj(s["study_id"])
            for r in P.plan_summary(study):
                try:
                    pd_date = date.fromisoformat(r["计划日期"])
                except Exception:
                    continue
                if today <= pd_date <= today.fromordinal(today.toordinal() + 90) and r["已取样"] == "否":
                    rows.append({**r, "研究": study.name})
        if rows:
            st.dataframe(pd.DataFrame(rows), width='stretch')
        else:
            st.caption("未来90天无待取样计划。")


# ----------------------------------------------------------------------------
# 研究管理
# ----------------------------------------------------------------------------
elif page == "研究管理":
    st.header("🗂 研究管理")
    if not check_perm("study:create"):
        st.error("权限不足：需 study:create。")
    else:
        tab1, tab2 = st.tabs(["新建研究", "研究列表 / 删除"])
        with tab1:
            # 从模板创建
            with st.expander("⚡ 从方案模板快速创建"):
                tpl_name = st.selectbox("选择模板", P.list_templates())
                t_name = st.text_input("新研究名称", "模板研究")
                t_sponsor = st.text_input("申办方/部门", "")
                t_batches = st.text_input("批号（逗号分隔，如 B1,B2,B3）", "B1,B2,B3")
                t_start = st.date_input("起始日期", date.today(), key="tpl_start")
                note = P.template_note(tpl_name)
                if note:
                    st.info(f"📋 模板说明：{note}")
                stage_opts = [s.value for s in M.DevelopmentStage]
                t_stage = st.selectbox("临床阶段", stage_opts, index=0, key="tpl_stage")
                rel_opts = ["（无）"] + [f'{s["name"]} ({s["study_id"]})' for s in studies]
                t_rel = st.selectbox("关联研究（如 DS 对应 DP）", rel_opts, key="tpl_rel")
                t_rel_kind = st.text_input("关联类型描述", "原液→制剂联动(Q5C)")
                if st.button("基于模板创建"):
                    batches = [b.strip() for b in t_batches.split(",") if b.strip()]
                    st_tpl = P.create_from_template(tpl_name, t_name, t_sponsor, batches, t_start.isoformat(), stage=t_stage)
                    if t_rel != "（无）":
                        rsid = t_rel.split("(")[-1].rstrip(")")
                        st_tpl.related_study_id = rsid
                        st_tpl.related_study_type = t_rel_kind
                    persist(st_tpl, user, "STUDY_CREATE_TPL")
                    st.success(f"已基于模板创建：{t_name}（阶段：{st_tpl.stage}，含 {sum(len(s.time_points) for s in st_tpl.samples)} 个计划取样点，"
                              f"检测项目：{st_tpl._template_attrs}）")
            biologic = st.checkbox("生物制品研究 (ICH Q5C)", value=False)
            with st.form("new_study"):
                name = st.text_input("研究名称", "XX稳定性研究")
                drug = st.text_input("药品通用名", "某化学药")
                stype = st.selectbox("研究类型", [t.value for t in M.StudyType])
                design = st.selectbox("设计类型", [d.value for d in M.DesignType])
                molecule = st.selectbox("分子类型", MOLECULE_OPTIONS, disabled=not biologic)
                stage_opts = [s.value for s in M.DevelopmentStage]
                stage = st.selectbox("临床阶段", stage_opts, index=0, key="new_stage")
                sponsor = st.text_input("申办方/部门", "")
                start = st.date_input("研究起始日期", date.today())
                if st.form_submit_button("创建研究"):
                    mt = molecule if biologic else ""
                    st_obj = M.StabilityStudy(name, stype, drug, sponsor, design,
                                              start.isoformat(), biologic=biologic, molecule_type=mt, stage=stage)
                    persist(st_obj, user, "STUDY_CREATE")
                    st.success(f"已创建研究：{name}（阶段：{stage}，ID: {st_obj.study_id}）")
        # R15：教学示例一键加载（生物制品单抗 DS+DP）
        st.divider()
        st.subheader("🎓 教学示例数据集")
        st.caption("一键生成一套生物制品教学示例（单抗原液DS + 制剂DP，含 CQA 降解数据、冻融/使用中/运输条件），"
                   "用于熟悉系统功能与合规流程。示例数据不构成真实货架期结论。")
        if st.button("加载教学示例（单抗 DS + DP）"):
            n_loaded = seed_teaching_examples(user)
            st.success(f"已加载 {n_loaded} 个教学示例研究（见『研究管理』列表）。可在『教学指南』页对照学习。")
        if studies:
            sel = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies])
            sid = sel.split("(")[-1].rstrip(")")
            if check_perm("study:delete"):
                # R28：删除二次确认（防误删）
                if st.button("删除该研究", type="primary"):
                    st.session_state["confirm_del"] = sid
                if st.session_state.get("confirm_del") == sid:
                    st.error(f"⚠ 确认删除研究『{sid}』？此操作不可撤销！")
                    # 电子签名：删除为关键操作，须重新输入口令（Part 11 §11.200）
                    reauth_pw = st.text_input("请输入您的登录口令以确认（电子签名）", type="password",
                                              key=f"reauth_del_{sid}")
                    c1, c2 = st.columns(2)
                    if c1.button("✅ 确认删除", type="primary"):
                        if not AU.reauthenticate(user["username"], reauth_pw):
                            st.error("口令错误，未删除。（错误次数计入锁定策略）")
                        else:
                            before = DB.load_study(sid)
                            DB.delete_study(sid)
                            AU.audit("STUDY_DELETE", "study", sid, user["username"], role,
                                     st.session_state.client_ip, st.session_state.session_id, before,
                                     note=before["name"] if before else sid)
                            AU.e_signature(sid, "STUDY_DELETE", user.get("name") or user["username"], role,
                                           "删除研究（不可撤销）", username=user["username"],
                                           ip=st.session_state.client_ip)
                            st.session_state["confirm_del"] = None
                            st.rerun()
                    if c2.button("❌ 取消"):
                        st.session_state["confirm_del"] = None
                        st.rerun()
            # R48：研究导入/导出 JSON（便于备份迁移与审计追溯）
            col_imp, col_exp = st.columns(2)
            with col_exp:
                if st.button("📤 导出该研究 JSON"):
                    st_obj = load_study_obj(sid)
                    st.download_button("下载", json.dumps(st_obj.to_dict(), ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                                       f"{sid}.json", "application/json")
            with col_imp:
                upj = st.file_uploader("📥 导入研究 JSON", type=["json"], key="imp_json")
                if upj:
                    try:
                        data = json.loads(upj.getvalue().decode("utf-8"))
                        st_obj = M.StabilityStudy.from_dict(data)
                        # 若 ID 冲突则生成新 ID
                        if DB.load_study(st_obj.study_id):
                            st_obj.study_id = M.StabilityStudy.from_dict({}).study_id  # 新ID
                            st_obj.study_id = f"IMP_{int(__import__('time').time())}"
                        persist(st_obj, user, "STUDY_IMPORT")
                        st.success(f"已导入研究：{st_obj.name}（ID: {st_obj.study_id}）")
                    except Exception as e:
                        st.error(f"导入失败：{e}")
            st.divider()
            st.subheader("添加样品与取样计划")
            study = load_study_obj(sid)
            cond_opts = BIO_CONDITIONS if study.biologic else CHEM_CONDITIONS
            with st.form("add_sample"):
                batch = st.text_input("批号", "B2026-001")
                pkg = st.text_input("包装/容器", "铝塑泡罩+复合膜")
                strength = st.text_input("规格", "10mg")
                conds = st.multiselect("研究条件", cond_opts, default=[cond_opts[0]] if cond_opts else [])
                # R41：时间点方案选择
                tp_preset = st.selectbox("时间点方案", list(P.TIME_POINT_PRESETS.keys()),
                                         help="选择 ICH 标准时间点预设，或留空用默认方案")
                if st.form_submit_button("添加样品并生成计划"):
                    before = study.to_dict()
                    custom = P.TIME_POINT_PRESETS.get(tp_preset)
                    P.add_sample_with_plan(study, batch, pkg, strength, conds,
                                           molecule_type=study.molecule_type, custom_months=custom)
                    persist(study, user, "SAMPLE_ADD", before)
                    st.success(f"样品 {batch} 已添加，计划 {len(study.samples[-1].time_points)} 个取样点。")


# ----------------------------------------------------------------------------
# 数据录入
# ----------------------------------------------------------------------------
elif page == "数据录入":
    st.header("🧪 检测数据录入")
    if not check_perm("data:write"):
        st.error("权限不足：需 data:write。")
    elif not studies:
        st.info("请先创建研究。")
    else:
        # R9：教学提示 —— 生物制品 CQA 录入规范
        sel0 = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies], key="entry_sel0")
        sid0 = sel0.split("(")[-1].rstrip(")")
        study0 = load_study_obj(sid0)
        if study0.biologic:
            st.info("🧬 生物制品：CQA 录入请使用稳定性指示方法；效价下降>10% 即判显著变化(Q5C)。"
                    "强制降解/冻融/使用中/运输等特殊条件数据请按模板条件分类录入。")
        sel = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        # ---- 批量 CSV 录入 ----
        with st.expander("📥 批量 CSV 录入（列：批号,条件,月点,检测项目,数值,单位,限度,方向）"):
            st.caption("示例：B2026-001,冷藏(2-8C),0,效价,100.0,%,90,lower")
            # R24：CSV 模板下载
            tmpl_csv = IM.TEMPLATE_CSV
            st.download_button("⬇ 下载 CSV 录入模板", tmpl_csv.encode("utf-8-sig"),
                               "bulk_template.csv", "text/csv")
            up = st.file_uploader("上传 CSV", type=["csv"], key="bulk_csv")
            if up:
                try:
                    bulk = IM.read_bulk_csv(up.getvalue())
                    before = study.to_dict()
                    cnt, skipped = IM.import_bulk_csv(study, bulk)
                    if cnt:
                        persist(study, user, "DATA_BULK", before)
                        st.success(f"已批量录入 {cnt} 条。")
                    else:
                        st.warning("未匹配到任何有效记录（请确认批号存在于本研究）。")
                    if skipped:
                        with st.expander(f"跳过 {len(skipped)} 行（查看原因）"):
                            for msg in skipped:
                                st.write("• " + msg)
                except ValueError as e:
                    st.error(f"CSV 导入失败：{e}")
        sample_opts = {f'{s.batch_id} ({s.sample_id})': s for s in study.samples}
        if not sample_opts:
            st.warning("该研究尚无样品，请先在『研究管理』添加。")
        else:
            samp_sel = st.selectbox("选择样品", list(sample_opts.keys()))
            sample = sample_opts[samp_sel]
            tp_opts = {f'{tp.condition} {tp.month}月 ({tp.planned_date})': tp for tp in sample.time_points}
            tp_sel = st.selectbox("选择取样时间点", list(tp_opts.keys()))
            tp = tp_opts[tp_sel]
            attr = st.selectbox("检测项目", ATTRIBUTE_OPTIONS)
            # R46：边录边看——该属性历史趋势 mini 图
            hist_x, hist_y = [], []
            for sm in study.samples:
                for m in sm.measurements:
                    if m.attribute == attr and m.value is not None:
                        hist_x.append(m.time_point_id)
                        hist_y.append(m.value)
            if hist_x:
                fig_mini = go.Figure(go.Scatter(x=hist_x, y=hist_y, mode="markers+lines",
                                                name="历史"))
                fig_mini.update_layout(title=f"{attr} 已录入趋势（边录边看）", height=200,
                                       margin=dict(l=30, r=10, t=30, b=30))
                st.plotly_chart(fig_mini)
            # R20：复制该批最近一次同属性值（提升录入效率）
            if st.button("📋 复制该批最近同属性值"):
                last_v = None
                for m in reversed(sample.measurements):
                    if m.attribute == attr and m.value is not None:
                        last_v = m.value
                        break
                if last_v is not None:
                    st.session_state["prefill_val"] = last_v
                    st.rerun()
                else:
                    st.info("该批暂无同属性历史值。")
            col1, col2 = st.columns(2)
            val = col1.number_input("检测数值", value=st.session_state.get("prefill_val", 0.0), key="val_input", format="%.4f")
            # R35：单位智能默认（按属性）
            _unit_default = {
                "效价": "相对标示量%", "含量": "%", "结合活性": "%",
                "聚集体": "%", "碎片": "%", "脱酰胺": "%", "氧化": "%",
                "电荷异质体": "%", "糖基化": "%", "有关物质": "%", "水分": "%",
                "不溶性微粒": "个/剂", "渗透压": "mOsm/kg", "pH": "", "可见异物": "",
                "容器密封": "", "纯度(HPLC)": "%",
            }.get(attr, "%")
            unit = col2.text_input("单位", _unit_default)
            # R27：优先用模板限度预填（先于实时校验计算）
            raw = DB.load_study(sid)
            tpl_limits = {}
            try:
                if raw.get("meta_json"):
                    meta = json.loads(raw["meta_json"])
                    tpl_limits = meta.get("limits", {})
            except Exception:
                pass
            # R27：实时合规提示（边录边校验）
            dft_now = tpl_limits.get(attr) if attr in tpl_limits else M.default_limit_for(attr)
            if dft_now:
                dir_now, lim_now = dft_now
                warns_rt = M.validate_measurement(attr, float(val) if val else 0.0, unit=unit,
                                                  limit_spec=lim_now, direction=dir_now)
                if warns_rt:
                    for w in warns_rt:
                        st.warning("⚠ " + w)
            if attr in tpl_limits:
                tpl_lim, tpl_dir = tpl_limits[attr]
                dft = (tpl_dir, tpl_lim)
                st.caption(f"📋 模板预填限度：{attr} 方向={tpl_dir}，默认={tpl_lim}")
            else:
                dft = M.default_limit_for(attr)
                if dft:
                    st.caption(f"提示：{attr} 默认限度方向={dft[0]}，默认值={dft[1]}")
            col3, col4 = st.columns(2)
            limit_val = col3.number_input("质量标准限度(可选)", value=float(dft[1]) if dft else 0.0, format="%.4f")
            limit_on = col4.checkbox("设置该限度用于有效期推算", value=bool(dft))
            note = st.text_input("备注", "")
            # R11：稳定性指示能力可选字段（分离度/峰纯度）
            rc1, rc2 = st.columns(2)
            res_input = rc1.number_input("分离度 Rs (可选, 指示能力≥1.5)", value=0.0, min_value=0.0, format="%.2f")
            pp_input = rc2.number_input("峰纯度 % (可选, ≥95%)", value=0.0, min_value=0.0, max_value=100.0, format="%.1f")
            if st.button("保存检测值", type="primary"):
                before = study.to_dict()
                is_limit = (attr in ("有关物质", "杂质", "聚集体", "碎片", "脱酰胺",
                                     "氧化", "电荷异质体", "不溶性微粒", "糖基化"))
                direction = dft[0] if dft else ("lower" if not is_limit else "upper")
                cqa = attr if study.biologic else ""
                m = M.Measurement(tp.month, attr, val, unit, limit_val if limit_on else None, is_limit, note, cqa, direction, tp_ref=tp.tp_id,
                                  resolution=res_input if res_input > 0 else None,
                                  peak_purity=pp_input if pp_input > 0 else None)
                sample.measurements.append(m)
                persist(study, user, "DATA_ADD", before)
                st.success("已保存。")
            st.subheader("已录入数据")
            if sample.measurements:
                st.dataframe(pd.DataFrame([m.to_dict() for m in sample.measurements]), width='stretch')
                # 删除指定检测值
                del_opts = {f'{m.time_point_id}月/{m.attribute}/{m.value}': m for m in sample.measurements}
                del_sel = st.selectbox("选择要删除的记录", list(del_opts.keys()))
                if st.button("删除该记录", type="secondary"):
                    before = study.to_dict()
                    sample.measurements = [m for m in sample.measurements if m is not del_opts[del_sel]]
                    persist(study, user, "DATA_DELETE", before)
                    st.success("已删除。")
                    st.rerun()


# ----------------------------------------------------------------------------
# 分析与时序图
# ----------------------------------------------------------------------------
elif page == "分析与时序图":
    st.header("📈 降解趋势分析")
    if not studies:
        st.info("请先创建研究。")
    else:
        sel = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        attrs = st.multiselect("检测项目", ATTRIBUTE_OPTIONS, default=["含量", "效价"])
        if attrs:
            res = A.analyze_study(study, attrs)
            if res:
                st.dataframe(pd.DataFrame(res), width='stretch')
                # 限度选择（用于趋势图标示）
                lim_attr = st.selectbox("在图中标示限度（可选）", [""] + attrs)
                lim_val = None
                lim_dir = ""
                if lim_attr:
                    # 从首个匹配 measurement 取限度
                    for s in study.samples:
                        for m in s.measurements:
                            if m.attribute == lim_attr and m.limit_spec is not None:
                                lim_val = m.limit_spec
                                lim_dir = m.direction
                                break
                        if lim_val is not None:
                            break
                # R11：生物制品特殊条件说明（教学提示）
                if study.biologic:
                    special = [c for c in set(tp.condition for s in study.samples for tp in s.time_points)
                               if c in M.SPECIAL_CONDITION_DESC]
                    if special:
                        for c in special:
                            st.caption(f"🔬 {c}：{M.SPECIAL_CONDITION_DESC[c]}")
                st.subheader("交互式趋势图（可缩放/悬浮）")
                for attr in attrs:
                    render_interactive_trend(study, attr, lim_val if attr == lim_attr else None, lim_dir)
                # R36：异常点标注（MAD 稳健离群检测高亮）
                st.subheader("🔍 异常点标注 (MAD 离群检测)")
                for attr in attrs:
                    outlier_rows = []
                    for s in study.samples:
                        for cond in set(tp.condition for tp in s.time_points):
                            months, vals, _ = A._series_for(s, attr, cond)
                            if len(vals) >= 4:
                                idxs = A.mad_outlier_detection(list(vals))
                                for i in idxs:
                                    outlier_rows.append({"批号": s.batch_id, "条件": cond,
                                                         "月点": months[i], "数值": round(vals[i], 2)})
                    if outlier_rows:
                        st.warning(f"『{attr}』检出 {len(outlier_rows)} 个疑似离群点（MAD z>3.5）：")
                        st.dataframe(pd.DataFrame(outlier_rows), width='stretch')
                    else:
                        st.caption(f"『{attr}』未检出显著离群点。")
                import matplotlib.pyplot as plt
                st.subheader("静态趋势图（备用）")
                for attr in attrs:
                    fig, ax = plt.subplots(figsize=(8, 4))
                    for s in study.samples:
                        for cond in set(tp.condition for tp in s.time_points):
                            months, vals, _ = A._series_for(s, attr, cond)
                            if len(vals) >= 1:
                                ax.plot(months, vals, marker="o", label=f"{s.batch_id}-{cond}")
                                reg = A.regression_summary(months, vals)
                                if reg and reg["n"] >= 2:
                                    xs = [months.min(), months.max()]
                                    ys = [reg["intercept"] + reg["slope"] * x for x in xs]
                                    ax.plot(xs, ys, "--", alpha=0.5)
                    ax.set_xlabel("时间 (月)")
                    ax.set_ylabel(attr)
                    ax.set_title(f"{study.drug_name} — {attr} 降解趋势")
                    ax.legend(fontsize=7)
                    ax.grid(alpha=0.3)
                    st.pyplot(fig)
            else:
                st.info("暂无足够数据（每序列需≥2个点）。")
            # R26：数据质量评分（study_data_quality 可视化）
            if study.samples:
                q = A.study_data_quality(study, attrs)
                score, n_issues = A.data_quality_score(q)
                st.subheader("🏅 数据质量评分")
                st.progress(score / 100.0)
                st.caption(f"质量分：{score}/100（启发式：每个问题扣 5 分，仅供内部排查，不是法规指标），问题数：{n_issues}")
                if q:
                    with st.expander("查看质量问题明细"):
                        for iss in q:
                            st.write(f"• {iss['批号']} / {iss['条件']} / {iss['检测项目']}：离群索引 {iss['离群索引'] or '无'}，"
                                     f"缺失月点 {iss['缺失月点'] or '无'}，非线性提示 {iss['非线性'] or '无'}")
            # R42：批间趋势发散检测（不同批降解斜率差异是否随时间扩大）
            diverging = []
            for attr in (attrs if attrs else []):
                slopes = {}
                for sm in study.samples:
                    xs, ys = [], []
                    for m in sm.measurements:
                        if m.attribute != attr or m.value is None:
                            continue
                        tp = A._tp_by_ref(study, sm, m)
                        if tp is None or tp.condition not in (M.StorageCondition.LONG_TERM.value, "长期"):
                            continue
                        xs.append(m.time_point_id)
                        ys.append(m.value)
                    if len(xs) >= 2:
                        sl, _, _, _, _ = stats.linregress(xs, ys)
                        slopes[sm.batch_id] = sl
                if len(slopes) >= 2:
                    sl_vals = list(slopes.values())
                    spread = max(sl_vals) - min(sl_vals)
                    if spread > 0.5:  # 斜率差异>0.5%/月 视为发散
                        diverging.append({"CQA": attr, "斜率极差(%/月)": round(spread, 3),
                                          "批斜率": {k: round(v, 3) for k, v in slopes.items()}})
            if diverging:
                st.error("⚠ 批间趋势发散：以下 CQA 各批降解速率差异显著，提示工艺/批间不均一，"
                         "不可简单外推，建议逐批评估或减括号。")
                with st.expander("查看发散明细"):
                    st.dataframe(pd.DataFrame(diverging), width='stretch')


# ----------------------------------------------------------------------------
# 有效期推算
# ----------------------------------------------------------------------------
elif page == "有效期推算":
    st.header("⏳ 有效期 / 复验期推算 (ICH Q1E / Q5C)")
    st.caption("基于各检测项目的限度，按95%置信下限(下限限度)或上限(上限限度)推算有效期。需≥3个时间点。"
               "生物制品聚集体/碎片等常见非线性降解，系统会给出提示。")
    if not studies:
        st.info("请先创建研究。")
    else:
        sel = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        attrs = st.multiselect("检测项目", ATTRIBUTE_OPTIONS, default=["含量", "效价"])
        if attrs:
            res = A.analyze_study(study, attrs)
            if res:
                df = pd.DataFrame(res)
                df_disp = df[["批号", "条件", "检测项目", "数据点", "斜率/月", "R²", "p值", "趋势", "有效期(月)", "备注"]]
                st.dataframe(df_disp, width='stretch')
                if "有效期(月)" in df.columns:
                    valid = df.dropna(subset=["有效期(月)"])
                    if not valid.empty:
                        st.subheader("各样品最严格有效期（取所有项目最小值）")
                        summary = valid.groupby("批号")["有效期(月)"].min().reset_index()
                        summary.columns = ["批号", "建议有效期(月)"]
                        st.dataframe(summary, width='stretch')
                        st.warning("注：有效期应取各CQA中最严格者，并向下舍入至合规整数月（ICH Q1E/Q5C）。"
                                   "外推超过观测期1倍需有充分论证；生物制品非线性降解应谨慎外推。")
                        # R22：外推风险等级（批数/覆盖率/LOO 稳健性）
                        n_batch = len(study.samples)
                        risk_factors = []
                        if n_batch < 3:
                            risk_factors.append(f"批数不足({n_batch}<3)")
                        # 覆盖率：观测期占推算比例
                        max_obs = max((tp.month for sm in study.samples for tp in sm.time_points
                                       if tp.condition in (M.StorageCondition.LONG_TERM.value, "长期")), default=0)
                        min_exp = summary["建议有效期(月)"].min() if not summary.empty else 0
                        if max_obs and min_exp > max_obs * 2:
                            risk_factors.append("外推>2倍观测期(高风险)")
                        elif max_obs and min_exp > max_obs * 1.5:
                            risk_factors.append("外推>1.5倍观测期(中风险)")
                        # LOO 稳健性
                        loo_robust = True
                        for s in study.samples:
                            for cond in set(tp.condition for tp in s.time_points):
                                dl = M.default_limit_for("效价")
                                if dl and n_batch >= 2:
                                    lo = A.leave_one_out_expiry(study, "效价", cond, dl[1], dl[0])
                                    if lo and not lo.get("robust"):
                                        loo_robust = False
                        if not loo_robust:
                            risk_factors.append("留一法外推不稳健")
                        if not risk_factors:
                            st.success("✅ 外推风险等级：低（批数充足、外推比例适度、LOO稳健）。")
                        else:
                            st.error("⚠ 外推风险等级：高/中 — " + "；".join(risk_factors)
                                     + "。建议补充批次、延长监测期或限制外推。")
            else:
                st.info("需在『数据录入』中录入检测值（≥3时间点）。")
            # R37：多模型对比图（线性/指数/logistic，AIC 选择）
            st.subheader("📉 多模型拟合对比 (AIC/BIC 选择)")
            mm_attrs = attrs
            mm_conds = sorted({tp.condition for sm in study.samples for tp in sm.time_points})
            if mm_attrs and mm_conds:
                mm_a = st.selectbox("选择属性（多模型）", mm_attrs, key="mm_a")
                mm_c = st.selectbox("选择条件（多模型）", mm_conds, key="mm_c")
                try:
                    bm = A.fit_best_model(study, mm_a, mm_c)
                    fig_mm = go.Figure()
                    for s in study.samples:
                        months, vals, _ = A._series_for(s, mm_a, mm_c)
                        if vals:
                            fig_mm.add_trace(go.Scatter(x=list(months), y=list(vals),
                                                        mode="markers", name=f"{s.batch_id}实测"))
                    t_grid = bm.get("t_grid")
                    for name, pred in bm.get("predictions", {}).items():
                        fig_mm.add_trace(go.Scatter(x=t_grid, y=pred, mode="lines",
                                                    name=f"{name} (AIC={bm['comparison'][name]['aic']:.0f})"))
                    fig_mm.update_layout(title=f"{mm_a} @ {mm_c} 多模型拟合", xaxis_title="月", yaxis_title=mm_a)
                    st.plotly_chart(fig_mm)
                    best = bm["best_model"]
                    st.success(f"最优模型（最小 AIC）：**{best}**（AIC={bm['comparison'][best]['aic']:.1f}）")
                except Exception as e:
                    st.info("多模型拟合暂不可用：" + str(e)[:100])
            # 外推因子分析（ICH Q1E）
            ext_rows = []
            for attr in attrs:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        ex = A.expiry_extrapolation(study, attr, cond)
                        if ex:
                            ext_rows.append({"批号": ex["batch"], "条件": ex["condition"],
                                             "检测项目": ex["attribute"], "观测期(月)": ex["t_obs"],
                                             "95%下限有效期": ex["t_lower_bound"],
                                             "外推倍率": ex["extrap_factor"], "建议": ex["recommendation"]})
            if ext_rows:
                st.subheader("外推因子分析 (ICH Q1E)")
                st.dataframe(pd.DataFrame(ext_rows), width='stretch')
            # R18：多模型拟合与 AIC/BIC 选择（非线性降解提示）
            st.subheader("模型拟合与选择 (线性/指数/逻辑斯蒂, AIC/BIC)")
            model_rows = []
            for attr in attrs:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        # 取限度
                        lim = None
                        for m in s.measurements:
                            if m.attribute == attr and m.limit_spec is not None:
                                lim = m.limit_spec
                                break
                        if lim is None:
                            continue
                        ref = next((m.value for sm in study.samples for m in sm.measurements if m.attribute == attr), 0)
                        direction = "lower" if lim < ref else "upper"
                        fm = A.fit_best_model(study, attr, cond, lim, direction)
                        if fm:
                            comp = fm["comparison"]
                            model_rows.append({
                                "条件": cond, "检测项目": attr, "最优模型": fm["best_model"],
                                "AIC": fm["best_aic"], "BIC": fm["best_bic"],
                                "线性有效期": comp.get("linear", {}).get("shelf_life"),
                                "最优模型有效期": fm["shelf_life_best"],
                            })
            if model_rows:
                st.dataframe(pd.DataFrame(model_rows), width='stretch')
                nonlinear = [r for r in model_rows if r["最优模型"] != "linear"]
                if nonlinear:
                    st.warning("⚠ 以下组合非线性模型(AIC/BIC 更优)："
                               + "、".join(f'{r["检测项目"]}@{r["条件"]}' for r in nonlinear)
                               + "。生物制品降解多非线性，线性外推偏乐观(Q1E)，"
                               "建议增加时间点或采用非线性模型推算有效期。")
            # R12：批合并外推有效期（Q1E 95% 单侧下限）
            st.subheader("📏 批合并外推有效期 (ICH Q1E 95% 单侧下限)")
            pe_rows = []
            all_conds = sorted({tp.condition for sm in study.samples for tp in sm.time_points})
            for attr in attrs:
                for cond in all_conds:
                    pe = A.pooled_expiry_extrapolation(study, attr, cond)
                    if pe["recommended"] is not None:
                        pe_rows.append({
                            "检测项目": attr, "条件": cond,
                            "可合并": "是" if pe["poolable"] else "否",
                            "合并外推(月)": round(pe["pooled_expiry"], 1) if pe["pooled_expiry"] else None,
                            "单批最小(月)": round(pe["min_single_expiry"], 1) if pe["min_single_expiry"] else None,
                            "保守建议(月)": round(pe["recommended"], 1),
                        })
            if pe_rows:
                st.dataframe(pd.DataFrame(pe_rows), width='stretch')
                st.caption("保守有效期取『合并外推』与『单批最小外推』的较小值（95% 单侧置信下限，Q1E）。")
            else:
                st.info("暂无可计算外推有效期的检测项目。")
            # 显著变化判定（生物制品用 Q5C 专属阈值）
            sig_rows = []
            for attr in attrs:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        sc = A.biologic_significant_change(study, attr, cond)
                        if sc:
                            sig_rows.append(sc)
            if sig_rows:
                st.subheader("显著变化判定 (ICH Q1A / Q5C)")
                st.dataframe(pd.DataFrame(sig_rows), width='stretch')
            # R9：生物制品外推谨慎提示
            if study.biologic:
                st.warning("🧬 生物制品外推需谨慎 (Q5C/Q1E)：建议至少 3 批、覆盖 75% 监测期，"
                           "且批间一致方可外推至 2 倍（长期）或 1.5 倍（加速）。可用『统计汇总』页的"
                           "Bootstrap 置信区间与留一法评估外推稳健性。")
            # R3：使用中稳定性（in-use，以天为单位）
            inuse_attrs = [a for a in attrs
                           if any(tp.condition == "使用中" for s in study.samples for tp in s.time_points)
                           and any(m.attribute == a for s in study.samples for m in s.measurements)]
            if inuse_attrs:
                st.subheader("💉 使用中稳定性 (in-use, 复溶/开启后天数)")
                st.caption("ICH Q5C：多剂量/复溶制剂需评估开启后使用期限（常见 28 天）。"
                           "本段以『开启后天数』为横轴推算 CQA 触及限度的天数。")
                for attr in inuse_attrs:
                    r = A.in_use_shelf_life(study, attr)
                    if r["status"] == "ok":
                        st.success(f"{attr}：{r['note']}")
                        st.dataframe(pd.DataFrame(r["batches"]), width='stretch')
                    else:
                        st.info(f"{attr}：{r['note']}")
            # R14：批间一致性 / 工艺能力 Cpk
            st.subheader("📊 批间一致性 / 工艺能力 (Cpk)")
            cpk_rows = []
            for attr in attrs:
                cc = A.batch_consistency_capability(study, attr)
                if cc["n_batches"] >= 2:
                    cpk_rows.append({
                        "检测项目": attr, "批数": cc["n_batches"],
                        "批均值": round(cc["mean"], 2) if cc["mean"] else None,
                        "σ": round(cc["sd"], 2) if cc["sd"] else None,
                        "Cpk": ("∞" if cc["cpk"] == float("inf") else round(cc["cpk"], 2)),
                        "一致性": cc["consistency"],
                    })
            if cpk_rows:
                st.dataframe(pd.DataFrame(cpk_rows), width='stretch')
                st.caption("Cpk≥1.33 优；1.0–1.33 良；0.67–1.0 临界；<0.67 差。规格未提供时以历史批均值±3σ为经验规格。")
            else:
                st.info("批数不足，无法评估批间一致性。")
            # R15：容器密封完整性（CCIT）趋势
            cc = A.ccit_trend_assessment(study)
            if cc["has_data"]:
                st.subheader("🔒 容器密封完整性 (CCIT, USP<1207>/Q5C)")
                st.dataframe(pd.DataFrame(cc["trend"]), width='stretch')
                if cc["first_fail_month"] is not None:
                    st.error(cc["note"])
                else:
                    st.success(cc["note"])
            else:
                st.info("💡 " + cc["note"])


# ----------------------------------------------------------------------------
# 横向比较（多研究/多批 同一检测项目叠加对比）
# ----------------------------------------------------------------------------
elif page == "横向比较":
    st.header("🔬 横向比较分析")
    st.caption("跨研究/跨批次对比同一检测项目的降解趋势与有效期，识别平台/工艺差异。")
    if not studies:
        st.info("请先创建研究。")
    else:
        sel_studies = st.multiselect("选择研究（可多选）",
                                     [f'{s["name"]} ({s["study_id"]})' for s in studies])
        attr = st.selectbox("对比检测项目", ATTRIBUTE_OPTIONS)
        if sel_studies:
            fig = go.Figure()
            comp_rows = []
            for label in sel_studies:
                sid = label.split("(")[-1].rstrip(")")
                st_obj = load_study_obj(sid)
                for s in st_obj.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        months, vals, _ = A._series_for(s, attr, cond)
                        if len(vals) >= 1:
                            fig.add_trace(go.Scatter(
                                x=months, y=vals, mode="markers+lines",
                                name=f"{st_obj.name[:8]}/{s.batch_id}/{cond}"))
                            reg = A.regression_summary(months, vals)
                            if reg and reg["n"] >= 2:
                                comp_rows.append({
                                    "研究": st_obj.name[:10], "批号": s.batch_id, "条件": cond,
                                    "斜率/月": round(reg["slope"], 4),
                                    "年降解率%": round(reg["rel_rate_pct_year"], 2) if not (isinstance(reg["rel_rate_pct_year"], float) and reg["rel_rate_pct_year"] != reg["rel_rate_pct_year"]) else None,
                                    "R²": round(reg["r2"], 3),
                                })
            fig.update_layout(title=f"横向对比 — {attr}", xaxis_title="时间(月)",
                              yaxis_title=attr, hovermode="x unified", height=420,
                              legend=dict(font=dict(size=8)))
            # R26：生物制品 CQA 综合稳定性雷达图（各研究多 CQA 终末保持率）
            radar_attrs = ["效价", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体"]
            radar_data = []
            for label in sel_studies:
                sid = label.split("(")[-1].rstrip(")")
                st_obj = load_study_obj(sid)
                if not st_obj.biologic:
                    continue
                # 取主要长期条件
                main_cond = next((c for c in ("冷藏", "冷冻-80", "长期") if any(
                    tp.condition == c for sm in st_obj.samples for tp in sm.time_points)), None)
                if not main_cond:
                    continue
                scores = []
                for a in radar_attrs:
                    series_vals = []
                    for sm in st_obj.samples:
                        m_, v_, _ = A._series_for(sm, a, main_cond)
                        if len(v_) >= 2:
                            series_vals.append(v_[-1])
                    if series_vals:
                        scores.append(round(float(np.mean(series_vals)), 1))
                    else:
                        scores.append(0.0)
                radar_data.append((st_obj.name[:10], scores))
            if radar_data:
                fig_radar = go.Figure()
                for name, scores in radar_data:
                    fig_radar.add_trace(go.Scatterpolar(r=scores + [scores[0]],
                                                        theta=radar_attrs + [radar_attrs[0]],
                                                        fill="toself", name=name))
                fig_radar.update_layout(title="生物制品 CQA 综合稳定性雷达（终末保持率，越高越好）",
                                        height=420)
                st.plotly_chart(fig_radar)
                st.caption("雷达图以各 CQA 在主要长期条件的终末观测值表示综合稳定性，仅生物制品研究参与。"
                           "聚集体/碎片/脱酰胺等以实测值（越低越好）展示，需结合限度解读。")
            st.plotly_chart(fig)
            if comp_rows:
                st.subheader("降解速率对比表")
                st.dataframe(pd.DataFrame(comp_rows), width='stretch')


# ----------------------------------------------------------------------------
# 质量告警（离群/缺失/非线性 自动扫描）
# ----------------------------------------------------------------------------
elif page == "质量告警":
    st.header("🚨 数据质量告警面板")
    st.caption("自动扫描全部研究的离群值、缺失时间点与非线性降解趋势。")
    if not studies:
        st.info("请先创建研究。")
    else:
        attrs_all = ATTRIBUTE_OPTIONS
        for s in studies:
            study = load_study_obj(s["study_id"])
            attrs = sorted({m.attribute for sm in study.samples for m in sm.measurements})
            issues = A.study_data_quality(study, attrs) if attrs else []
            # R21：计划月点未录入提醒（掉点预警）
            missing_rows = []
            for cond in set(tp.condition for sm in study.samples for tp in sm.time_points):
                planned = sorted({tp.month for sm in study.samples for tp in sm.time_points if tp.condition == cond})
                for attr in attrs:
                    miss = A.detect_missing(study.samples[0] if study.samples else None, cond, planned) if study.samples else []
                    # detect_missing 针对单 sample，改为跨批汇总
            # 正确的跨批缺失检测：
            missing_summary = []
            for sm in study.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    planned = sorted({tp.month for tp in sm.time_points if tp.condition == cond})
                    miss = A.detect_missing(sm, cond, planned)
                    for mm in miss:
                        missing_summary.append({"批号": sm.batch_id, "条件": cond, "缺失月点": mm})
            if missing_summary:
                st.warning(f"📅 【{study.name}】计划取样点未录入：共 {len(missing_summary)} 处（提示补测/确认掉点）。")
                with st.expander("查看缺失明细"):
                    st.dataframe(pd.DataFrame(missing_summary), width='stretch')
            if issues:
                st.subheader(f"⚠ {study.name} — {len(issues)} 项")
                st.dataframe(pd.DataFrame(issues), width='stretch')
            # R12：生物制品专属 CQA 显著变化告警
            if study.biologic:
                cqa_sig = []
                for attr in attrs:
                    for sm in study.samples:
                        for cond in set(tp.condition for tp in sm.time_points):
                            sc = A.biologic_significant_change(study, attr, cond)
                            if sc:
                                cqa_sig.append({"类型": "生物CQA显著变化(Q5C)", "批号": sc["batch"],
                                                "条件": cond, "CQA": attr,
                                                "月点": sc["month_of_change"], "变化%": sc["change_pct"],
                                                "结论": sc["conclusion"]})
                if cqa_sig:
                    st.subheader(f"🧬 {study.name} 生物制品 CQA 显著变化 — {len(cqa_sig)} 项")
                    st.dataframe(pd.DataFrame(cqa_sig), width='stretch')
        # 全库汇总
        total = sum(len(A.study_data_quality(load_study_obj(x["study_id"]),
                         sorted({m.attribute for sm in load_study_obj(x["study_id"]).samples for m in sm.measurements}))
                         if sorted({m.attribute for sm in load_study_obj(x["study_id"]).samples for m in sm.measurements}) else [])
                    for x in studies)
        if total == 0:
            st.success("✅ 全库未发现离群/缺失/非线性异常。")


# ----------------------------------------------------------------------------
# 生物制品 CQA 专项仪表
# ----------------------------------------------------------------------------
elif page == "生物CQA":
    st.header("🧬 生物制品 CQA 稳定性仪表")
    bio_studies = [s for s in studies if load_study_obj(s["study_id"]).biologic]
    if not bio_studies:
        st.info("暂无生物制品研究（创建时勾选『生物制品』）。")
    else:
        # R7：生物制品总览 —— 阶段分布 + DS-DP 关联
        st.subheader("① 生物制品研究总览")
        c1, c2 = st.columns([1, 1])
        with c1:
            stage_cnt = {}
            for s in bio_studies:
                st_obj = load_study_obj(s["study_id"])
                stage_cnt[st_obj.stage or "未指定"] = stage_cnt.get(st_obj.stage or "未指定", 0) + 1
            fig_pie = go.Figure(go.Pie(labels=list(stage_cnt.keys()), values=list(stage_cnt.values()),
                                       title="临床阶段分布"))
            fig_pie.update_layout(height=340)
            st.plotly_chart(fig_pie)
        with c2:
            st.markdown("**DS-DP 关联链路 (ICH Q5C)**")
            link_rows = []
            for s in bio_studies:
                st_obj = load_study_obj(s["study_id"])
                if st_obj.related_study_id:
                    link_rows.append({"本研究": st_obj.name, "关联类型": st_obj.related_study_type,
                                      "关联ID": st_obj.related_study_id})
            if link_rows:
                st.dataframe(pd.DataFrame(link_rows), width='stretch')
            else:
                st.caption("暂无关联（创建模板时可指定原液↔制剂联动）。")
        # 生物制品显著变化审计（所有生物CQA）
        st.subheader("② 生物制品显著变化速览 (ICH Q5C)")
        sig_rows = []
        for s in bio_studies:
            st_obj = load_study_obj(s["study_id"])
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    for attr in ["效价", "结合活性", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体", "糖基化"]:
                        r = A.biologic_significant_change(st_obj, attr, cond)
                        if r:
                            sig_rows.append({"研究": st_obj.name, "批号": r["batch"], "条件": cond,
                                             "CQA": attr, "月点": r["month_of_change"],
                                             "变化%": r["change_pct"], "结论": r["conclusion"]})
        if sig_rows:
            st.dataframe(pd.DataFrame(sig_rows), width='stretch')
        else:
            st.caption("当前生物制品数据未触发显著变化。")
        # R17：全 CQA 状态仪表（一屏总览该研究的各 CQA 最新状态）
        st.subheader("② 全 CQA 状态仪表")
        dash_sel = st.selectbox("选择生物制品研究（仪表）",
                                [f'{s["name"]} ({s["study_id"]})' for s in bio_studies], key="cqa_dash")
        dsid = dash_sel.split("(")[-1].rstrip(")")
        dstudy = load_study_obj(dsid)
        dash_rows = []
        for attr in BIO_CQA_ATTRS + ["含量", "有关物质", "pH", "渗透压", "水分", "不溶性微粒"]:
            present = any(m.attribute == attr for sm in dstudy.samples for m in sm.measurements)
            if not present:
                continue
            # 取长期条件终末值（最新月点均值）
            last_vals = []
            for sm in dstudy.samples:
                for tp in sm.time_points:
                    if tp.condition in (M.StorageCondition.LONG_TERM.value, "长期"):
                        for m in sm.measurements:
                            if m.attribute == attr and m.value is not None and float(m.time_point_id) == float(tp.month):
                                last_vals.append(m.value)
            cur = float(np.mean(last_vals)) if last_vals else None
            dl = M.default_limit_for(attr)
            status = "—"
            if cur is not None and dl:
                d, lim = dl
                if d == "lower" and cur < lim:
                    status = "❌低于下限"
                elif d == "upper" and cur > lim:
                    status = "❌高于上限"
                else:
                    status = "✅符合"
            dash_rows.append({
                "CQA": attr, "终末均值": round(cur, 2) if cur is not None else None,
                "限度": dl[1] if dl else None, "方向": dl[0] if dl else None, "状态": status,
            })
        if dash_rows:
            st.dataframe(pd.DataFrame(dash_rows), width='stretch')
        else:
            st.info("该研究无标准CQA数据。")
        sel = st.selectbox("选择生物制品研究", [f'{s["name"]} ({s["study_id"]})' for s in bio_studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        cqa_attrs = [a for a in BIO_CQA_ATTRS if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
        if not cqa_attrs:
            st.info("该研究的检测项目未包含标准CQA（效价/聚集体/碎片/脱酰胺/氧化/电荷异质体/糖基化）。")
        else:
            radar_r = {}
            for attr in cqa_attrs:
                # 用首批首条件做速率
                s0 = study.samples[0]
                cond = next((tp.condition for tp in s0.time_points), "")
                months, vals, _ = A._series_for(s0, attr, cond)
                if len(vals) >= 2:
                    reg = A.regression_summary(months, vals)
                    # 限度余量：当前值到限度的相对距离（越大越好）
                    lim = None
                    for m in s0.measurements:
                        if m.attribute == attr and m.limit_spec is not None:
                            lim = m.limit_spec; break
                    margin = 0
                    if lim is not None and vals[-1] != 0:
                        margin = abs(vals[-1] - lim) / abs(vals[-1]) * 100
                    radar_r[attr] = round(margin, 1)
            if radar_r:
                fig_r = go.Figure(go.Scatterpolar(
                    r=list(radar_r.values()) + [list(radar_r.values())[0]],
                    theta=list(radar_r.keys()) + [list(radar_r.keys())[0]],
                    fill="toself"))
                fig_r.update_layout(title="各CQA限度余量 (%)，越大越安全", height=420)
                st.plotly_chart(fig_r)
            st.subheader("CQA 降解速率汇总")
            rows = []
            for s in study.samples:
                for cond in set(tp.condition for tp in s.time_points):
                    for attr in cqa_attrs:
                        months, vals, _ = A._series_for(s, attr, cond)
                        if len(vals) >= 2:
                            reg = A.regression_summary(months, vals)
                            rows.append({"批号": s.batch_id, "条件": cond, "CQA": attr,
                                         "斜率/月": round(reg["slope"], 4),
                                         "年变化率%": round(reg["rel_rate_pct_year"], 2) if not (isinstance(reg["rel_rate_pct_year"], float) and reg["rel_rate_pct_year"] != reg["rel_rate_pct_year"]) else None,
                                         "R²": round(reg["r2"], 3)})
            if rows:
                st.dataframe(pd.DataFrame(rows), width='stretch')
            # R23：强制降解/应激 — 稳定性指示方法确证
            fd = A.forced_degradation_assessment(study)
            if fd:
                st.subheader("🔬 强制降解确证 (稳定性指示方法, ICH Q5C)")
                st.dataframe(pd.DataFrame(fd), width='stretch')
                if any(r["稳定性指示能力"] == "否(需复核方法/增加应激强度)" for r in fd):
                    st.warning("部分批/应力条件未产生降解信号，可能应激强度不足或方法不灵敏，"
                               "需复核方法以确保其具有稳定性指示能力(stability-indicating)。")
                # R33：应激强度等级建议
                weak = [r for r in fd if r.get("SIm确证", "").startswith("弱")]
                if weak:
                    st.info("💡 应激强度建议：对未产生降解信号的批，应提高应激强度（如升温/强酸强碱/"
                           "氧化/光照强化）直至产生可定量降解产物，以确证方法的稳定性指示能力。")
            # R8：矩阵/括号设计合规自检（Q1D）
            st.subheader("📐 设计合规自检 (ICH Q1D 矩阵/括号)")
            dc = A.matrix_bracket_compliance(study)
            for name, ok in dc["checks"]:
                st.write(("✅" if ok else "❌") + " " + name)
            if dc["issues"]:
                for iss in dc["issues"]:
                    st.error("⚠ " + iss)
            else:
                st.success(dc["note"])
            # R24：冻融循环 / 使用中(in-use) 专项分析
            special_conds = []
            for c in ("冻融循环", "使用中", "运输"):
                if any(tp.condition == c for sm in study.samples for tp in sm.time_points):
                    special_conds.append(c)
            if special_conds:
                st.subheader("❄ 冻融 / 使用中 / 运输 专项稳定性")
                sc_sel = st.selectbox("专项条件", special_conds, key="spec_cond")
                xlabel = "冻融循环次数" if sc_sel == "冻融循环" else ("复溶后天数" if sc_sel == "使用中" else "运输模拟")
                srows = []
                for sm in study.samples:
                    for m in sm.measurements:
                        if any(tp.condition == sc_sel and float(tp.month) == float(m.time_point_id) for tp in sm.time_points):
                            srows.append({"批号": sm.batch_id, "X(轴)": m.time_point_id,
                                          "检测项目": m.attribute, "数值": m.value,
                                          "单位": m.unit, "限度": m.limit_spec})
                if srows:
                    df_sp = pd.DataFrame(srows)
                    st.dataframe(df_sp, width='stretch')
                    # 趋势图（按批按CQA）
                    for attr in sorted(df_sp["检测项目"].unique()):
                        sub = df_sp[df_sp["检测项目"] == attr]
                        fig_sp = go.Figure()
                        for bid in sub["批号"].unique():
                            ss = sub[sub["批号"] == bid]
                            fig_sp.add_trace(go.Scatter(x=ss["X(轴)"], y=ss["数值"],
                                                       mode="lines+markers", name=bid))
                        fig_sp.update_layout(title=f"{attr} @ {sc_sel}", xaxis_title=xlabel, yaxis_title=attr)
                        st.plotly_chart(fig_sp)
                    st.caption(f"说明：{sc_sel} 条件以 {xlabel} 为横轴。冻融循环常见5次、使用中(in-use)"
                               "为复溶后至给药前允许天数、运输为模拟后单点评估。")
                    # R4/R5：冻融耐受次数 / 运输耐受判定
                    if sc_sel == "冻融循环":
                        ft_attrs = [a for a in df_sp["检测项目"].unique()
                                    if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
                        for attr in ft_attrs:
                            fr = A.freeze_thaw_assessment(study, attr)
                            if fr["status"] == "ok":
                                st.success(f"❄ {attr}：{fr['note']}")
                            elif fr["status"] == "limited":
                                st.warning(f"❄ {attr}：{fr['note']}")
                            elif fr["status"] == "fail":
                                st.error(f"❄ {attr}：{fr['note']}")
                            else:
                                st.info(f"❄ {attr}：{fr['note']}")
                    elif sc_sel == "运输":
                        tr_attrs = [a for a in df_sp["检测项目"].unique()
                                    if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
                        for attr in tr_attrs:
                            tr = A.transport_stress_assessment(study, attr)
                            if tr["status"] == "ok":
                                st.success(f"🚚 {attr}：{tr['note']}")
                            elif tr["status"] == "fail":
                                st.error(f"🚚 {attr}：{tr['note']}")
                            else:
                                st.info(f"🚚 {attr}：{tr['note']}")
                    # R32：冻融循环 vs CQA 相对变化图（每循环相对0月）
                    if sc_sel == "冻融循环":
                        ft_all = [a for a in df_sp["检测项目"].unique()
                                  if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
                        cycles = sorted({r["X(轴)"] for r in srows})
                        if cycles:
                            fig_ft = go.Figure()
                            for attr in ft_all:
                                rel = []
                                for cyc in cycles:
                                    vals_c = [r["数值"] for r in srows if r["检测项目"] == attr and r["X(轴)"] == cyc]
                                    vals_0 = [r["数值"] for r in srows if r["检测项目"] == attr and r["X(轴)"] == cycles[0]]
                                    base = float(np.mean(vals_0)) if vals_0 else None
                                    cur = float(np.mean(vals_c)) if vals_c else None
                                    rel.append((cur - base) / abs(base) * 100.0 if base else 0.0)
                                fig_ft.add_trace(go.Scatter(x=cycles, y=rel, mode="lines+markers", name=attr))
                            fig_ft.update_layout(title="冻融循环 CQA 相对变化 (%)", xaxis_title="冻融循环次数",
                                                 yaxis_title="相对0月变化%")
                            st.plotly_chart(fig_ft)


# ----------------------------------------------------------------------------
# 光稳定性（ICH Q1B）
# ----------------------------------------------------------------------------
elif page == "光稳定性":
    st.header("💡 光稳定性评估 (ICH Q1B)")
    st.markdown("ICH Q1B 要求对光照敏感药物（尤其生物制品的某些制剂、可见光/紫外敏感分子）进行光稳定性"
                "考察。常规暴露：**总照度≥1.2×10⁶ lux·hr，近紫外能量≥200 W·hr/m²**；强化暴露翻倍。"
                "本页比较各批 0 月对照与光照后 CQA，判定光照后是否仍在质量标准内。")
    # 已录入光照数据的研究
    photo_studies = []
    for s in studies:
        st_obj = load_study_obj(s["study_id"])
        if any(tp.condition == "光照" for sm in st_obj.samples for tp in sm.time_points):
            photo_studies.append(st_obj)
    if not photo_studies:
        st.info("暂无可进行光稳定性评估的研究（需在数据录入时为某批添加『光照』条件的时间点）。")
    else:
        sel = st.selectbox("选择研究", [f'{s.name} ({s.study_id})' for s in photo_studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        option = st.radio("Q1B 暴露选项", ["option1", "option2"],
                          format_func=lambda x: "选项1 常规(1.2M lux·hr)" if x == "option1"
                          else "选项2 强化(2.4M lux·hr)")
        c1, c2 = st.columns(2)
        with c1:
            lux_hr = st.number_input("实际总照度 (lux·hr)", min_value=0.0,
                                     value=float(M.PHOTO_Q1B_OPTION1["total_lux_hr"] if option == "option1"
                                                else M.PHOTO_Q1B_OPTION2["total_lux_hr"]), step=1e5)
        with c2:
            uv = st.number_input("实际近紫外能量 (W·hr/m²)", min_value=0.0,
                                 value=float(M.PHOTO_Q1B_OPTION1["uv_wh_m2"] if option == "option1"
                                            else M.PHOTO_Q1B_OPTION2["uv_wh_m2"]), step=10.0)
        attrs = [a for a in (BIO_CQA_ATTRS + ["含量", "有关物质", "pH"])
                 if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
        if not attrs:
            st.info("该研究检测项目中无可评估的质量属性。")
        else:
            # R31：暴露剂量计算器（照度 lux × 时长 h = lux·hr）
            with st.expander("🔦 暴露剂量计算器"):
                ic1, ic2 = st.columns(2)
                illum = ic1.number_input("光照度 (lux)", value=12000.0, min_value=0.0, step=500.0)
                hours = ic2.number_input("暴露时长 (小时)", value=100.0, min_value=0.0, step=1.0)
                calc_lux_hr = illum * hours
                uv_rate = st.number_input("近紫外功率密度 (W/m², 可选)", value=2.0, min_value=0.0, step=0.1)
                calc_uv = uv_rate * hours
                st.write(f"累计总照度 = **{calc_lux_hr:.3e} lux·hr**，近紫外 = **{calc_uv:.1f} W·hr/m²**")
                req1 = M.PHOTO_Q1B_OPTION1
                ok_l = calc_lux_hr >= req1["total_lux_hr"]
                ok_u = calc_uv >= req1["uv_wh_m2"]
                st.write("对照 Q1B 选项1：" + ("✅满足" if ok_l and ok_u else "❌不足"))
            attr = st.selectbox("评估质量属性", attrs)
            res = A.photostability_assessment(study, attr, option, lux_hr, uv)
            if res["exposure"]:
                ex = res["exposure"]
                if ex["ok"]:
                    st.success(f"光照暴露充足：总照度✓ 近紫外✓（要求 {ex['required']['total_lux_hr']:.1e} "
                               f"lux·hr / {ex['required']['uv_wh_m2']} W·hr/m²）")
                else:
                    st.warning(f"光照暴露不足：总照度{'✓' if ex['total_ok'] else '✗'} "
                               f"近紫外{'✓' if ex['uv_ok'] else '✗'}，需补足暴露后再评估。")
            if res["batches"]:
                st.subheader("批次光照前后对比")
                st.dataframe(pd.DataFrame(res["batches"]), width='stretch')
                # 柱状图：0月 vs 光照后
                fig_p = go.Figure()
                bids = [b["batch_id"] for b in res["batches"]]
                fig_p.add_trace(go.Bar(x=bids, y=[b["base"] for b in res["batches"]], name="0月对照"))
                fig_p.add_trace(go.Bar(x=bids, y=[b["photo"] for b in res["batches"]], name="光照后"))
                fig_p.update_layout(title=f"{attr}：0月 vs 光照后", barmode="group")
                st.plotly_chart(fig_p)
                if res["compliant"]:
                    st.success(res["note"])
                elif res["compliant"] is False:
                    st.error(res["note"])
            else:
                st.info(res["note"])
            # R43：批次配对 Δ% 汇总（光照后相对0月对照）
            if res.get("batches"):
                df_b = pd.DataFrame(res["batches"])
                if "rel_pct" in df_b.columns:
                    st.subheader("📊 光照诱导变化 Δ% 汇总")
                    st.dataframe(df_b[["batch_id", "base", "photo", "delta", "rel_pct", "over_limit"]],
                                 width='stretch')
                    st.caption("rel_pct = (光照后 - 0月对照)/0月对照 × 100%。正值=光照降解。")


# ----------------------------------------------------------------------------
# 统计汇总（全库概览指标）
# ----------------------------------------------------------------------------
elif page == "统计汇总":
    st.header("📊 全库统计汇总")
    if not studies:
        st.info("暂无研究。")
    else:
        n_study = len(studies)
        n_sample = 0
        n_meas = 0
        bio = 0
        cqa_rate = {}
        total_issue = 0
        attr_studies = {}  # R34：属性覆盖率
        for s in studies:
            st_obj = load_study_obj(s["study_id"])
            n_sample += len(st_obj.samples)
            for sm in st_obj.samples:
                n_meas += len(sm.measurements)
            if st_obj.biologic:
                bio += 1
            for attr in {m.attribute for sm in st_obj.samples for m in sm.measurements}:
                attr_studies.setdefault(attr, set()).add(s["study_id"])
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    for attr in {m.attribute for m in sm.measurements}:
                        months, vals, _ = A._series_for(sm, attr, cond)
                        if len(vals) >= 2:
                            reg = A.regression_summary(months, vals)
                            cqa_rate.setdefault(attr, []).append(reg["rel_rate_pct_year"])
            issues = A.study_data_quality(st_obj, sorted({m.attribute for sm in st_obj.samples for m in sm.measurements}))
            total_issue += len(issues)
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("研究数", n_study)
        col2.metric("样品数", n_sample)
        col3.metric("检测值数", n_meas)
        col4.metric("质量告警项", total_issue)
        st.subheader("生物制品占比")
        fig = go.Figure(go.Pie(labels=["化学药", "生物制品"], values=[n_study - bio, bio], hole=0.4))
        fig.update_layout(height=300)
        st.plotly_chart(fig)
        if cqa_rate:
            st.subheader("各检测项目平均年降解率 (%)")
            avg = {k: round(sum(v) / len(v), 2) for k, v in cqa_rate.items()}
            fig2 = go.Figure(go.Bar(x=list(avg.keys()), y=list(avg.values()),
                                    text=list(avg.values()), textposition="auto"))
            fig2.update_layout(height=320)
            st.plotly_chart(fig2)
        # R34：属性覆盖率（各检测项目在多少研究中被录入）
        if attr_studies:
            st.subheader("📋 检测项目覆盖率")
            cov_rows = [{"检测项目": a, "录入研究数": len(sids),
                         "覆盖率%": round(len(sids) / n_study * 100, 1)}
                        for a, sids in sorted(attr_studies.items(), key=lambda x: -len(x[1]))]
            st.dataframe(pd.DataFrame(cov_rows), width='stretch')
            st.caption("覆盖率低的项目提示录入不完整或方案设计差异。")
        # R10：全库批间合并 Bootstrap 置信区间 + 留一法稳健性（多批次研究）
        st.subheader("批间合并外推稳健性 (Bootstrap 95% CI / 留一法, ICH Q1E)")
        boot_rows = []
        for s in studies:
            st_obj = load_study_obj(s["study_id"])
            attrs_all = {m.attribute for sm in st_obj.samples for m in sm.measurements}
            for attr in attrs_all:
                # 取有数据的首个条件
                cond = None
                lim = None
                for sm in st_obj.samples:
                    for tp in sm.time_points:
                        if any(m.attribute == attr for m in sm.measurements if m.time_point_id == tp.tp_id):
                            cond = tp.condition
                            for m in sm.measurements:
                                if m.attribute == attr and m.limit_spec is not None:
                                    lim = m.limit_spec
                            break
                    if cond:
                        break
                if not cond or lim is None:
                    continue
                direction = "lower" if lim is not None and lim < (next((m.value for sm in st_obj.samples for m in sm.measurements if m.attribute == attr), 0)) else "upper"
                bs = A.pooled_bootstrap_ci(st_obj, attr, cond, lim, direction)
                lo = A.leave_one_out_expiry(st_obj, attr, cond, lim, direction)
                if bs and lo:
                    boot_rows.append({
                        "研究": st_obj.name, "条件": cond, "检测项目": attr,
                        "合并有效期(月)": bs["point_estimate"], "CI低": bs["ci_low"],
                        "CI高": bs["ci_high"], "CI宽度": bs["ci_width"], "批数": bs["n_batches"],
                        "留一法全批": lo["full_estimate"], "最大降幅": lo["max_drop"],
                        "外推稳健": "是" if lo["robust"] else "否",
                    })
        if boot_rows:
            st.dataframe(pd.DataFrame(boot_rows), width='stretch')
            st.caption("说明：Bootstrap 95% CI 反映多批次合并有效期的抽样不确定性；留一法最大降幅<20% 视为外推稳健。"
                       "非稳健项应增加批次或谨慎外推(Q1E)。")
        else:
            st.caption("暂无可计算的多批次合并稳健性（需≥2批次、≥3数据点且含限度）。")
        # R45：外推稳健性汇总表（跨研究）
        st.subheader("📐 外推稳健性汇总（跨研究）")
        robust_rows = []
        for s in studies:
            st_obj = load_study_obj(s["study_id"])
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    if cond not in (M.StorageCondition.LONG_TERM.value, "长期"):
                        continue
                    for attr in {m.attribute for m in sm.measurements}:
                        dl = M.default_limit_for(attr)
                        if not dl or len(st_obj.samples) < 2:
                            continue
                        try:
                            lo = A.leave_one_out_expiry(st_obj, attr, cond, dl[1], dl[0])
                            if lo and lo.get("replicate_expiries"):
                                spread = max(lo["replicate_expiries"]) - min(lo["replicate_expiries"])
                                robust_rows.append({
                                    "研究": st_obj.name, "批号": sm.batch_id, "条件": cond, "CQA": attr,
                                    "LOO外推(月)": round(lo.get("expiry_months", 0), 1),
                                    "稳健性": "稳健" if lo.get("robust") else "不稳健",
                                    "批间离散(月)": round(spread, 1),
                                })
                        except Exception:
                            continue
        if robust_rows:
            st.dataframe(pd.DataFrame(robust_rows), width='stretch')
            st.caption("稳健性=留一法各批外推差异小；不稳健提示需补充数据或逐批评估。")
        else:
            st.info("暂无可计算的跨研究外推稳健性（需≥2批含限度数据）。")
        # R18：计算引擎状态面板（标识已实现的统计/合规方法）
        with st.expander("🧮 计算引擎状态（已实现的统计与合规方法）"):
            engine = [
                ("线性回归 + 95% 单侧预测限有效期", "✅"),
                ("多模型选择（线性/指数/logistic AIC-BIC）", "✅"),
                ("Bootstrap 95% 置信区间（合并有效期）", "✅" if any(
                    A.pooled_bootstrap_ci(load_study_obj(s["study_id"]), attr, cond, 80.0, "lower")
                    for s in studies for cond in ["长期"] for attr in ["效价"]) else "⚠需数据"),
                ("留一法（LOO）外推稳健性", "✅"),
                ("MAD 稳健离群检测", "✅"),
                ("Arrhenius 温度外推", "✅"),
                ("批合并评估（Q1E poolability）", "✅"),
                ("方差分量 / ICC", "✅"),
                ("可比性等效性 90% CI (80-125%)", "✅"),
                ("光稳定性（Q1B）", "✅"),
                ("使用中/冻融/运输应激", "✅"),
                ("强制降解 SIm 确证", "✅"),
                ("Cpk 批间一致性", "✅"),
                ("CCIT 容器密封趋势", "✅"),
                ("审计链完整性校验（Part 11）", "✅"),
            ]
            st.table(pd.DataFrame(engine, columns=["方法", "状态"]))
        # R22：跨研究汇总导出
        if studies:
            all_objs = [load_study_obj(s["study_id"]) for s in studies]
            if st.button("导出跨研究汇总 Excel（总览/有效期/生物CQA/稳健性）"):
                xlsx = R.export_cross_study_summary(all_objs)
                st.download_button("下载跨研究汇总.xlsx", xlsx, "cross_study_summary.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ----------------------------------------------------------------------------
# 导出报告
# ----------------------------------------------------------------------------
elif page == "导出报告":
    st.header("📤 导出报告 (Excel / PDF)")
    if not check_perm("report:export"):
        st.error("权限不足：需 report:export。")
    elif not studies:
        st.info("请先创建研究。")
    else:
        sel = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        attrs = st.multiselect("纳入报告的检测项目", ATTRIBUTE_OPTIONS, default=["含量", "效价"])
        c1, c2 = st.columns(2)
        if c1.button("📊 导出 Excel", type="primary"):
            data = R.export_excel(study, attrs)
            AU.audit("REPORT_EXPORT", "study", sid, user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="Excel")
            st.download_button("下载 Excel", data, file_name=f"{study.name}_报告.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if c2.button("📄 导出 PDF", type="primary"):
            data = R.export_pdf(study, attrs)
            AU.audit("REPORT_EXPORT", "study", sid, user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="PDF")
            st.download_button("下载 PDF", data, file_name=f"{study.name}_报告.pdf",
                               mime="application/pdf")
        # R16：导出研究完整数据包 JSON（含计算结论，供 QA/申报）
        if st.button("🗂 导出研究数据包 (JSON, 含计算结论)"):
            data = R.export_study_json(study)
            AU.audit("REPORT_EXPORT", "study", sid, user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="JSON")
            st.download_button("下载 JSON 数据包", data, file_name=f"{study.name}_数据包.json",
                               mime="application/json")


# ----------------------------------------------------------------------------
# 设计建议
# ----------------------------------------------------------------------------
elif page == "设计建议":
    st.header("📐 稳定性研究设计建议")
    if not studies:
        st.info("请先创建研究。")
    else:
        sel = st.selectbox("选择研究", [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        st.info(P.design_advice(study))
        # R13：阶段合规清单对照 + DS-DP 关联提示
        try:
            import importlib
            T = importlib.import_module("teaching")
            ck = T.checklist_for(study.stage)
            if ck:
                st.subheader(f"📋 {study.stage or '通用'} 阶段合规清单自查")
                for i, item in enumerate(ck, 1):
                    st.markdown(f"{i}. {item}")
            if study.biologic and not study.related_study_id:
                st.warning("⚠ 该研究为生物制品但未设置关联研究(DS↔DP)。ICH Q5C 建议原液与制剂"
                           "稳定性联合评估，建议创建关联研究以建立联动。")
        except Exception:
            pass
        st.subheader("条件与温湿度规范")
        specs = {**P.condition_specs()}
        cond_list = (BIO_CONDITIONS if study.biologic else CHEM_CONDITIONS)
        for c in cond_list:
            if c in specs:
                st.markdown(f"- **{c}**：{specs[c]}")
        st.subheader("ICH 推荐时间点")
        from models import RECOMMENDED_TIME_POINTS, BIO_TIME_POINTS
        src = BIO_TIME_POINTS if study.biologic else RECOMMENDED_TIME_POINTS
        for c in M.StorageCondition:
            if c.value in cond_list and c in src:
                st.markdown(f"- **{c.value}**：{src[c]} 月")
        # 温湿度换算与货架建议
        st.subheader("温湿度换算与货架建议")
        cond_c = {
            "冷藏(2-8C)": ("2–8 °C", "35.6–46.4 °F", "需冷链(冷藏)，运输用保温箱+冰袋"),
            "冷冻(-20C)": ("-20 °C", "-4 °F", "需冷冻，避免反复冻融"),
            "冷冻(-80C)": ("-80 °C", "-112 °F", "超低温，液氮/超低温冰箱，仅长期储存"),
            "室温(25C)": ("25 °C", "77 °F", "常温储存，注意湿度(60±5% RH)"),
            "加速(40C)": ("40 °C", "104 °F", "加速试验，相对湿度75±5% RH"),
            "强光照射": ("光照≥120万lux或200万 lux·hr", "—", "ICH Q1B 光照试验"),
            "中间(30C)": ("30 °C", "86 °F", "温带气候带III/IVa长期条件"),
        }
        rows_c = []
        for c in cond_list:
            if c in cond_c:
                cmin, f, shelf = cond_c[c]
                rows_c.append({"条件": c, "温度(℃)": cmin, "温度(℉)": f, "货架/运输建议": shelf})
        if rows_c:
            st.dataframe(pd.DataFrame(rows_c), width='stretch')
        st.caption("说明：℃↔℉ 换算 F=℃×9/5+32。长期/加速条件相对湿度要求见 ICH Q1A(R2) "
                   "（长期 25°C/60%RH 或 30°C/65%RH；加速 40°C/75%RH）。")
        if study.biologic:
            st.subheader("生物制品稳定性要点 (ICH Q5C)")
            st.markdown("""
            - **核心CQA**：效价、聚集体(高分子量物质)、碎片、脱酰胺、氧化、电荷异质体、糖基化、不溶性微粒、可见异物、pH、水分。
            - **降解多非线性**：聚集体/碎片常呈S型增长，线性外推偏乐观，建议增加时间点或采用非线性模型。
            - **条件选择**：多数生物制品长期条件为冷藏(2–8°C)，冻存(-20/-80°C)用于质粒/细胞/病毒载体。
            - **效价**为关键指标，通常以相对标示量的百分比表示，限度常设≥80%。
            - 参考 ICH Q5C / Q6B，并结合产品特异性降解途径设计检测矩阵。
            """)
        # R20：Arrhenius 加速→长期换算提示（若有加速条件）
        if "加速" in cond_list:
            st.subheader("加速→长期降解速率换算 (Arrhenius, 初筛提示)")
            # 以含量/效价在加速与长期的斜率比粗略估算；此处给通用说明+示例
            st.caption("若已知加速条件(40°C)与长期条件(25°C/冷藏)的降解速率常数，可用 Arrhenius 估算倍率。"
                       "示例：Ea=80 kJ/mol 时，40°C 降解速率约为 25°C 的 ~6.5 倍、约为 5°C(冷藏)的 ~25 倍。"
                       "⚠ 生物制品高温可能改变降解机制，加速数据不可直接换算长期有效期，须经真实长期数据确证(Q5C)。")
        st.markdown("---")
        st.caption("本系统为研究管理与分析辅助工具，有效期结论需由授权人员结合全部CQA、"
                   "包装、规模等因素综合判定，并符合21 CFR Part 11 / 数据完整性要求。")


# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# 可比性研究（变更前后 / 类似药对比, ICH Q5C 可比性）
# ----------------------------------------------------------------------------
elif page == "可比性":
    st.header("🔗 可比性研究 (Comparability, ICH Q5C)")
    st.caption("用于工艺变更、场地转移、生物类似药等场景：对比变更前后稳定性 CQA 漂移，"
               "判断是否等效。判定基于各 CQA 在共同时间点的最小二乘均值差(Δ)与等效接受范围。")
    if len(studies) < 2:
        st.info("可比性研究需至少 2 个研究用于对比。")
    else:
        col_a, col_b = st.columns(2)
        opts = [f'{s["name"]} ({s["study_id"]})' for s in studies]
        sa = col_a.selectbox("研究A（变更前/参比）", opts, key="cmp_a")
        sb = col_b.selectbox("研究B（变更后/候选）", opts, index=min(1, len(opts) - 1), key="cmp_b")
        sid_a = sa.split("(")[-1].rstrip(")")
        sid_b = sb.split("(")[-1].rstrip(")")
        st_a, st_b = load_study_obj(sid_a), load_study_obj(sid_b)
        attrs = sorted(set(m.attribute for sm in st_a.samples for m in sm.measurements)
                       | set(m.attribute for sm in st_b.samples for m in sm.measurements))
        attr = st.selectbox("对比 CQA", attrs)
        cond = st.selectbox("对比条件", sorted(set(tp.condition for sm in st_a.samples for tp in sm.time_points)
                                               & set(tp.condition for sm in st_b.samples for tp in sm.time_points)))
        # 等效接受范围（相对初始±10% 默认，生物制品效价±10%）
        accept = st.number_input("等效接受范围(Δ%, 相对初始)", value=10.0, step=1.0)
        # 取两研究共同月点
        months_a = {tp.month for sm in st_a.samples for tp in sm.time_points if tp.condition == cond}
        months_b = {tp.month for sm in st_b.samples for tp in sm.time_points if tp.condition == cond}
        common = sorted(months_a & months_b)
        if not common:
            st.warning("两研究在该条件无共同月点，无法可比性分析。")
        else:
            # 各研究共同月点的批均值
            def batch_mean_at(study, mo):
                vals = []
                for sm in study.samples:
                    for m in sm.measurements:
                        if m.attribute == attr and m.time_point_id == mo:
                            vals.append(m.value)
                return float(np.mean(vals)) if vals else None
            ma = [batch_mean_at(st_a, mo) for mo in common]
            mb = [batch_mean_at(st_b, mo) for mo in common]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=common, y=ma, mode="lines+markers", name=st_a.name))
            fig.add_trace(go.Scatter(x=common, y=mb, mode="lines+markers", name=st_b.name))
            fig.update_layout(title=f"{attr} @ {cond} 可比性趋势", xaxis_title="月", yaxis_title=attr)
            st.plotly_chart(fig)
            # Δ 与等效判定
            deltas = [(mb[i] - ma[i]) if (ma[i] is not None and mb[i] is not None) else None for i in range(len(common))]
            max_abs = max([abs(d) for d in deltas if d is not None]) if deltas else 0
            equiv = max_abs <= accept
            st.subheader("可比性结论")
            res = pd.DataFrame({"月点": common, "研究A均值": ma, "研究B均值": mb, "Δ(B-A)": deltas})
            st.dataframe(res, width='stretch')
            if equiv:
                st.success(f"✅ CQA『{attr}』在 {cond} 下最大漂移 {max_abs:.2f}% ≤ 接受范围 {accept:.0f}%，"
                           f"支持可比性（变更前后等效）。")
            else:
                st.error(f"❌ 最大漂移 {max_abs:.2f}% > 接受范围 {accept:.0f}%，"
                         f"不可比，需补充稳定性或重新论证。")
            # R9：规范等效性 (90% CI 落在 80-125%)，以比例 B/A 计（生物类似药常见 TOST 准则）
            eq = A.comparability_equivalence(st_a, st_b, attr, cond)
            if eq["n"] >= 1:
                st.subheader("📐 等效性统计 (90% CI, 接受区间 80–125%)")
                st.write(f"共同时间点 n={eq['n']}，B/A 比例均值={eq['mean_ratio']*100:.1f}%，"
                         f"90% CI=[{eq['ci_low']*100:.1f}%, {eq['ci_high']*100:.1f}%]")
                if eq["equivalent"]:
                    st.success("比例 90% CI 完全落在 80–125% 接受区间内，支持等效性（TOST 准则）。")
                else:
                    st.warning("比例 90% CI 超出 80–125% 接受区间，尚不支持常规等效性，"
                               "需更多数据或采用临床桥接论证。")
            # R30：可比性漂移热图（各 CQA × 各条件 的 B-A 相对漂移）
            heat_attrs = sorted(set(m.attribute for sm in st_a.samples for m in sm.measurements)
                                | set(m.attribute for sm in st_b.samples for m in sm.measurements))
            heat_conds = sorted(set(tp.condition for sm in st_a.samples for tp in sm.time_points)
                                & set(tp.condition for sm in st_b.samples for tp in sm.time_points))
            if heat_attrs and heat_conds:
                z, yl = [], []
                for ha in heat_attrs:
                    row = []
                    for hc in heat_conds:
                        da = [m.value for sm in st_a.samples for m in sm.measurements
                              if m.attribute == ha and m.value is not None
                              and any(tp.condition == hc and float(tp.month) == float(m.time_point_id) for tp in sm.time_points)]
                        db = [m.value for sm in st_b.samples for m in sm.measurements
                              if m.attribute == ha and m.value is not None
                              and any(tp.condition == hc and float(tp.month) == float(m.time_point_id) for tp in sm.time_points)]
                        if da and db:
                            drift = (np.mean(db) - np.mean(da)) / abs(np.mean(da)) * 100.0
                        else:
                            drift = 0.0
                        row.append(round(drift, 2))
                    z.append(row)
                    yl.append(ha)
                fig_h = go.Figure(go.Heatmap(z=z, x=heat_conds, y=yl, colorscale="RdBu", zmid=0,
                                             text=[[f"{v:.1f}%" for v in row] for row in z],
                                             texttemplate="%{text}"))
                fig_h.update_layout(title="可比性漂移热图 (%): B-A / A", height=max(300, 40 * len(yl) + 120))
                st.plotly_chart(fig_h)
                st.caption("红=B高于A，蓝=B低于A；数值为批均值相对漂移幅度。")
            # R44：各条件 B-A 绝对差异柱状图
            bar_attrs = sorted(set(m.attribute for sm in st_a.samples for m in sm.measurements)
                               | set(m.attribute for sm in st_b.samples for m in sm.measurements))
            if bar_attrs and heat_conds:
                fig_bar = go.Figure()
                for hc in heat_conds:
                    diffs = []
                    for ha in bar_attrs:
                        da = [m.value for sm in st_a.samples for m in sm.measurements
                              if m.attribute == ha and m.value is not None
                              and any(tp.condition == hc and float(tp.month) == float(m.time_point_id) for tp in sm.time_points)]
                        db = [m.value for sm in st_b.samples for m in sm.measurements
                              if m.attribute == ha and m.value is not None
                              and any(tp.condition == hc and float(tp.month) == float(m.time_point_id) for tp in sm.time_points)]
                        if da and db:
                            diffs.append(np.mean(db) - np.mean(da))
                        else:
                            diffs.append(0.0)
                    fig_bar.add_trace(go.Bar(x=bar_attrs, y=diffs, name=hc))
                fig_bar.update_layout(title="可比性 B-A 绝对差异 (各条件)", barmode="group",
                                      yaxis_title="B均值 - A均值")
                st.plotly_chart(fig_bar)


# 审计日志
# ----------------------------------------------------------------------------
elif page == "审计日志":
    st.header("🛡 审计日志 (21 CFR Part 11)")
    st.caption("审计记录仅追加、不可修改/删除，包含操作人、时间(UTC)、IP、会话、前/后值。")
    logs = AU.read_audit(limit=2000)
    if logs:
        df = pd.DataFrame(logs)
        # 筛选
        users = ["全部"] + sorted(df["username"].unique().tolist())
        actions = ["全部"] + sorted(df["action"].unique().tolist())
        c1, c2 = st.columns(2)
        fu = c1.selectbox("按用户筛选", users)
        fa = c2.selectbox("按动作筛选", actions)
        df_f = df.copy()
        if fu != "全部":
            df_f = df_f[df_f["username"] == fu]
        if fa != "全部":
            df_f = df_f[df_f["action"] == fa]
        show_cols = ["ts", "username", "role", "action", "object_type", "object_id", "ip", "note"]
        show_cols = [c for c in show_cols if c in df_f.columns]
        st.dataframe(df_f[show_cols], width='stretch')
        # 导出 CSV
        csv = df_f[show_cols].to_csv(index=False).encode("utf-8-sig")
        st.download_button("导出筛选后审计日志 (CSV)", csv, "audit_log.csv", "text/csv")
        # R13：审计完整性校验（防篡改哈希链）
        if st.button("🔐 校验审计链完整性 (21 CFR Part 11)"):
            integ = AU.verify_audit_integrity()
            if integ["ok"]:
                st.success(f"✅ 审计链完整：共 {integ['total']} 条记录，未检测到篡改。")
            else:
                st.error(f"❌ 审计链在记录 {integ['broken_at']} 处断裂，疑似被篡改！")
        with st.expander("查看某条记录的前/后值(JSON)"):
            opts = [f'{l["ts"]} {l["username"]} {l["action"]}' for l in logs]
            idx = st.selectbox("选择记录", opts)
            rec = next(l for l in logs if f'{l["ts"]} {l["username"]} {l["action"]}' == idx)
            st.json({"before": rec.get("before_val"), "after": rec.get("after_val")})
    else:
        st.info("暂无审计记录。")


# ----------------------------------------------------------------------------
# 用户管理
# ----------------------------------------------------------------------------
elif page == "用户管理":
    st.header("👥 用户管理")
    if not check_perm("user:manage"):
        st.error("权限不足：需 user:manage。")
    else:
        with st.form("add_user"):
            nu = st.text_input("新用户名")
            npw = st.text_input("初始密码", type="password")
            nn = st.text_input("姓名")
            nr = st.selectbox("角色", [r for r in AU.ROLE_LABELS if r != "admin"] + ["admin"])
            if st.form_submit_button("创建用户"):
                if AU.create_user(nu, npw, nn, nr, operator=user["username"]):
                    AU.audit("USER_CREATE", "user", nu, user["username"], role,
                             st.session_state.client_ip, st.session_state.session_id, note=f"role={nr}")
                    st.success(f"已创建用户 {nu}（{AU.ROLE_LABELS.get(nr, nr)}）")
                else:
                    st.error("创建失败（用户名可能已存在）。")
        st.subheader("现有用户")
        us = AU.list_users()
        if us:
            df = pd.DataFrame(us)
            st.dataframe(df, width='stretch')
            dis = st.selectbox("禁用/启用用户", [u["username"] for u in us if u["username"] != user["username"]])
            c1, c2 = st.columns(2)
            if c1.button("禁用"):
                AU.set_enabled(dis, False)
                AU.audit("USER_DISABLE", "user", dis, user["username"], role,
                         st.session_state.client_ip, st.session_state.session_id)
                st.rerun()
            if c2.button("启用"):
                AU.set_enabled(dis, True)
                AU.audit("USER_ENABLE", "user", dis, user["username"], role,
                         st.session_state.client_ip, st.session_state.session_id)
                st.rerun()


# ----------------------------------------------------------------------------
# 系统维护（管理员）
# ----------------------------------------------------------------------------
elif page == "系统维护":
    st.header("🛠 系统维护 / 数据备份恢复")
    if not (user and user.get("role") == "admin"):
        st.error("权限不足：需管理员。")
    else:
        st.subheader("整库备份")
        if st.button("生成整库备份 (JSON)"):
            data = DB.export_all_json()
            st.download_button("下载备份文件", data.encode("utf-8"),
                               "stability_backup.json", "application/json")
        st.subheader("整库恢复")
        st.warning("⚠ 恢复将覆盖/追加数据库内容，操作前请先备份！")
        up = st.file_uploader("上传备份 JSON", type=["json"], key="restore")
        merge = st.checkbox("合并模式（仅追加不存在的研究，不清空现有数据）", value=True)
        # 电子签名：恢复为关键操作，须重新输入口令
        reauth_pw = st.text_input("请输入您的登录口令以确认恢复（电子签名）", type="password", key="restore_pw")
        if up and st.button("执行恢复"):
            if not AU.reauthenticate(user["username"], reauth_pw):
                st.error("口令错误，未执行恢复。（错误次数计入锁定策略）")
            else:
                try:
                    data = up.getvalue().decode("utf-8")
                    DB.import_all_json(data, merge=merge)
                    AU.audit("DB_RESTORE", "system", "all", user["username"], role,
                             st.session_state.client_ip, st.session_state.session_id,
                             note=f"merge={merge}")
                    AU.e_signature("ALL", "DB_RESTORE", user.get("name") or user["username"], role,
                                   f"整库恢复（merge={merge}）", username=user["username"],
                                   ip=st.session_state.client_ip)
                    st.success("恢复完成。")
                    st.rerun()
                except Exception as e:
                    st.error(f"恢复失败：{e}")
        # R29：法规符合性自检
        st.subheader("🔍 法规符合性自检")
        checks = []
        total_studies = len(studies)
        bio_n = sum(1 for s in studies if load_study_obj(s["study_id"]).biologic)
        bio_no_rel = sum(1 for s in studies if load_study_obj(s["study_id"]).biologic
                         and not load_study_obj(s["study_id"]).related_study_id)
        no_limit = 0
        for s in studies:
            st_obj = load_study_obj(s["study_id"])
            has_limit = any(m.limit_spec is not None for sm in st_obj.samples for m in sm.measurements)
            if any(sm.measurements for sm in st_obj.samples) and not has_limit:
                no_limit += 1
        audits = AU.read_audit(limit=100000)
        covered = sum(1 for s in studies if any(a.get("entity_id") == s["study_id"] for a in audits))
        audit_cov = round(covered / total_studies * 100, 1) if total_studies else 100
        checks.append({"项目": "研究总数", "状态": str(total_studies), "说明": "—"})
        checks.append({"项目": "生物制品研究", "状态": str(bio_n), "说明": "ICH Q5C 适用"})
        checks.append({"项目": "生物制品未设 DS-DP 关联", "状态": str(bio_no_rel),
                       "说明": "建议建立原液↔制剂联动" if bio_no_rel else "已全覆盖"})
        checks.append({"项目": "有数据但缺限度研究", "状态": str(no_limit),
                       "说明": "需设定质量标准限度以推算有效期" if no_limit else "已全覆盖"})
        checks.append({"项目": "审计覆盖率", "状态": f"{audit_cov}%",
                       "说明": "21 CFR Part 11 可追溯" if audit_cov >= 80 else "覆盖率偏低，建议核查"})
        df_ck = pd.DataFrame(checks)
        st.dataframe(df_ck, width='stretch')
        if st.button("导出符合性自检报告 (CSV)"):
            csv = df_ck.to_csv(index=False).encode("utf-8")
            st.download_button("下载自检报告.csv", csv, "compliance_selfcheck.csv", "text/csv")


# ----------------------------------------------------------------------------
# 教学指南（学习模式 / 教学版本）
# ----------------------------------------------------------------------------
elif page == "教学指南":
    st.header("📚 稳定性研究教学指南 (学习模式)")
    st.caption("本页提供法规术语、阶段合规清单与常见误区，供学习与方案自查。法规依据："
               "ICH Q1A/Q1E/Q1D/Q5C/Q6B、NMPA 生物制品指导原则、21 CFR Part 11、USP <1049>。")
    import importlib
    if "src" not in sys.path:
        sys.path.insert(0, "src")
    T = importlib.import_module("teaching")
    tab_g, tab_c, tab_p, tab_q = st.tabs(["术语表", "阶段合规清单", "常见误区", "自测题"])
    with tab_g:
        q = st.text_input("搜索术语", "")
        items = {k: v for k, v in T.GLOSSARY.items() if not q or q.lower() in k.lower() or q.lower() in v.lower()}
        for k, v in items.items():
            st.markdown(f"**{k}**：{v}")
    with tab_c:
        stage_sel = st.selectbox("选择开发阶段", list(T.CHECKLISTS.keys()))
        chk = T.checklist_for(stage_sel)
        # R23：可勾选交互 + 完成度
        done_key = f"chk_{stage_sel}"
        if done_key not in st.session_state:
            st.session_state[done_key] = set()
        cols = st.columns(2)
        for i, item in enumerate(chk, 1):
            checked = st.checkbox(f"{i}. {item}", value=(i in st.session_state[done_key]), key=f"c_{stage_sel}_{i}")
            if checked:
                st.session_state[done_key].add(i)
            else:
                st.session_state[done_key].discard(i)
        total = len(chk)
        done = len(st.session_state[done_key])
        st.progress(done / total if total else 0)
        st.caption(f"完成度：{done}/{total}（勾选项仅会话内有效，用于自查练习）")
        st.info("提示：在研究管理中创建研究时选择对应临床阶段，可在『生物CQA』页对照本清单自查。")
    with tab_p:
        for i, item in enumerate(T.PITFALLS, 1):
            st.markdown(f"{i}. {item}")
    # R40：常见误区自测 quiz
    with tab_q:
        st.caption("自测题（仅学习用，勾选后显示答案与解析）：")
        for i, q in enumerate(T.QUIZ):
            st.subheader(f"Q{i+1}. {q['q']}")
            choice = st.radio("选择", q["options"], key=f"quiz_{i}")
            if st.button(f"显示答案 Q{i+1}", key=f"qa_{i}"):
                correct = (choice.startswith(q["answer"]))
                if correct:
                    st.success(f"✅ 正确！答案：{q['answer']}。{q['explain']}")
                else:
                    st.error(f"❌ 错误。正确答案：{q['answer']}。{q['explain']}")

UI.footer()
