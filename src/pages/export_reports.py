"""导出报告页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import report as R
import auth as AU
from ui_common import ATTRIBUTE_OPTIONS, check_perm, load_study_obj


def render(ctx):
    user = ctx["user"]
    role = ctx["role"]
    studies = ctx["studies"]

    st.header(t("📤 导出报告 (Excel / PDF)"))
    if not check_perm("report:export"):
        st.error(t("权限不足：需 report:export。"))
    elif not studies:
        st.info(t("请先创建研究。"))
    else:
        sel = st.selectbox(t("选择研究"), [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        attrs = st.multiselect(t("纳入报告的检测项目"), ATTRIBUTE_OPTIONS, default=["含量", "效价"], format_func=t)
        c1, c2 = st.columns(2)
        if c1.button(t("📊 导出 Excel"), type="primary"):
            data = R.export_excel(study, attrs)
            AU.audit("REPORT_EXPORT", "study", sid, user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="Excel")
            st.download_button(t("下载 Excel"), data, file_name=f"{study.name}_报告.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if c2.button(t("📄 导出 PDF"), type="primary"):
            data = R.export_pdf(study, attrs)
            AU.audit("REPORT_EXPORT", "study", sid, user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="PDF")
            st.download_button(t("下载 PDF"), data, file_name=f"{study.name}_报告.pdf",
                               mime="application/pdf")
        # R16：导出研究完整数据包 JSON（含计算结论，供 QA/申报）
        if st.button(t("🗂 导出研究数据包 (JSON, 含计算结论)")):
            data = R.export_study_json(study)
            AU.audit("REPORT_EXPORT", "study", sid, user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="JSON")
            st.download_button(t("下载 JSON 数据包"), data, file_name=f"{study.name}_数据包.json",
                               mime="application/json")


# ----------------------------------------------------------------------------
# 设计建议
# ----------------------------------------------------------------------------
