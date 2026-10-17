"""系统维护页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import db as DB
import auth as AU
from ui_common import load_study_obj


def render(ctx):
    user = ctx["user"]
    role = ctx["role"]
    studies = ctx["studies"]

    st.header(t("🛠 系统维护 / 数据备份恢复"))
    if not (user and user.get("role") == "admin"):
        st.error(t("权限不足：需管理员。"))
    else:
        st.subheader(t("整库备份"))
        st.caption(t("备份包含用户口令哈希与审计记录，生成前需重新输入口令（电子签名）。"))
        reauth_bk = st.text_input(t("请输入您的登录口令以确认备份（电子签名）"), type="password", key="reauth_backup")
        if st.button(t("生成整库备份 (JSON)")):
            if not AU.reauthenticate(user["username"], reauth_bk):
                st.error(t("口令错误，未生成备份。（错误次数计入锁定策略）"))
                st.stop()
            data = DB.export_all_json()
            AU.audit("DB_BACKUP", "system", "all", user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id, note="整库备份导出")
            AU.e_signature("ALL", "DB_BACKUP", user.get("name") or user["username"], role,
                           "导出整库备份（含口令哈希）", username=user["username"],
                           ip=st.session_state.client_ip)
            st.download_button(t("下载备份文件"), data.encode("utf-8"),
                               "stability_backup.json", "application/json")
        st.subheader(t("整库恢复"))
        st.warning(t("⚠ 恢复将覆盖/追加数据库内容，操作前请先备份！"))
        up = st.file_uploader(t("上传备份 JSON"), type=["json"], key="restore")
        merge = st.checkbox(t("合并模式（仅追加不存在的研究，不清空现有数据）"), value=True)
        # 电子签名：恢复为关键操作，须重新输入口令
        reauth_pw = st.text_input(t("请输入您的登录口令以确认恢复（电子签名）"), type="password", key="restore_pw")
        if up and st.button(t("执行恢复")):
            if not AU.reauthenticate(user["username"], reauth_pw):
                st.error(t("口令错误，未执行恢复。（错误次数计入锁定策略）"))
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
                    st.success(t("恢复完成。"))
                    st.rerun()
                except Exception as e:
                    st.error(t("恢复失败：{0}").format(e))
        # R29：法规符合性自检
        st.subheader(t("🔍 法规符合性自检"))
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
        if st.button(t("导出符合性自检报告 (CSV)")):
            csv = df_ck.to_csv(index=False).encode("utf-8")
            st.download_button(t("下载自检报告.csv"), csv, "compliance_selfcheck.csv", "text/csv")


# ----------------------------------------------------------------------------
# 教学指南（学习模式 / 教学版本）
# ----------------------------------------------------------------------------
