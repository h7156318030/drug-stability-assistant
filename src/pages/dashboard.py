"""仪表盘页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime
import numpy as np
import models as M
import planner as P
import analysis as A
from ui_common import dashboard_aggregate, load_study_obj


def render(ctx):
    user = ctx["user"]
    studies = ctx["studies"]

    st.header(t("📊 稳定性研究仪表盘"))
    with st.expander(t("💡 使用提示（学习模式）"), expanded=False):
        st.markdown(t("本系统支持生物制品(ICH Q5C/Q6B)全流程稳定性研究：**原液(DS)/制剂(DP)联动、强制降解、冻融循环、使用中(in-use)、运输稳定性**，并提供显著变化专属阈值(效价>10%)、批间合并 Bootstrap 置信区间、留一法稳健性、多模型 AIC/BIC 选择。建议新用户先到『教学指南』页学习法规术语与合规清单，再到『研究管理』加载教学示例。"))
    if not studies:
        st.info(t("暂无研究数据。"))
    else:
        df_idx = pd.DataFrame(studies)
        agg = dashboard_aggregate(user["username"])  # R49：缓存聚合
        col1, col2, col3, col4 = st.columns(4)
        col1.metric(t("研究总数"), agg["n_study"])
        col2.metric(t("样品总数"), agg["n_sample"])
        col3.metric(t("生物制品研究"), agg["bio"])
        # R25：生物CQA显著变化数（全库）
        bio_sig_n = agg["bio_sig_n"]
        col4.metric(t("生物CQA显著变化"), bio_sig_n)
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
            st.subheader(t("🟢 生物 CQA 合格率"))
            st.progress(rate)
            st.caption(t("合格（无显著变化）{0}/{1} = {2:.0f}%").format(cqa_pass, cqa_total, rate*100))
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
            st.warning(t("⏰ 近期到期预警（推算有效期≤18月）：{0} 项").format(len(expiring)))
            with st.expander(t("查看明细")):
                st.dataframe(pd.DataFrame(expiring), width='stretch')
        # 阶段分布（仅生物制品）
        bio_studies = [s for s in studies if load_study_obj(s["study_id"]).biologic]
        if bio_studies:
            c1, c2 = st.columns(2)
            with c1:
                st.subheader(t("生物制品临床阶段分布"))
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
            st.subheader(t("研究类型分布"))
            types = df_idx["study_type"].value_counts() if "study_type" in df_idx else pd.Series(dtype=int)
            if not types.empty:
                fig_t = go.Figure(go.Pie(labels=types.index.tolist(), values=types.values.tolist(), hole=0.4))
                fig_t.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_t)
            else:
                st.caption(t("无数据"))
        with c2:
            st.subheader(t("化学药 / 生物制品占比"))
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
            st.subheader(t("未来90天待取样（按月）"))
            mc = pd.Series(plan_rows).value_counts().sort_index()
            fig_m = go.Figure(go.Bar(x=[f"{m}月" for m in mc.index], y=mc.values.tolist()))
            fig_m.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_m)
        st.subheader(t("研究列表"))
        cols = ["study_id", "name", "drug_name", "study_type", "design",
                "biologic", "molecule_type", "start_date", "updated_at"]
        cols = [c for c in cols if c in df_idx.columns]
        st.dataframe(df_idx[cols], width='stretch')
        st.subheader(t("近期取样计划（未来90天）"))
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
            st.caption(t("未来90天无待取样计划。"))


# ----------------------------------------------------------------------------
# 研究管理
# ----------------------------------------------------------------------------
