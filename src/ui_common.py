"""界面公共工具：常量、研究加载、数据持久化与权限检查（由 app.py 拆分而来）。"""

import json
import streamlit as st
from i18n import t
import plotly.graph_objects as go
from typing import Dict, List, Optional
import numpy as np
import scipy.stats as stats
import models as M
import planner as P
import analysis as A
import db as DB
import auth as AU

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

def current_role() -> str:
    """当前登录用户的角色（未登录时为 viewer，最低权限）。"""
    user = st.session_state.get("user") or {}
    return user.get("role", "viewer")


def check_perm(perm: str) -> bool:
    return AU.has_permission(current_role(), perm)


def require(perm: str):
    if not check_perm(perm):
        st.error(t("权限不足：当前角色无权执行此操作。"))
        st.stop()
