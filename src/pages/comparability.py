"""可比性研究页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import analysis as A
from ui_common import load_study_obj


def render(ctx):
    studies = ctx["studies"]

    st.header(t("🔗 可比性研究 (Comparability, ICH Q5C)"))
    st.caption(t("用于工艺变更、场地转移、生物类似药等场景：对比变更前后稳定性 CQA 漂移，判断是否等效。判定基于各 CQA 在共同时间点的最小二乘均值差(Δ)与等效接受范围。"))
    if len(studies) < 2:
        st.info(t("可比性研究需至少 2 个研究用于对比。"))
    else:
        col_a, col_b = st.columns(2)
        opts = [f'{s["name"]} ({s["study_id"]})' for s in studies]
        sa = col_a.selectbox(t("研究A（变更前/参比）"), opts, key="cmp_a")
        sb = col_b.selectbox(t("研究B（变更后/候选）"), opts, index=min(1, len(opts) - 1), key="cmp_b")
        sid_a = sa.split("(")[-1].rstrip(")")
        sid_b = sb.split("(")[-1].rstrip(")")
        st_a, st_b = load_study_obj(sid_a), load_study_obj(sid_b)
        attrs = sorted(set(m.attribute for sm in st_a.samples for m in sm.measurements)
                       | set(m.attribute for sm in st_b.samples for m in sm.measurements))
        attr = st.selectbox(t("对比 CQA"), attrs, format_func=t)
        cond = st.selectbox(t("对比条件"), sorted(set(tp.condition for sm in st_a.samples for tp in sm.time_points)
                                               & set(tp.condition for sm in st_b.samples for tp in sm.time_points)), format_func=t)
        # 等效接受范围（相对初始±10% 默认，生物制品效价±10%）
        accept = st.number_input(t("等效接受范围(Δ%, 相对初始)"), value=10.0, step=1.0)
        # 取两研究共同月点
        months_a = {tp.month for sm in st_a.samples for tp in sm.time_points if tp.condition == cond}
        months_b = {tp.month for sm in st_b.samples for tp in sm.time_points if tp.condition == cond}
        common = sorted(months_a & months_b)
        if not common:
            st.warning(t("两研究在该条件无共同月点，无法可比性分析。"))
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
            st.subheader(t("可比性结论"))
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
                st.subheader(t("📐 等效性统计 (90% CI, 接受区间 80–125%)"))
                st.write(f"共同时间点 n={eq['n']}，B/A 比例均值={eq['mean_ratio']*100:.1f}%，"
                         f"90% CI=[{eq['ci_low']*100:.1f}%, {eq['ci_high']*100:.1f}%]")
                if eq["equivalent"]:
                    st.success(t("比例 90% CI 完全落在 80–125% 接受区间内，支持等效性（TOST 准则）。"))
                else:
                    st.warning(t("比例 90% CI 超出 80–125% 接受区间，尚不支持常规等效性，需更多数据或采用临床桥接论证。"))
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
                st.caption(t("红=B高于A，蓝=B低于A；数值为批均值相对漂移幅度。"))
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
