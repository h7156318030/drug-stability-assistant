"""降解趋势分析与时序图页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import scipy.stats as stats
import models as M
import analysis as A
from ui_common import ATTRIBUTE_OPTIONS, load_study_obj, render_interactive_trend


def render(ctx):
    studies = ctx["studies"]

    st.header(t("📈 降解趋势分析"))
    if not studies:
        st.info(t("请先创建研究。"))
    else:
        sel = st.selectbox(t("选择研究"), [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        attrs = st.multiselect(t("检测项目"), ATTRIBUTE_OPTIONS, default=["含量", "效价"], format_func=t)
        if attrs:
            res = A.analyze_study(study, attrs)
            if res:
                st.dataframe(pd.DataFrame(res), width='stretch')
                # 限度选择（用于趋势图标示）
                lim_attr = st.selectbox(t("在图中标示限度（可选）"), [""] + attrs, format_func=t)
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
                            st.caption(t("🔬 {0}：{1}").format(c, M.SPECIAL_CONDITION_DESC[c]))
                st.subheader(t("交互式趋势图（可缩放/悬浮）"))
                for attr in attrs:
                    render_interactive_trend(study, attr, lim_val if attr == lim_attr else None, lim_dir)
                # R36：异常点标注（MAD 稳健离群检测高亮）
                st.subheader(t("🔍 异常点标注 (MAD 离群检测)"))
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
                        st.warning(t("『{0}』检出 {1} 个疑似离群点（MAD z>3.5）：").format(attr, len(outlier_rows)))
                        st.dataframe(pd.DataFrame(outlier_rows), width='stretch')
                    else:
                        st.caption(t("『{0}』未检出显著离群点。").format(attr))
                import matplotlib.pyplot as plt
                st.subheader(t("静态趋势图（备用）"))
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
                st.info(t("暂无足够数据（每序列需≥2个点）。"))
            # R26：数据质量评分（study_data_quality 可视化）
            if study.samples:
                q = A.study_data_quality(study, attrs)
                score, n_issues = A.data_quality_score(q)
                st.subheader(t("🏅 数据质量评分"))
                st.progress(score / 100.0)
                st.caption(t("质量分：{0}/100（启发式：每个问题扣 5 分，仅供内部排查，不是法规指标），问题数：{1}").format(score, n_issues))
                if q:
                    with st.expander(t("查看质量问题明细")):
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
                st.error(t("⚠ 批间趋势发散：以下 CQA 各批降解速率差异显著，提示工艺/批间不均一，不可简单外推，建议逐批评估或减括号。"))
                with st.expander(t("查看发散明细")):
                    st.dataframe(pd.DataFrame(diverging), width='stretch')


# ----------------------------------------------------------------------------
# 有效期推算
# ----------------------------------------------------------------------------
