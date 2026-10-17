"""研究管理页面（由 app.py 拆分而来）。"""

import json
import streamlit as st
from i18n import t
from datetime import date, datetime
import models as M
import planner as P
import db as DB
import auth as AU
from ui_common import BIO_CONDITIONS, CHEM_CONDITIONS, MOLECULE_OPTIONS, check_perm, load_study_obj, persist, seed_teaching_examples


def render(ctx):
    user = ctx["user"]
    role = ctx["role"]
    name = ctx["name"]
    studies = ctx["studies"]

    st.header(t("🗂 研究管理"))
    if not check_perm("study:create"):
        st.error(t("权限不足：需 study:create。"))
    else:
        tab1, tab2 = st.tabs([t("新建研究"), t("研究列表 / 删除")])
        with tab1:
            # 从模板创建
            with st.expander(t("⚡ 从方案模板快速创建")):
                tpl_name = st.selectbox(t("选择模板"), P.list_templates(), format_func=t)
                t_name = st.text_input(t("新研究名称"), "模板研究")
                t_sponsor = st.text_input(t("申办方/部门"), "")
                t_batches = st.text_input(t("批号（逗号分隔，如 B1,B2,B3）"), "B1,B2,B3")
                t_start = st.date_input(t("起始日期"), date.today(), key="tpl_start")
                note = P.template_note(tpl_name)
                if note:
                    st.info(t("📋 模板说明：{0}").format(note))
                stage_opts = [s.value for s in M.DevelopmentStage]
                t_stage = st.selectbox(t("临床阶段"), stage_opts, index=0, key="tpl_stage", format_func=t)
                rel_opts = ["（无）"] + [f'{s["name"]} ({s["study_id"]})' for s in studies]
                t_rel = st.selectbox(t("关联研究（如 DS 对应 DP）"), rel_opts, key="tpl_rel", format_func=t)
                t_rel_kind = st.text_input(t("关联类型描述"), "原液→制剂联动(Q5C)")
                if st.button(t("基于模板创建")):
                    batches = [b.strip() for b in t_batches.split(",") if b.strip()]
                    st_tpl = P.create_from_template(tpl_name, t_name, t_sponsor, batches, t_start.isoformat(), stage=t_stage)
                    if t_rel != "（无）":
                        rsid = t_rel.split("(")[-1].rstrip(")")
                        st_tpl.related_study_id = rsid
                        st_tpl.related_study_type = t_rel_kind
                    persist(st_tpl, user, "STUDY_CREATE_TPL")
                    st.success(f"已基于模板创建：{t_name}（阶段：{st_tpl.stage}，含 {sum(len(s.time_points) for s in st_tpl.samples)} 个计划取样点，"
                              f"检测项目：{st_tpl._template_attrs}）")
            biologic = st.checkbox(t("生物制品研究 (ICH Q5C)"), value=False)
            with st.form("new_study"):
                name = st.text_input(t("研究名称"), "XX稳定性研究")
                drug = st.text_input(t("药品通用名"), "某化学药")
                stype = st.selectbox(t("研究类型"), [t.value for t in M.StudyType], format_func=t)
                design = st.selectbox(t("设计类型"), [d.value for d in M.DesignType], format_func=t)
                molecule = st.selectbox(t("分子类型"), MOLECULE_OPTIONS, disabled=not biologic, format_func=t)
                stage_opts = [s.value for s in M.DevelopmentStage]
                stage = st.selectbox(t("临床阶段"), stage_opts, index=0, key="new_stage", format_func=t)
                sponsor = st.text_input(t("申办方/部门"), "")
                start = st.date_input(t("研究起始日期"), date.today())
                if st.form_submit_button(t("创建研究")):
                    mt = molecule if biologic else ""
                    st_obj = M.StabilityStudy(name, stype, drug, sponsor, design,
                                              start.isoformat(), biologic=biologic, molecule_type=mt, stage=stage)
                    persist(st_obj, user, "STUDY_CREATE")
                    st.success(t("已创建研究：{0}（阶段：{1}，ID: {2}）").format(name, stage, st_obj.study_id))
        # R15：教学示例一键加载（生物制品单抗 DS+DP）
        st.divider()
        st.subheader(t("🎓 教学示例数据集"))
        st.caption(t("一键生成一套生物制品教学示例（单抗原液DS + 制剂DP，含 CQA 降解数据、冻融/使用中/运输条件），用于熟悉系统功能与合规流程。示例数据不构成真实货架期结论。"))
        if st.button(t("加载教学示例（单抗 DS + DP）")):
            n_loaded = seed_teaching_examples(user)
            st.success(t("已加载 {0} 个教学示例研究（见『研究管理』列表）。可在『教学指南』页对照学习。").format(n_loaded))
        if studies:
            sel = st.selectbox(t("选择研究"), [f'{s["name"]} ({s["study_id"]})' for s in studies])
            sid = sel.split("(")[-1].rstrip(")")
            if check_perm("study:delete"):
                # R28：删除二次确认（防误删）
                if st.button(t("删除该研究"), type="primary"):
                    st.session_state["confirm_del"] = sid
                if st.session_state.get("confirm_del") == sid:
                    st.error(t("⚠ 确认删除研究『{0}』？此操作不可撤销！").format(sid))
                    # 电子签名：删除为关键操作，须重新输入口令（Part 11 §11.200）
                    reauth_pw = st.text_input(t("请输入您的登录口令以确认（电子签名）"), type="password",
                                              key=f"reauth_del_{sid}")
                    c1, c2 = st.columns(2)
                    if c1.button(t("✅ 确认删除"), type="primary"):
                        if not AU.reauthenticate(user["username"], reauth_pw):
                            st.error(t("口令错误，未删除。（错误次数计入锁定策略）"))
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
                    if c2.button(t("❌ 取消")):
                        st.session_state["confirm_del"] = None
                        st.rerun()
            # R48：研究导入/导出 JSON（便于备份迁移与审计追溯）
            col_imp, col_exp = st.columns(2)
            with col_exp:
                if st.button(t("📤 导出该研究 JSON")):
                    st_obj = load_study_obj(sid)
                    st.download_button(t("下载"), json.dumps(st_obj.to_dict(), ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                                       f"{sid}.json", "application/json")
            with col_imp:
                upj = st.file_uploader(t("📥 导入研究 JSON"), type=["json"], key="imp_json")
                if upj:
                    try:
                        data = json.loads(upj.getvalue().decode("utf-8"))
                        st_obj = M.StabilityStudy.from_dict(data)
                        # 若 ID 冲突则生成新 ID
                        if DB.load_study(st_obj.study_id):
                            st_obj.study_id = M.StabilityStudy.from_dict({}).study_id  # 新ID
                            st_obj.study_id = f"IMP_{int(__import__('time').time())}"
                        persist(st_obj, user, "STUDY_IMPORT")
                        st.success(t("已导入研究：{0}（ID: {1}）").format(st_obj.name, st_obj.study_id))
                    except Exception as e:
                        st.error(t("导入失败：{0}").format(e))
            st.divider()
            st.subheader(t("添加样品与取样计划"))
            study = load_study_obj(sid)
            cond_opts = BIO_CONDITIONS if study.biologic else CHEM_CONDITIONS
            with st.form("add_sample"):
                batch = st.text_input(t("批号"), "B2026-001")
                pkg = st.text_input(t("包装/容器"), "铝塑泡罩+复合膜")
                strength = st.text_input(t("规格"), "10mg")
                conds = st.multiselect(t("研究条件"), cond_opts, default=[cond_opts[0]] if cond_opts else [], format_func=t)
                # R41：时间点方案选择
                tp_preset = st.selectbox(t("时间点方案"), list(P.TIME_POINT_PRESETS.keys()),
                                         help=t("选择 ICH 标准时间点预设，或留空用默认方案"), format_func=t)
                if st.form_submit_button(t("添加样品并生成计划")):
                    before = study.to_dict()
                    custom = P.TIME_POINT_PRESETS.get(tp_preset)
                    P.add_sample_with_plan(study, batch, pkg, strength, conds,
                                           molecule_type=study.molecule_type, custom_months=custom)
                    persist(study, user, "SAMPLE_ADD", before)
                    st.success(t("样品 {0} 已添加，计划 {1} 个取样点。").format(batch, len(study.samples[-1].time_points)))


# ----------------------------------------------------------------------------
# 数据录入
# ----------------------------------------------------------------------------
