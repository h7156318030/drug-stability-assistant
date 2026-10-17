"""统计汇总页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import models as M
import analysis as A
import report as R
from ui_common import load_study_obj


def render(ctx):
    studies = ctx["studies"]

    st.header(t("📊 全库统计汇总"))
    if not studies:
        st.info(t("暂无研究。"))
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
        col1.metric(t("研究数"), n_study)
        col2.metric(t("样品数"), n_sample)
        col3.metric(t("检测值数"), n_meas)
        col4.metric(t("质量告警项"), total_issue)
        st.subheader(t("生物制品占比"))
        fig = go.Figure(go.Pie(labels=["化学药", "生物制品"], values=[n_study - bio, bio], hole=0.4))
        fig.update_layout(height=300)
        st.plotly_chart(fig)
        if cqa_rate:
            st.subheader(t("各检测项目平均年降解率 (%)"))
            avg = {k: round(sum(v) / len(v), 2) for k, v in cqa_rate.items()}
            fig2 = go.Figure(go.Bar(x=list(avg.keys()), y=list(avg.values()),
                                    text=list(avg.values()), textposition="auto"))
            fig2.update_layout(height=320)
            st.plotly_chart(fig2)
        # R34：属性覆盖率（各检测项目在多少研究中被录入）
        if attr_studies:
            st.subheader(t("📋 检测项目覆盖率"))
            cov_rows = [{"检测项目": a, "录入研究数": len(sids),
                         "覆盖率%": round(len(sids) / n_study * 100, 1)}
                        for a, sids in sorted(attr_studies.items(), key=lambda x: -len(x[1]))]
            st.dataframe(pd.DataFrame(cov_rows), width='stretch')
            st.caption(t("覆盖率低的项目提示录入不完整或方案设计差异。"))
        # R10：全库批间合并 Bootstrap 置信区间 + 留一法稳健性（多批次研究）
        st.subheader(t("批间合并外推稳健性 (Bootstrap 95% CI / 留一法, ICH Q1E)"))
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
            st.caption(t("说明：Bootstrap 95% CI 反映多批次合并有效期的抽样不确定性；留一法最大降幅<20% 视为外推稳健。非稳健项应增加批次或谨慎外推(Q1E)。"))
        else:
            st.caption(t("暂无可计算的多批次合并稳健性（需≥2批次、≥3数据点且含限度）。"))
        # R45：外推稳健性汇总表（跨研究）
        st.subheader(t("📐 外推稳健性汇总（跨研究）"))
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
            st.caption(t("稳健性=留一法各批外推差异小；不稳健提示需补充数据或逐批评估。"))
        else:
            st.info(t("暂无可计算的跨研究外推稳健性（需≥2批含限度数据）。"))
        # R18：计算引擎状态面板（标识已实现的统计/合规方法）
        with st.expander(t("🧮 计算引擎状态（已实现的统计与合规方法）")):
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
            if st.button(t("导出跨研究汇总 Excel（总览/有效期/生物CQA/稳健性）")):
                xlsx = R.export_cross_study_summary(all_objs)
                st.download_button(t("下载跨研究汇总.xlsx"), xlsx, "cross_study_summary.xlsx",
                                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ----------------------------------------------------------------------------
# 导出报告
# ----------------------------------------------------------------------------
