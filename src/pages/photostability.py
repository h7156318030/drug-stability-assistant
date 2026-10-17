"""光稳定性页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import models as M
import analysis as A
from ui_common import BIO_CQA_ATTRS, load_study_obj


def render(ctx):
    studies = ctx["studies"]

    st.header(t("💡 光稳定性评估 (ICH Q1B)"))
    st.markdown(t("ICH Q1B 要求对光照敏感药物（尤其生物制品的某些制剂、可见光/紫外敏感分子）进行光稳定性考察。常规暴露：**总照度≥1.2×10⁶ lux·hr，近紫外能量≥200 W·hr/m²**；强化暴露翻倍。本页比较各批 0 月对照与光照后 CQA，判定光照后是否仍在质量标准内。"))
    # 已录入光照数据的研究
    photo_studies = []
    for s in studies:
        st_obj = load_study_obj(s["study_id"])
        if any(tp.condition == "光照" for sm in st_obj.samples for tp in sm.time_points):
            photo_studies.append(st_obj)
    if not photo_studies:
        st.info(t("暂无可进行光稳定性评估的研究（需在数据录入时为某批添加『光照』条件的时间点）。"))
    else:
        sel = st.selectbox(t("选择研究"), [f'{s.name} ({s.study_id})' for s in photo_studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        option = st.radio(t("Q1B 暴露选项"), ["option1", "option2"],
                          format_func=lambda x: "选项1 常规(1.2M lux·hr)" if x == "option1"
                          else "选项2 强化(2.4M lux·hr)")
        c1, c2 = st.columns(2)
        with c1:
            lux_hr = st.number_input(t("实际总照度 (lux·hr)"), min_value=0.0,
                                     value=float(M.PHOTO_Q1B_OPTION1["total_lux_hr"] if option == "option1"
                                                else M.PHOTO_Q1B_OPTION2["total_lux_hr"]), step=1e5)
        with c2:
            uv = st.number_input(t("实际近紫外能量 (W·hr/m²)"), min_value=0.0,
                                 value=float(M.PHOTO_Q1B_OPTION1["uv_wh_m2"] if option == "option1"
                                            else M.PHOTO_Q1B_OPTION2["uv_wh_m2"]), step=10.0)
        attrs = [a for a in (BIO_CQA_ATTRS + ["含量", "有关物质", "pH"])
                 if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
        if not attrs:
            st.info(t("该研究检测项目中无可评估的质量属性。"))
        else:
            # R31：暴露剂量计算器（照度 lux × 时长 h = lux·hr）
            with st.expander(t("🔦 暴露剂量计算器")):
                ic1, ic2 = st.columns(2)
                illum = ic1.number_input(t("光照度 (lux)"), value=12000.0, min_value=0.0, step=500.0)
                hours = ic2.number_input(t("暴露时长 (小时)"), value=100.0, min_value=0.0, step=1.0)
                calc_lux_hr = illum * hours
                uv_rate = st.number_input(t("近紫外功率密度 (W/m², 可选)"), value=2.0, min_value=0.0, step=0.1)
                calc_uv = uv_rate * hours
                st.write(t("累计总照度 = **{0:.3e} lux·hr**，近紫外 = **{1:.1f} W·hr/m²**").format(calc_lux_hr, calc_uv))
                req1 = M.PHOTO_Q1B_OPTION1
                ok_l = calc_lux_hr >= req1["total_lux_hr"]
                ok_u = calc_uv >= req1["uv_wh_m2"]
                st.write("对照 Q1B 选项1：" + ("✅满足" if ok_l and ok_u else "❌不足"))
            attr = st.selectbox(t("评估质量属性"), attrs, format_func=t)
            res = A.photostability_assessment(study, attr, option, lux_hr, uv)
            if res["exposure"]:
                ex = res["exposure"]
                if ex["ok"]:
                    st.success(f"光照暴露充足：总照度✓ 近紫外✓（要求 {ex['required']['total_lux_hr']:.1e} "
                               f"lux·hr / {ex['required']['uv_wh_m2']} W·hr/m²）")
                else:
                    st.warning(f"光照暴露不足：总照度{'✓' if ex['total_ok'] else '✗'} "
                               f"近紫外{'✓' if ex['uv_ok'] else '✗'}，需补足暴露后再评估。")
            if res["batches"]:
                st.subheader(t("批次光照前后对比"))
                st.dataframe(pd.DataFrame(res["batches"]), width='stretch')
                # 柱状图：0月 vs 光照后
                fig_p = go.Figure()
                bids = [b["batch_id"] for b in res["batches"]]
                fig_p.add_trace(go.Bar(x=bids, y=[b["base"] for b in res["batches"]], name="0月对照"))
                fig_p.add_trace(go.Bar(x=bids, y=[b["photo"] for b in res["batches"]], name="光照后"))
                fig_p.update_layout(title=f"{attr}：0月 vs 光照后", barmode="group")
                st.plotly_chart(fig_p)
                if res["compliant"]:
                    st.success(res["note"])
                elif res["compliant"] is False:
                    st.error(res["note"])
            else:
                st.info(res["note"])
            # R43：批次配对 Δ% 汇总（光照后相对0月对照）
            if res.get("batches"):
                df_b = pd.DataFrame(res["batches"])
                if "rel_pct" in df_b.columns:
                    st.subheader(t("📊 光照诱导变化 Δ% 汇总"))
                    st.dataframe(df_b[["batch_id", "base", "photo", "delta", "rel_pct", "over_limit"]],
                                 width='stretch')
                    st.caption(t("rel_pct = (光照后 - 0月对照)/0月对照 × 100%。正值=光照降解。"))


# ----------------------------------------------------------------------------
# 统计汇总（全库概览指标）
# ----------------------------------------------------------------------------
