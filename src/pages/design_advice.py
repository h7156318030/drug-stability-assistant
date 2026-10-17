"""设计建议页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import models as M
import planner as P
from ui_common import BIO_CONDITIONS, CHEM_CONDITIONS, load_study_obj


def render(ctx):
    studies = ctx["studies"]

    st.header(t("📐 稳定性研究设计建议"))
    if not studies:
        st.info(t("请先创建研究。"))
    else:
        sel = st.selectbox(t("选择研究"), [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        st.info(P.design_advice(study))
        # R13：阶段合规清单对照 + DS-DP 关联提示
        try:
            import importlib
            T = importlib.import_module("teaching")
            ck = T.checklist_for(study.stage)
            if ck:
                st.subheader(t("📋 {0} 阶段合规清单自查").format(study.stage or '通用'))
                for i, item in enumerate(ck, 1):
                    st.markdown(f"{i}. {t(item)}")
            if study.biologic and not study.related_study_id:
                st.warning(t("⚠ 该研究为生物制品但未设置关联研究(DS↔DP)。ICH Q5C 建议原液与制剂稳定性联合评估，建议创建关联研究以建立联动。"))
        except Exception:
            pass
        st.subheader(t("条件与温湿度规范"))
        specs = {**P.condition_specs()}
        cond_list = (BIO_CONDITIONS if study.biologic else CHEM_CONDITIONS)
        for c in cond_list:
            if c in specs:
                st.markdown(t("- **{0}**：{1}").format(c, t(specs[c])))
        st.subheader(t("ICH 推荐时间点"))
        from models import RECOMMENDED_TIME_POINTS, BIO_TIME_POINTS
        src = BIO_TIME_POINTS if study.biologic else RECOMMENDED_TIME_POINTS
        for c in M.StorageCondition:
            if c.value in cond_list and c in src:
                st.markdown(t("- **{0}**：{1} 月").format(c.value, src[c]))
        # 温湿度换算与货架建议
        st.subheader(t("温湿度换算与货架建议"))
        cond_c = {
            "冷藏(2-8C)": ("2–8 °C", "35.6–46.4 °F", "需冷链(冷藏)，运输用保温箱+冰袋"),
            "冷冻(-20C)": ("-20 °C", "-4 °F", "需冷冻，避免反复冻融"),
            "冷冻(-80C)": ("-80 °C", "-112 °F", "超低温，液氮/超低温冰箱，仅长期储存"),
            "室温(25C)": ("25 °C", "77 °F", "常温储存，注意湿度(60±5% RH)"),
            "加速(40C)": ("40 °C", "104 °F", "加速试验，相对湿度75±5% RH"),
            "强光照射": ("光照≥120万lux或200万 lux·hr", "—", "ICH Q1B 光照试验"),
            "中间(30C)": ("30 °C", "86 °F", "温带气候带III/IVa长期条件"),
        }
        rows_c = []
        for c in cond_list:
            if c in cond_c:
                cmin, f, shelf = cond_c[c]
                rows_c.append({"条件": c, "温度(℃)": cmin, "温度(℉)": f, "货架/运输建议": shelf})
        if rows_c:
            st.dataframe(pd.DataFrame(rows_c), width='stretch')
        st.caption(t("说明：℃↔℉ 换算 F=℃×9/5+32。长期/加速条件相对湿度要求见 ICH Q1A(R2) （长期 25°C/60%RH 或 30°C/65%RH；加速 40°C/75%RH）。"))
        if study.biologic:
            st.subheader(t("生物制品稳定性要点 (ICH Q5C)"))
            st.markdown(t("\n            - **核心CQA**：效价、聚集体(高分子量物质)、碎片、脱酰胺、氧化、电荷异质体、糖基化、不溶性微粒、可见异物、pH、水分。\n            - **降解多非线性**：聚集体/碎片常呈S型增长，线性外推偏乐观，建议增加时间点或采用非线性模型。\n            - **条件选择**：多数生物制品长期条件为冷藏(2–8°C)，冻存(-20/-80°C)用于质粒/细胞/病毒载体。\n            - **效价**为关键指标，通常以相对标示量的百分比表示，限度常设≥80%。\n            - 参考 ICH Q5C / Q6B，并结合产品特异性降解途径设计检测矩阵。\n            "))
        # R20：Arrhenius 加速→长期换算提示（若有加速条件）
        if "加速" in cond_list:
            st.subheader(t("加速→长期降解速率换算 (Arrhenius, 初筛提示)"))
            # 以含量/效价在加速与长期的斜率比粗略估算；此处给通用说明+示例
            st.caption(t("若已知加速条件(40°C)与长期条件(25°C/冷藏)的降解速率常数，可用 Arrhenius 估算倍率。示例：Ea=80 kJ/mol 时，40°C 降解速率约为 25°C 的 ~6.5 倍、约为 5°C(冷藏)的 ~25 倍。⚠ 生物制品高温可能改变降解机制，加速数据不可直接换算长期有效期，须经真实长期数据确证(Q5C)。"))
        st.markdown("---")
        st.caption(t("本系统为研究管理与分析辅助工具，有效期结论需由授权人员结合全部CQA、包装、规模等因素综合判定，并符合21 CFR Part 11 / 数据完整性要求。"))


# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# 可比性研究（变更前后 / 类似药对比, ICH Q5C 可比性）
# ----------------------------------------------------------------------------
