"""数据录入页面（由 app.py 拆分而来）。"""

import json
import streamlit as st
from i18n import t
import pandas as pd
import plotly.graph_objects as go
import models as M
import db as DB
import importers as IM
from ui_common import ATTRIBUTE_OPTIONS, check_perm, load_study_obj, persist


def render(ctx):
    user = ctx["user"]
    studies = ctx["studies"]

    st.header(t("🧪 检测数据录入"))
    if not check_perm("data:write"):
        st.error(t("权限不足：需 data:write。"))
    elif not studies:
        st.info(t("请先创建研究。"))
    else:
        # R9：教学提示 —— 生物制品 CQA 录入规范
        sel0 = st.selectbox(t("选择研究"), [f'{s["name"]} ({s["study_id"]})' for s in studies], key="entry_sel0")
        sid0 = sel0.split("(")[-1].rstrip(")")
        study0 = load_study_obj(sid0)
        if study0.biologic:
            st.info(t("🧬 生物制品：CQA 录入请使用稳定性指示方法；效价下降>10% 即判显著变化(Q5C)。强制降解/冻融/使用中/运输等特殊条件数据请按模板条件分类录入。"))
        sel = st.selectbox(t("选择研究"), [f'{s["name"]} ({s["study_id"]})' for s in studies])
        sid = sel.split("(")[-1].rstrip(")")
        study = load_study_obj(sid)
        # ---- 批量 CSV 录入 ----
        with st.expander(t("📥 批量 CSV 录入（列：批号,条件,月点,检测项目,数值,单位,限度,方向）")):
            st.caption(t("示例：B2026-001,冷藏(2-8C),0,效价,100.0,%,90,lower"))
            # R24：CSV 模板下载
            tmpl_csv = IM.TEMPLATE_CSV
            st.download_button(t("⬇ 下载 CSV 录入模板"), tmpl_csv.encode("utf-8-sig"),
                               "bulk_template.csv", "text/csv")
            up = st.file_uploader(t("上传 CSV"), type=["csv"], key="bulk_csv")
            if up:
                try:
                    bulk = IM.read_bulk_csv(up.getvalue())
                    before = study.to_dict()
                    cnt, skipped = IM.import_bulk_csv(study, bulk)
                    if cnt:
                        persist(study, user, "DATA_BULK", before)
                        st.success(t("已批量录入 {0} 条。").format(cnt))
                    else:
                        st.warning(t("未匹配到任何有效记录（请确认批号存在于本研究）。"))
                    if skipped:
                        with st.expander(t("跳过 {0} 行（查看原因）").format(len(skipped))):
                            for msg in skipped:
                                st.write("• " + msg)
                except ValueError as e:
                    st.error(t("CSV 导入失败：{0}").format(e))
        sample_opts = {f'{s.batch_id} ({s.sample_id})': s for s in study.samples}
        if not sample_opts:
            st.warning(t("该研究尚无样品，请先在『研究管理』添加。"))
        else:
            samp_sel = st.selectbox(t("选择样品"), list(sample_opts.keys()))
            sample = sample_opts[samp_sel]
            tp_opts = {f'{tp.condition} {tp.month}月 ({tp.planned_date})': tp for tp in sample.time_points}
            tp_sel = st.selectbox(t("选择取样时间点"), list(tp_opts.keys()))
            tp = tp_opts[tp_sel]
            attr = st.selectbox(t("检测项目"), ATTRIBUTE_OPTIONS, format_func=t)
            # R46：边录边看——该属性历史趋势 mini 图
            hist_x, hist_y = [], []
            for sm in study.samples:
                for m in sm.measurements:
                    if m.attribute == attr and m.value is not None:
                        hist_x.append(m.time_point_id)
                        hist_y.append(m.value)
            if hist_x:
                fig_mini = go.Figure(go.Scatter(x=hist_x, y=hist_y, mode="markers+lines",
                                                name="历史"))
                fig_mini.update_layout(title=f"{attr} 已录入趋势（边录边看）", height=200,
                                       margin=dict(l=30, r=10, t=30, b=30))
                st.plotly_chart(fig_mini)
            # R20：复制该批最近一次同属性值（提升录入效率）
            if st.button(t("📋 复制该批最近同属性值")):
                last_v = None
                for m in reversed(sample.measurements):
                    if m.attribute == attr and m.value is not None:
                        last_v = m.value
                        break
                if last_v is not None:
                    st.session_state["prefill_val"] = last_v
                    st.rerun()
                else:
                    st.info(t("该批暂无同属性历史值。"))
            col1, col2 = st.columns(2)
            val = col1.number_input(t("检测数值"), value=st.session_state.get("prefill_val", 0.0), key="val_input", format="%.4f")
            # R35：单位智能默认（按属性）
            _unit_default = {
                "效价": "相对标示量%", "含量": "%", "结合活性": "%",
                "聚集体": "%", "碎片": "%", "脱酰胺": "%", "氧化": "%",
                "电荷异质体": "%", "糖基化": "%", "有关物质": "%", "水分": "%",
                "不溶性微粒": "个/剂", "渗透压": "mOsm/kg", "pH": "", "可见异物": "",
                "容器密封": "", "纯度(HPLC)": "%",
            }.get(attr, "%")
            unit = col2.text_input(t("单位"), _unit_default)
            # R27：优先用模板限度预填（先于实时校验计算）
            raw = DB.load_study(sid)
            tpl_limits = {}
            try:
                if raw.get("meta_json"):
                    meta = json.loads(raw["meta_json"])
                    tpl_limits = meta.get("limits", {})
            except Exception:
                pass
            # R27：实时合规提示（边录边校验）
            dft_now = tpl_limits.get(attr) if attr in tpl_limits else M.default_limit_for(attr)
            if dft_now:
                dir_now, lim_now = dft_now
                warns_rt = M.validate_measurement(attr, float(val) if val else 0.0, unit=unit,
                                                  limit_spec=lim_now, direction=dir_now)
                if warns_rt:
                    for w in warns_rt:
                        st.warning("⚠ " + w)
            if attr in tpl_limits:
                tpl_lim, tpl_dir = tpl_limits[attr]
                dft = (tpl_dir, tpl_lim)
                st.caption(t("📋 模板预填限度：{0} 方向={1}，默认={2}").format(attr, tpl_dir, tpl_lim))
            else:
                dft = M.default_limit_for(attr)
                if dft:
                    st.caption(t("提示：{0} 默认限度方向={1}，默认值={2}").format(attr, dft[0], dft[1]))
            col3, col4 = st.columns(2)
            limit_val = col3.number_input(t("质量标准限度(可选)"), value=float(dft[1]) if dft else 0.0, format="%.4f")
            limit_on = col4.checkbox(t("设置该限度用于有效期推算"), value=bool(dft))
            note = st.text_input(t("备注"), "")
            # R11：稳定性指示能力可选字段（分离度/峰纯度）
            rc1, rc2 = st.columns(2)
            res_input = rc1.number_input(t("分离度 Rs (可选, 指示能力≥1.5)"), value=0.0, min_value=0.0, format="%.2f")
            pp_input = rc2.number_input(t("峰纯度 % (可选, ≥95%)"), value=0.0, min_value=0.0, max_value=100.0, format="%.1f")
            if st.button(t("保存检测值"), type="primary"):
                before = study.to_dict()
                is_limit = (attr in ("有关物质", "杂质", "聚集体", "碎片", "脱酰胺",
                                     "氧化", "电荷异质体", "不溶性微粒", "糖基化"))
                direction = dft[0] if dft else ("lower" if not is_limit else "upper")
                cqa = attr if study.biologic else ""
                m = M.Measurement(tp.month, attr, val, unit, limit_val if limit_on else None, is_limit, note, cqa, direction, tp_ref=tp.tp_id,
                                  resolution=res_input if res_input > 0 else None,
                                  peak_purity=pp_input if pp_input > 0 else None)
                sample.measurements.append(m)
                persist(study, user, "DATA_ADD", before)
                st.success(t("已保存。"))
            st.subheader(t("已录入数据"))
            if sample.measurements:
                st.dataframe(pd.DataFrame([m.to_dict() for m in sample.measurements]), width='stretch')
                # 删除指定检测值
                del_opts = {f'{m.time_point_id}月/{m.attribute}/{m.value}': m for m in sample.measurements}
                del_sel = st.selectbox(t("选择要删除的记录"), list(del_opts.keys()))
                if st.button(t("删除该记录"), type="secondary"):
                    before = study.to_dict()
                    sample.measurements = [m for m in sample.measurements if m is not del_opts[del_sel]]
                    persist(study, user, "DATA_DELETE", before)
                    st.success(t("已删除。"))
                    st.rerun()


# ----------------------------------------------------------------------------
# 分析与时序图
# ----------------------------------------------------------------------------
