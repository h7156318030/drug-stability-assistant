"""有效期推算页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import models as M
import analysis as A
from ui_common import ATTRIBUTE_OPTIONS, load_study_obj


def render(ctx):
    name = ctx["name"]
    studies = ctx["studies"]

    st.header(t("⏳ 有效期 / 复验期推算 (ICH Q1E / Q5C)"))
    st.caption(t("基于各检测项目的限度，按95%置信下限(下限限度)或上限(上限限度)推算有效期。需≥3个时间点。生物制品聚集体/碎片等常见非线性降解，系统会给出提示。"))
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
                df = pd.DataFrame(res)
                df_disp = df[["批号", "条件", "检测项目", "数据点", "斜率/月", "R²", "p值", "趋势", "有效期(月)", "备注"]]
                st.dataframe(df_disp, width='stretch')
                if "有效期(月)" in df.columns:
                    valid = df.dropna(subset=["有效期(月)"])
                    if not valid.empty:
                        st.subheader(t("各样品最严格有效期（取所有项目最小值）"))
                        summary = valid.groupby("批号")["有效期(月)"].min().reset_index()
                        summary.columns = ["批号", "建议有效期(月)"]
                        st.dataframe(summary, width='stretch')
                        st.warning(t("注：有效期应取各CQA中最严格者，并向下舍入至合规整数月（ICH Q1E/Q5C）。外推超过观测期1倍需有充分论证；生物制品非线性降解应谨慎外推。"))
                        # R22：外推风险等级（批数/覆盖率/LOO 稳健性）
                        n_batch = len(study.samples)
                        risk_factors = []
                        if n_batch < 3:
                            risk_factors.append(f"批数不足({n_batch}<3)")
                        # 覆盖率：观测期占推算比例
                        max_obs = max((tp.month for sm in study.samples for tp in sm.time_points
                                       if tp.condition in (M.StorageCondition.LONG_TERM.value, "长期")), default=0)
                        min_exp = summary["建议有效期(月)"].min() if not summary.empty else 0
                        if max_obs and min_exp > max_obs * 2:
                            risk_factors.append("外推>2倍观测期(高风险)")
                        elif max_obs and min_exp > max_obs * 1.5:
                            risk_factors.append("外推>1.5倍观测期(中风险)")
                        # LOO 稳健性
                        loo_robust = True
                        for s in study.samples:
                            for cond in set(tp.condition for tp in s.time_points):
                                dl = M.default_limit_for("效价")
                                if dl and n_batch >= 2:
                                    lo = A.leave_one_out_expiry(study, "效价", cond, dl[1], dl[0])
                                    if lo and not lo.get("robust"):
                                        loo_robust = False
                        if not loo_robust:
                            risk_factors.append("留一法外推不稳健")
                        if not risk_factors:
                            st.success(t("✅ 外推风险等级：低（批数充足、外推比例适度、LOO稳健）。"))
                        else:
                            st.error("⚠ 外推风险等级：高/中 — " + "；".join(risk_factors)
                                     + "。建议补充批次、延长监测期或限制外推。")
            else:
                st.info(t("需在『数据录入』中录入检测值（≥3时间点）。"))
            # R37：多模型对比图（线性/指数/logistic，AIC 选择）
            st.subheader(t("📉 多模型拟合对比 (AIC/BIC 选择)"))
            mm_attrs = attrs
            mm_conds = sorted({tp.condition for sm in study.samples for tp in sm.time_points})
            if mm_attrs and mm_conds:
                mm_a = st.selectbox(t("选择属性（多模型）"), mm_attrs, key="mm_a", format_func=t)
                mm_c = st.selectbox(t("选择条件（多模型）"), mm_conds, key="mm_c", format_func=t)
                try:
                    bm = A.fit_best_model(study, mm_a, mm_c)
                    fig_mm = go.Figure()
                    for s in study.samples:
                        months, vals, _ = A._series_for(s, mm_a, mm_c)
                        if len(vals):
                            fig_mm.add_trace(go.Scatter(x=list(months), y=list(vals),
                                                        mode="markers", name=f"{s.batch_id}实测"))
                    t_grid = bm.get("t_grid")
                    for name, pred in bm.get("predictions", {}).items():
                        fig_mm.add_trace(go.Scatter(x=t_grid, y=pred, mode="lines",
                                                    name=f"{name} (AIC={bm['comparison'][name]['aic']:.0f})"))
                    fig_mm.update_layout(title=f"{mm_a} @ {mm_c} 多模型拟合", xaxis_title="月", yaxis_title=mm_a)
                    st.plotly_chart(fig_mm)
                    best = bm["best_model"]
                    st.success(t("最优模型（最小 AIC）：**{0}**（AIC={1:.1f}）").format(best, bm['comparison'][best]['aic']))
                except Exception as e:
                    st.info("多模型拟合暂不可用：" + str(e)[:100])
            # 外推因子分析（ICH Q1E）
            ext_rows = []
            for attr in attrs:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        ex = A.expiry_extrapolation(study, attr, cond)
                        if ex:
                            ext_rows.append({"批号": ex["batch"], "条件": ex["condition"],
                                             "检测项目": ex["attribute"], "观测期(月)": ex["t_obs"],
                                             "95%下限有效期": ex["t_lower_bound"],
                                             "外推倍率": ex["extrap_factor"], "建议": ex["recommendation"]})
            if ext_rows:
                st.subheader(t("外推因子分析 (ICH Q1E)"))
                st.dataframe(pd.DataFrame(ext_rows), width='stretch')
            # R18：多模型拟合与 AIC/BIC 选择（非线性降解提示）
            st.subheader(t("模型拟合与选择 (线性/指数/逻辑斯蒂, AIC/BIC)"))
            model_rows = []
            for attr in attrs:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        # 取限度
                        lim = None
                        for m in s.measurements:
                            if m.attribute == attr and m.limit_spec is not None:
                                lim = m.limit_spec
                                break
                        if lim is None:
                            continue
                        ref = next((m.value for sm in study.samples for m in sm.measurements if m.attribute == attr), 0)
                        direction = "lower" if lim < ref else "upper"
                        fm = A.fit_best_model(study, attr, cond, lim, direction)
                        if fm:
                            comp = fm["comparison"]
                            model_rows.append({
                                "条件": cond, "检测项目": attr, "最优模型": fm["best_model"],
                                "AIC": fm["best_aic"], "BIC": fm["best_bic"],
                                "线性有效期": comp.get("linear", {}).get("shelf_life"),
                                "最优模型有效期": fm["shelf_life_best"],
                            })
            if model_rows:
                st.dataframe(pd.DataFrame(model_rows), width='stretch')
                nonlinear = [r for r in model_rows if r["最优模型"] != "linear"]
                if nonlinear:
                    st.warning("⚠ 以下组合非线性模型(AIC/BIC 更优)："
                               + "、".join(f'{r["检测项目"]}@{r["条件"]}' for r in nonlinear)
                               + "。生物制品降解多非线性，线性外推偏乐观(Q1E)，"
                               "建议增加时间点或采用非线性模型推算有效期。")
            # R12：批合并外推有效期（Q1E 95% 单侧下限）
            st.subheader(t("📏 批合并外推有效期 (ICH Q1E 95% 单侧下限)"))
            pe_rows = []
            all_conds = sorted({tp.condition for sm in study.samples for tp in sm.time_points})
            for attr in attrs:
                for cond in all_conds:
                    pe = A.pooled_expiry_extrapolation(study, attr, cond)
                    if pe["recommended"] is not None:
                        pe_rows.append({
                            "检测项目": attr, "条件": cond,
                            "可合并": "是" if pe["poolable"] else "否",
                            "合并外推(月)": round(pe["pooled_expiry"], 1) if pe["pooled_expiry"] else None,
                            "单批最小(月)": round(pe["min_single_expiry"], 1) if pe["min_single_expiry"] else None,
                            "保守建议(月)": round(pe["recommended"], 1),
                        })
            if pe_rows:
                st.dataframe(pd.DataFrame(pe_rows), width='stretch')
                st.caption(t("保守有效期取『合并外推』与『单批最小外推』的较小值（95% 单侧置信下限，Q1E）。"))
            else:
                st.info(t("暂无可计算外推有效期的检测项目。"))
            # 显著变化判定（生物制品用 Q5C 专属阈值）
            sig_rows = []
            for attr in attrs:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        sc = A.biologic_significant_change(study, attr, cond)
                        if sc:
                            sig_rows.append(sc)
            if sig_rows:
                st.subheader(t("显著变化判定 (ICH Q1A / Q5C)"))
                st.dataframe(pd.DataFrame(sig_rows), width='stretch')
            # R9：生物制品外推谨慎提示
            if study.biologic:
                st.warning(t("🧬 生物制品外推需谨慎 (Q5C/Q1E)：建议至少 3 批、覆盖 75% 监测期，且批间一致方可外推至 2 倍（长期）或 1.5 倍（加速）。可用『统计汇总』页的Bootstrap 置信区间与留一法评估外推稳健性。"))
            # R3：使用中稳定性（in-use，以天为单位）
            inuse_attrs = [a for a in attrs
                           if any(tp.condition == "使用中" for s in study.samples for tp in s.time_points)
                           and any(m.attribute == a for s in study.samples for m in s.measurements)]
            if inuse_attrs:
                st.subheader(t("💉 使用中稳定性 (in-use, 复溶/开启后天数)"))
                st.caption(t("ICH Q5C：多剂量/复溶制剂需评估开启后使用期限（常见 28 天）。本段以『开启后天数』为横轴推算 CQA 触及限度的天数。"))
                for attr in inuse_attrs:
                    r = A.in_use_shelf_life(study, attr)
                    if r["status"] == "ok":
                        st.success(t("{0}：{1}").format(attr, r['note']))
                        st.dataframe(pd.DataFrame(r["batches"]), width='stretch')
                    else:
                        st.info(t("{0}：{1}").format(attr, r['note']))
            # R14：批间一致性 / 工艺能力 Cpk
            st.subheader(t("📊 批间一致性 / 工艺能力 (Cpk)"))
            cpk_rows = []
            for attr in attrs:
                cc = A.batch_consistency_capability(study, attr)
                if cc["n_batches"] >= 2:
                    cpk_rows.append({
                        "检测项目": attr, "批数": cc["n_batches"],
                        "批均值": round(cc["mean"], 2) if cc["mean"] else None,
                        "σ": round(cc["sd"], 2) if cc["sd"] else None,
                        "Cpk": ("∞" if cc["cpk"] == float("inf") else round(cc["cpk"], 2)),
                        "一致性": cc["consistency"],
                    })
            if cpk_rows:
                st.dataframe(pd.DataFrame(cpk_rows), width='stretch')
                st.caption(t("Cpk≥1.33 优；1.0–1.33 良；0.67–1.0 临界；<0.67 差。规格未提供时以历史批均值±3σ为经验规格。"))
            else:
                st.info(t("批数不足，无法评估批间一致性。"))
            # R15：容器密封完整性（CCIT）趋势
            cc = A.ccit_trend_assessment(study)
            if cc["has_data"]:
                st.subheader(t("🔒 容器密封完整性 (CCIT, USP<1207>/Q5C)"))
                st.dataframe(pd.DataFrame(cc["trend"]), width='stretch')
                if cc["first_fail_month"] is not None:
                    st.error(cc["note"])
                else:
                    st.success(cc["note"])
            else:
                st.info("💡 " + cc["note"])


# ----------------------------------------------------------------------------
# 横向比较（多研究/多批 同一检测项目叠加对比）
# ----------------------------------------------------------------------------
