"""质量告警页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import analysis as A
from ui_common import ATTRIBUTE_OPTIONS, load_study_obj


def render(ctx):
    studies = ctx["studies"]

    st.header(t("🚨 数据质量告警面板"))
    st.caption(t("自动扫描全部研究的离群值、缺失时间点与非线性降解趋势。"))
    if not studies:
        st.info(t("请先创建研究。"))
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
                st.warning(t("📅 【{0}】计划取样点未录入：共 {1} 处（提示补测/确认掉点）。").format(study.name, len(missing_summary)))
                with st.expander(t("查看缺失明细")):
                    st.dataframe(pd.DataFrame(missing_summary), width='stretch')
            if issues:
                st.subheader(t("⚠ {0} — {1} 项").format(study.name, len(issues)))
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
                    st.subheader(t("🧬 {0} 生物制品 CQA 显著变化 — {1} 项").format(study.name, len(cqa_sig)))
                    st.dataframe(pd.DataFrame(cqa_sig), width='stretch')
        # 全库汇总
        total = sum(len(A.study_data_quality(load_study_obj(x["study_id"]),
                         sorted({m.attribute for sm in load_study_obj(x["study_id"]).samples for m in sm.measurements}))
                         if sorted({m.attribute for sm in load_study_obj(x["study_id"]).samples for m in sm.measurements}) else [])
                    for x in studies)
        if total == 0:
            st.success(t("✅ 全库未发现离群/缺失/非线性异常。"))


# ----------------------------------------------------------------------------
# 生物制品 CQA 专项仪表
# ----------------------------------------------------------------------------
