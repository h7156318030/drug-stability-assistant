"""生物制品 CQA页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import models as M
import analysis as A
from ui_common import BIO_CQA_ATTRS, load_study_obj


def render(ctx):
    name = ctx["name"]
    studies = ctx["studies"]

    st.header(t("🧬 生物制品 CQA 稳定性仪表"))
    bio_studies = [s for s in studies if load_study_obj(s["study_id"]).biologic]
    if not bio_studies:
        st.info(t("暂无生物制品研究（创建时勾选『生物制品』）。"))
    else:
        # R7：生物制品总览 —— 阶段分布 + DS-DP 关联
        st.subheader(t("① 生物制品研究总览"))
        c1, c2 = st.columns([1, 1])
        with c1:
            stage_cnt = {}
            for s in bio_studies:
                st_obj = load_study_obj(s["study_id"])
                stage_cnt[st_obj.stage or "未指定"] = stage_cnt.get(st_obj.stage or "未指定", 0) + 1
            fig_pie = go.Figure(go.Pie(labels=list(stage_cnt.keys()), values=list(stage_cnt.values()),
                                       title="临床阶段分布"))
            fig_pie.update_layout(height=340)
            st.plotly_chart(fig_pie)
        with c2:
            st.markdown(t("**DS-DP 关联链路 (ICH Q5C)**"))
            link_rows = []
            for s in bio_studies:
                st_obj = load_study_obj(s["study_id"])
                if st_obj.related_study_id:
                    link_rows.append({"本研究": st_obj.name, "关联类型": st_obj.related_study_type,
                                      "关联ID": st_obj.related_study_id})
            if link_rows:
                st.dataframe(pd.DataFrame(link_rows), width='stretch')
            else:
                st.caption(t("暂无关联（创建模板时可指定原液↔制剂联动）。"))
        # 生物制品显著变化审计（所有生物CQA）
        st.subheader(t("② 生物制品显著变化速览 (ICH Q5C)"))
        sig_rows = []
        for s in bio_studies:
            st_obj = load_study_obj(s["study_id"])
            for sm in st_obj.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    for attr in ["效价", "结合活性", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体", "糖基化"]:
                        r = A.biologic_significant_change(st_obj, attr, cond)
                        if r:
                            sig_rows.append({"研究": st_obj.name, "批号": r["batch"], "条件": cond,
                                             "CQA": attr, "月点": r["month_of_change"],
                                             "变化%": r["change_pct"], "结论": r["conclusion"]})
        if sig_rows:
            st.dataframe(pd.DataFrame(sig_rows), width='stretch')
        else:
            st.caption(t("当前生物制品数据未触发显著变化。"))
        # R17：全 CQA 状态仪表（一屏总览该研究的各 CQA 最新状态）
        st.subheader(t("② 全 CQA 状态仪表"))
        dash_sel = st.selectbox(t("选择生物制品研究（仪表）"),
                                [f'{s["name"]} ({s["study_id"]})' for s in bio_studies], key="cqa_dash")
        dsid = dash_sel.split("(")[-1].rstrip(")")
        dstudy = load_study_obj(dsid)
        dash_rows = []
        for attr in BIO_CQA_ATTRS + ["含量", "有关物质", "pH", "渗透压", "水分", "不溶性微粒"]:
            present = any(m.attribute == attr for sm in dstudy.samples for m in sm.measurements)
            if not present:
                continue
            # 取长期条件终末值（最新月点均值）
            last_vals = []
            for sm in dstudy.samples:
                for tp in sm.time_points:
                    if tp.condition in (M.StorageCondition.LONG_TERM.value, "长期"):
                        for m in sm.measurements:
                            if m.attribute == attr and m.value is not None and float(m.time_point_id) == float(tp.month):
                                last_vals.append(m.value)
            cur = float(np.mean(last_vals)) if last_vals else None
            dl = M.default_limit_for(attr)
            status = "—"
            if cur is not None and dl:
                d, lim = dl
                if d == "lower" and cur < lim:
                    status = "❌低于下限"
                elif d == "upper" and cur > lim:
                    status = "❌高于上限"
                else:
                    status = "✅符合"
            dash_rows.append({
                "CQA": attr, "终末均值": round(cur, 2) if cur is not None else None,
                "限度": dl[1] if dl else None, "方向": dl[0] if dl else None, "状态": status,
            })
        if dash_rows:
            st.dataframe(pd.DataFrame(dash_rows), width='stretch')
        else:
            st.info(t("该研究无标准CQA数据。"))
        sel = st.selectbox(t("选择生物制品研究"), [f'{s["name"]} ({s["study_id"]})' for s in bio_studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        cqa_attrs = [a for a in BIO_CQA_ATTRS if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
        if not cqa_attrs:
            st.info(t("该研究的检测项目未包含标准CQA（效价/聚集体/碎片/脱酰胺/氧化/电荷异质体/糖基化）。"))
        else:
            radar_r = {}
            for attr in cqa_attrs:
                # 用首批首条件做速率
                s0 = study.samples[0]
                cond = next((tp.condition for tp in s0.time_points), "")
                months, vals, _ = A._series_for(s0, attr, cond)
                if len(vals) >= 2:
                    reg = A.regression_summary(months, vals)
                    # 限度余量：当前值到限度的相对距离（越大越好）
                    lim = None
                    for m in s0.measurements:
                        if m.attribute == attr and m.limit_spec is not None:
                            lim = m.limit_spec; break
                    margin = 0
                    if lim is not None and vals[-1] != 0:
                        margin = abs(vals[-1] - lim) / abs(vals[-1]) * 100
                    radar_r[attr] = round(margin, 1)
            if radar_r:
                fig_r = go.Figure(go.Scatterpolar(
                    r=list(radar_r.values()) + [list(radar_r.values())[0]],
                    theta=list(radar_r.keys()) + [list(radar_r.keys())[0]],
                    fill="toself"))
                fig_r.update_layout(title="各CQA限度余量 (%)，越大越安全", height=420)
                st.plotly_chart(fig_r)
            st.subheader(t("CQA 降解速率汇总"))
            rows = []
            for s in study.samples:
                for cond in set(tp.condition for tp in s.time_points):
                    for attr in cqa_attrs:
                        months, vals, _ = A._series_for(s, attr, cond)
                        if len(vals) >= 2:
                            reg = A.regression_summary(months, vals)
                            rows.append({"批号": s.batch_id, "条件": cond, "CQA": attr,
                                         "斜率/月": round(reg["slope"], 4),
                                         "年变化率%": round(reg["rel_rate_pct_year"], 2) if not (isinstance(reg["rel_rate_pct_year"], float) and reg["rel_rate_pct_year"] != reg["rel_rate_pct_year"]) else None,
                                         "R²": round(reg["r2"], 3)})
            if rows:
                st.dataframe(pd.DataFrame(rows), width='stretch')
            # R23：强制降解/应激 — 稳定性指示方法确证
            fd = A.forced_degradation_assessment(study)
            if fd:
                st.subheader(t("🔬 强制降解确证 (稳定性指示方法, ICH Q5C)"))
                st.dataframe(pd.DataFrame(fd), width='stretch')
                if any(r["稳定性指示能力"] == "否(需复核方法/增加应激强度)" for r in fd):
                    st.warning(t("部分批/应力条件未产生降解信号，可能应激强度不足或方法不灵敏，需复核方法以确保其具有稳定性指示能力(stability-indicating)。"))
                # R33：应激强度等级建议
                weak = [r for r in fd if r.get("SIm确证", "").startswith("弱")]
                if weak:
                    st.info(t("💡 应激强度建议：对未产生降解信号的批，应提高应激强度（如升温/强酸强碱/氧化/光照强化）直至产生可定量降解产物，以确证方法的稳定性指示能力。"))
            # R8：矩阵/括号设计合规自检（Q1D）
            st.subheader(t("📐 设计合规自检 (ICH Q1D 矩阵/括号)"))
            dc = A.matrix_bracket_compliance(study)
            for name, ok in dc["checks"]:
                st.write(("✅" if ok else "❌") + " " + name)
            if dc["issues"]:
                for iss in dc["issues"]:
                    st.error("⚠ " + iss)
            else:
                st.success(dc["note"])
            # R24：冻融循环 / 使用中(in-use) 专项分析
            special_conds = []
            for c in ("冻融循环", "使用中", "运输"):
                if any(tp.condition == c for sm in study.samples for tp in sm.time_points):
                    special_conds.append(c)
            if special_conds:
                st.subheader(t("❄ 冻融 / 使用中 / 运输 专项稳定性"))
                sc_sel = st.selectbox(t("专项条件"), special_conds, key="spec_cond", format_func=t)
                xlabel = "冻融循环次数" if sc_sel == "冻融循环" else ("复溶后天数" if sc_sel == "使用中" else "运输模拟")
                srows = []
                for sm in study.samples:
                    for m in sm.measurements:
                        if any(tp.condition == sc_sel and float(tp.month) == float(m.time_point_id) for tp in sm.time_points):
                            srows.append({"批号": sm.batch_id, "X(轴)": m.time_point_id,
                                          "检测项目": m.attribute, "数值": m.value,
                                          "单位": m.unit, "限度": m.limit_spec})
                if srows:
                    df_sp = pd.DataFrame(srows)
                    st.dataframe(df_sp, width='stretch')
                    # 趋势图（按批按CQA）
                    for attr in sorted(df_sp["检测项目"].unique()):
                        sub = df_sp[df_sp["检测项目"] == attr]
                        fig_sp = go.Figure()
                        for bid in sub["批号"].unique():
                            ss = sub[sub["批号"] == bid]
                            fig_sp.add_trace(go.Scatter(x=ss["X(轴)"], y=ss["数值"],
                                                       mode="lines+markers", name=bid))
                        fig_sp.update_layout(title=f"{attr} @ {sc_sel}", xaxis_title=xlabel, yaxis_title=attr)
                        st.plotly_chart(fig_sp)
                    st.caption(f"说明：{sc_sel} 条件以 {xlabel} 为横轴。冻融循环常见5次、使用中(in-use)"
                               "为复溶后至给药前允许天数、运输为模拟后单点评估。")
                    # R4/R5：冻融耐受次数 / 运输耐受判定
                    if sc_sel == "冻融循环":
                        ft_attrs = [a for a in df_sp["检测项目"].unique()
                                    if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
                        for attr in ft_attrs:
                            fr = A.freeze_thaw_assessment(study, attr)
                            if fr["status"] == "ok":
                                st.success(t("❄ {0}：{1}").format(attr, fr['note']))
                            elif fr["status"] == "limited":
                                st.warning(t("❄ {0}：{1}").format(attr, fr['note']))
                            elif fr["status"] == "fail":
                                st.error(t("❄ {0}：{1}").format(attr, fr['note']))
                            else:
                                st.info(t("❄ {0}：{1}").format(attr, fr['note']))
                    elif sc_sel == "运输":
                        tr_attrs = [a for a in df_sp["检测项目"].unique()
                                    if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
                        for attr in tr_attrs:
                            tr = A.transport_stress_assessment(study, attr)
                            if tr["status"] == "ok":
                                st.success(t("🚚 {0}：{1}").format(attr, tr['note']))
                            elif tr["status"] == "fail":
                                st.error(t("🚚 {0}：{1}").format(attr, tr['note']))
                            else:
                                st.info(t("🚚 {0}：{1}").format(attr, tr['note']))
                    # R32：冻融循环 vs CQA 相对变化图（每循环相对0月）
                    if sc_sel == "冻融循环":
                        ft_all = [a for a in df_sp["检测项目"].unique()
                                  if any(m.attribute == a for sm in study.samples for m in sm.measurements)]
                        cycles = sorted({r["X(轴)"] for r in srows})
                        if cycles:
                            fig_ft = go.Figure()
                            for attr in ft_all:
                                rel = []
                                for cyc in cycles:
                                    vals_c = [r["数值"] for r in srows if r["检测项目"] == attr and r["X(轴)"] == cyc]
                                    vals_0 = [r["数值"] for r in srows if r["检测项目"] == attr and r["X(轴)"] == cycles[0]]
                                    base = float(np.mean(vals_0)) if vals_0 else None
                                    cur = float(np.mean(vals_c)) if vals_c else None
                                    rel.append((cur - base) / abs(base) * 100.0 if base else 0.0)
                                fig_ft.add_trace(go.Scatter(x=cycles, y=rel, mode="lines+markers", name=attr))
                            fig_ft.update_layout(title="冻融循环 CQA 相对变化 (%)", xaxis_title="冻融循环次数",
                                                 yaxis_title="相对0月变化%")
                            st.plotly_chart(fig_ft)


# ----------------------------------------------------------------------------
# 光稳定性（ICH Q1B）
# ----------------------------------------------------------------------------
