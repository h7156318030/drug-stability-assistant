"""横向比较页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import analysis as A
from ui_common import ATTRIBUTE_OPTIONS, load_study_obj


def render(ctx):
    name = ctx["name"]
    studies = ctx["studies"]

    st.header(t("🔬 横向比较分析"))
    st.caption(t("跨研究/跨批次对比同一检测项目的降解趋势与有效期，识别平台/工艺差异。"))
    if not studies:
        st.info(t("请先创建研究。"))
    else:
        sel_studies = st.multiselect(t("选择研究（可多选）"),
                                     [f'{s["name"]} ({s["study_id"]})' for s in studies])
        attr = st.selectbox(t("对比检测项目"), ATTRIBUTE_OPTIONS, format_func=t)
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
                st.caption(t("雷达图以各 CQA 在主要长期条件的终末观测值表示综合稳定性，仅生物制品研究参与。聚集体/碎片/脱酰胺等以实测值（越低越好）展示，需结合限度解读。"))
            st.plotly_chart(fig)
            if comp_rows:
                st.subheader(t("降解速率对比表"))
                st.dataframe(pd.DataFrame(comp_rows), width='stretch')


# ----------------------------------------------------------------------------
# 质量告警（离群/缺失/非线性 自动扫描）
# ----------------------------------------------------------------------------
