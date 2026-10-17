"""
稳定性研究报告导出 —— Excel (openpyxl) 与 PDF (matplotlib)

Excel 工作簿包含：
  1. 研究概览
  2. 取样计划
  3. 检测数据(长表)
  4. 分析结果(回归+有效期)

PDF 报告包含：
  - 研究元信息
  - 分析结果表
  - 各检测项目降解趋势图
"""

import os
import io
from datetime import datetime
from typing import List, Dict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from models import StabilityStudy
import planner as P
import analysis as A
import fonts as F

F.setup_chinese_font()


# ----------------------------------------------------------------------------
# Excel 导出
# ----------------------------------------------------------------------------
def export_excel(study: StabilityStudy, attributes: List[str], path: str = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1F4E78")
    head_font = Font(color="FFFFFF", bold=True)

    def style_header(ws, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for col in range(1, ncols + 1):
            ws.column_dimensions[get_column_letter(col)].width = 16

    def _xl_val(v):
        """清洗不可写入 Excel 的值：列表/元组→逗号串；NaN→空"""
        if isinstance(v, (list, tuple)):
            return ",".join(str(x) for x in v) if v else "—"
        if isinstance(v, float) and (v != v):  # NaN
            return ""
        return v

    # 1. 概览
    ws = wb.active
    ws.title = "研究概览"
    meta = [
        ("研究名称", study.name), ("药品", study.drug_name),
        ("研究类型", study.study_type),
        ("是否生物制品", "是" if study.biologic else "否"),
        ("分子类型", study.molecule_type or "—"),
        ("设计类型", study.design), ("起始日期", study.start_date),
        ("样品数", len(study.samples)),
        ("生成时间", datetime.now().isoformat(timespec="seconds")),
    ]
    ws.append(["字段", "值"])
    for k, v in meta:
        ws.append([k, v])
    style_header(ws, 2)

    # 2. 取样计划
    ws2 = wb.create_sheet("取样计划")
    plan = P.plan_summary(study)
    if plan:
        cols = list(plan[0].keys())
        ws2.append(cols)
        for r in plan:
            ws2.append([r[c] for c in cols])
        style_header(ws2, len(cols))

    # 3. 检测数据
    ws3 = wb.create_sheet("检测数据")
    long = A.export_long_format(study)
    if long:
        cols = list(long[0].keys())
        ws3.append(cols)
        for r in long:
            ws3.append([_xl_val(r.get(c)) for c in cols])
        style_header(ws3, len(cols))

    # 4. 分析结果
    ws4 = wb.create_sheet("分析结果")
    if attributes:
        res = A.analyze_study(study, attributes)
        if res:
            cols = list(res[0].keys())
            ws4.append(cols)
            for r in res:
                ws4.append([_xl_val(r.get(c)) for c in cols])
            style_header(ws4, len(cols))

    # 5. 质量告警（离群/缺失/非线性）
    ws5 = wb.create_sheet("质量告警")
    qa = A.study_data_quality(study, attributes) if attributes else []
    if qa:
        qcols = list(qa[0].keys())
        ws5.append(qcols)
        for r in qa:
            ws5.append([_xl_val(r.get(c)) for c in qcols])
        style_header(ws5, len(qcols))
    else:
        ws5.append(["未检测到离群/缺失/非线性异常"])

    # 6. 有效期外推倍率
    ws6 = wb.create_sheet("有效期外推")
    er_head = ["批号", "条件", "检测项目", "观测期(月)", "95%下限有效期", "外推倍率", "建议"]
    ws6.append(er_head)
    if attributes:
        for attr in attributes:
            for s in study.samples:
                for cond in set(tp.condition for tp in s.time_points):
                    ex = A.expiry_extrapolation(study, attr, cond)
                    if ex:
                        ws6.append([ex["batch"], ex["condition"], ex["attribute"],
                                   ex["t_obs"], ex["t_lower_bound"], ex["extrap_factor"], ex["recommendation"]])
    style_header(ws6, len(er_head))

    # 7. 生物制品 CQA 摘要 (R14, 仅生物制品)
    if study.biologic:
        ws7 = wb.create_sheet("生物制品CQA")
        ws7.append(["字段", "值"])
        meta_bio = [
            ("临床阶段", study.stage or "—"),
            ("关联研究ID", study.related_study_id or "—"),
            ("关联类型", study.related_study_type or "—"),
            ("生物制品依据", "ICH Q5C / Q6B"),
            ("效价显著变化阈值", ">10% 相对初始"),
        ]
        for k, v in meta_bio:
            ws7.append([k, v])
        # 显著变化表
        ws7.append([])
        ws7.append(["CQA显著变化明细"])
        sig_head = ["批号", "条件", "CQA", "月点", "变化%", "结论"]
        ws7.append(sig_head)
        if attributes:
            for attr in attributes:
                for s in study.samples:
                    for cond in set(tp.condition for tp in s.time_points):
                        sc = A.biologic_significant_change(study, attr, cond)
                        if sc:
                            ws7.append([sc["batch"], cond, attr, sc["month_of_change"],
                                        sc["change_pct"], sc["conclusion"]])
        # Bootstrap 稳健性
        ws7.append([])
        ws7.append(["批间合并外推稳健性 (Bootstrap/留一法)"])
        boot_head = ["条件", "检测项目", "合并有效期", "CI低", "CI高", "批数", "留一法全批", "最大降幅", "稳健"]
        ws7.append(boot_head)
        for attr in attributes or []:
            cond = None
            lim = None
            for s in study.samples:
                for tp in s.time_points:
                    if any(m.attribute == attr and m.limit_spec is not None for m in s.measurements if m.time_point_id == tp.tp_id):
                        cond = tp.condition
                        lim = next((m.limit_spec for m in s.measurements if m.attribute == attr and m.limit_spec is not None), None)
                        break
                if cond:
                    break
            if not cond or lim is None:
                continue
            ref_val = next((m.value for s in study.samples for m in s.measurements if m.attribute == attr), 0)
            direction = "lower" if lim < ref_val else "upper"
            bs = A.pooled_bootstrap_ci(study, attr, cond, lim, direction)
            lo = A.leave_one_out_expiry(study, attr, cond, lim, direction)
            if bs and lo:
                ws7.append([cond, attr, bs["point_estimate"], bs["ci_low"], bs["ci_high"],
                            bs["n_batches"], lo["full_estimate"], lo["max_drop"],
                            "是" if lo["robust"] else "否"])
        style_header(ws7, 2)

    if path:
        wb.save(path)
        return None
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------
# PDF 导出
# ----------------------------------------------------------------------------
def _build_figures(study: StabilityStudy, attributes: List[str]) -> List[bytes]:
    figs = []
    for attr in attributes:
        fig, ax = plt.subplots(figsize=(7.2, 3.6))
        any_data = False
        for s in study.samples:
            for cond in set(tp.condition for tp in s.time_points):
                months, vals, _ = A._series_for(s, attr, cond)
                if len(vals) >= 1:
                    any_data = True
                    ax.plot(months, vals, marker="o", label=f"{s.batch_id}-{cond}")
                    reg = A.regression_summary(months, vals)
                    if reg and reg["n"] >= 2:
                        xs = [months.min(), months.max()]
                        ys = [reg["intercept"] + reg["slope"] * x for x in xs]
                        ax.plot(xs, ys, "--", alpha=0.5)
        if any_data:
            ax.set_xlabel("时间 (月)")
            ax.set_ylabel(attr)
            ax.set_title(f"{study.drug_name} — {attr}")
            ax.legend(fontsize=7)
            ax.grid(alpha=0.3)
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
            plt.close(fig)
            figs.append(buf.getvalue())
    return figs


def export_pdf(study: StabilityStudy, attributes: List[str], path: str = None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Image)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    if path is None:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
    else:
        doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], fontSize=16)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12)
    elems = []
    elems.append(Paragraph(f"稳定性研究报告 — {study.name}", title))
    elems.append(Paragraph(
        f"药品：{study.drug_name} ｜ 类型：{study.study_type} ｜ "
        f"生物制品：{'是' if study.biologic else '否'} ｜ 分子类型：{study.molecule_type or '—'} ｜ "
        f"设计：{study.design} ｜ 起始：{study.start_date}", styles["Normal"]))
    elems.append(Spacer(1, 0.4 * cm))

    # 分析结果表
    elems.append(Paragraph("一、回归分析与有效期推算", h2))
    if attributes:
        res = A.analyze_study(study, attributes)
        if res:
            cols = ["批号", "条件", "检测项目", "数据点", "斜率/月", "年降解率%", "R²", "p值", "趋势", "有效期(月)", "批间合并有效期(月)", "备注"]
            data = [cols]
            for r in res:
                data.append([r.get(c, "") for c in cols])
            tbl = Table(data, repeatRows=1, hAlign="LEFT")
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6FB")]),
            ]))
            elems.append(tbl)
    elems.append(Spacer(1, 0.4 * cm))

    # 趋势图
    elems.append(Paragraph("二、降解趋势图", h2))
    for img_bytes in _build_figures(study, attributes):
        elems.append(Image(io.BytesIO(img_bytes), width=16 * cm, height=8 * cm))
        elems.append(Spacer(1, 0.2 * cm))

    # 生物制品 CQA 摘要 (R14)
    if study.biologic:
        elems.append(Paragraph("三、生物制品 CQA 合规摘要 (ICH Q5C/Q6B)", h2))
        bio_meta = [
            ["临床阶段", study.stage or "—", "关联研究", study.related_study_id or "—"],
            ["效价显著变化阈值", ">10%", "关联类型", study.related_study_type or "—"],
        ]
        bt = Table(bio_meta, hAlign="LEFT")
        bt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6FB")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ]))
        elems.append(bt)
        elems.append(Spacer(1, 0.2 * cm))
        sig_rows_pdf = []
        for attr in attributes or []:
            for s in study.samples:
                for cond in set(tp.condition for tp in s.time_points):
                    sc = A.biologic_significant_change(study, attr, cond)
                    if sc:
                        sig_rows_pdf.append([sc["batch"], cond, attr, str(sc["month_of_change"]),
                                             str(sc["change_pct"]), sc["conclusion"]])
        if sig_rows_pdf:
            elems.append(Paragraph("CQA 显著变化:", styles["Normal"]))
            stbl = Table([["批号", "条件", "CQA", "月点", "变化%", "结论"]] + sig_rows_pdf, hAlign="LEFT")
            stbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ]))
            elems.append(stbl)

    elems.append(Spacer(1, 0.3 * cm))
    elems.append(Paragraph(
        "注：本报告由稳定性研究管理系统自动生成，有效期结论需由授权人员结合全部CQA综合判定，"
        "并符合21 CFR Part 11与数据完整性要求。", styles["Normal"]))

    # R28：法规依据与阶段合规清单自查（学习/合规价值）
    try:
        import importlib
        T = importlib.import_module("teaching")
        base_reg = "ICH Q1A(R2)/Q1E/Q1D" + ("、Q5C/Q6B（生物制品）" if study.biologic else "")
        elems.append(Spacer(1, 0.2 * cm))
        elems.append(Paragraph(f"合规依据：{base_reg}；数据完整性 ALCOA+。", styles["Normal"]))
        ck = T.checklist_for(study.stage or "")
        if ck:
            elems.append(Paragraph(f"{study.stage or '通用'}阶段合规清单自查：", styles["Normal"]))
            for item in ck:
                elems.append(Paragraph(f"• {item}", styles["Normal"]))
    except Exception:
        pass

    # R29：数据完整性与法规符合性声明（ALCOA+）
    try:
        elems.append(Spacer(1, 0.2 * cm))
        elems.append(Paragraph("数据完整性声明（ALCOA+）：本研究数据遵循可归因(Attributable)、"
                               "易读(Legible)、同步(Contemporaneous)、原始(Original)、准确(Accurate)原则，"
                               "并具备完整(Complete)、一致(Consistent)、持久(Enduring)、可用(Available)属性。", styles["Normal"]))
        elems.append(Paragraph("本稳定性评估结论由软件依据录入数据与既定统计模型自动生成，"
                               "最终有效期/放行决策须由授权质量人员综合判定，符合 21 CFR Part 11 与"
                               "NMPA 相关规范要求。", styles["Normal"]))
    except Exception:
        pass

    doc.build(elems)
    if path is None:
        return buf.getvalue()
    return None


# ----------------------------------------------------------------------------
# 跨研究汇总 Excel (R22)
# ----------------------------------------------------------------------------
def export_study_json(study: StabilityStudy, path: str = None) -> bytes:
    """
    R16 导出研究完整数据包为 JSON（含原始数据 + 关键计算结论）：
    - 供 QA 审核、申报归档、系统间交换（ALCOA+ 可追溯）
    - 结论由 analysis 层实时重算，确保与界面一致
    """
    import json
    attrs = []
    conds = set()
    for s in study.samples:
        for m in s.measurements:
            if m.attribute not in attrs:
                attrs.append(m.attribute)
        for tp in s.time_points:
            conds.add(tp.condition)
    conclusions = {}
    for attr in attrs:
        for cond in conds:
            # 有效期外推
            try:
                ext = A.expiry_extrapolation(study, attr, cond)
            except Exception:
                ext = None
            # 显著变化
            try:
                sc = A.biologic_significant_change(study, attr, cond) if study.biologic else \
                    A.significant_change_assessment(study, attr, cond)
            except Exception:
                sc = None
            conclusions.setdefault(attr, {})[cond] = {
                "expiry_extrapolation": ext,
                "significant_change": sc,
            }
    payload = {
        "meta": study.to_dict(),
        "attributes": attrs,
        "conditions": list(conds),
        "conclusions": conclusions,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    data = text.encode("utf-8")
    if path:
        with open(path, "wb") as f:
            f.write(data)
    return data


def export_cross_study_summary(studies: List[StabilityStudy], path: str = None) -> bytes:
    """导出多研究 CQA 状态汇总工作簿（跨研究仪表），含：汇总、各研究有效期、生物CQA、稳健性。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    head_fill = PatternFill("solid", solid_fill="1F4E78") if hasattr(PatternFill, "solid_fill") else PatternFill("solid", fgColor="1F4E78")
    head_font = Font(color="FFFFFF", bold=True)

    def style_header(ws, ncols):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = head_font

    # 1. 研究总览
    ws = wb.active
    ws.title = "研究总览"
    ws.append(["研究名称", "药品", "类型", "生物制品", "分子类型", "阶段", "关联ID",
               "样品数", "批数", "生成时间"])
    for st in studies:
        ws.append([st.name, st.drug_name, st.study_type, "是" if st.biologic else "否",
                   st.molecule_type or "—", st.stage or "—", st.related_study_id or "—",
                   len(st.samples), len(st.samples),
                   st.created_at])
    style_header(ws, 10)

    # 2. 各研究最严格有效期
    ws2 = wb.create_sheet("有效期汇总")
    ws2.append(["研究", "批号", "检测项目", "条件", "有效期(月)", "建议有效期(月)"])
    for st in studies:
        attrs = sorted({m.attribute for sm in st.samples for m in sm.measurements})
        res = A.analyze_study(st, attrs) if attrs else []
        for r in res:
            if r.get("有效期(月)") is not None:
                ws2.append([st.name, r["批号"], r["检测项目"], r["条件"], r["有效期(月)"], ""])
    style_header(ws2, 6)

    # 3. 生物制品 CQA 显著变化
    ws3 = wb.create_sheet("生物CQA")
    ws3.append(["研究", "批号", "条件", "CQA", "月点", "变化%", "结论"])
    for st in studies:
        if not st.biologic:
            continue
        attrs = sorted({m.attribute for sm in st.samples for m in sm.measurements})
        for attr in attrs:
            for sm in st.samples:
                for cond in set(tp.condition for tp in sm.time_points):
                    try:
                        sc = A.biologic_significant_change(st, attr, cond)
                    except Exception as e:
                        import sys as _sys
                        print(f"[WARN] bio_sig_change failed: study={st.name} attr={attr} cond={cond} err={e}", file=_sys.stderr)
                        sc = None
                    if sc:
                        ws3.append([st.name, sc["batch"], cond, attr,
                                    sc["month_of_change"], sc["change_pct"], sc["conclusion"]])
    style_header(ws3, 7)

    # 4. 批间合并稳健性 (Bootstrap/留一法)
    ws4 = wb.create_sheet("外推稳健性")
    ws4.append(["研究", "条件", "检测项目", "合并有效期", "CI低", "CI高", "批数", "留一法全批", "最大降幅", "稳健"])
    for st in studies:
        attrs = sorted({m.attribute for sm in st.samples for m in sm.measurements})
        for attr in attrs:
            conds = set()
            lim = None
            ref = None
            for sm in st.samples:
                for tp in sm.time_points:
                    for m in sm.measurements:
                        if m.attribute == attr:
                            conds.add(tp.condition)
                            if m.limit_spec is not None and lim is None:
                                lim = m.limit_spec
                                ref = m.value
            cond = next(iter(conds), None)
            if not cond or lim is None or ref is None:
                continue
            direction = "lower" if lim < ref else "upper"
            try:
                bs = A.pooled_bootstrap_ci(st, attr, cond, lim, direction)
                lo = A.leave_one_out_expiry(st, attr, cond, lim, direction)
            except Exception:
                continue
            if bs and lo:
                ws4.append([st.name, cond, attr, bs["point_estimate"], bs["ci_low"],
                            bs["ci_high"], bs["n_batches"], lo["full_estimate"],
                            lo["max_drop"], "是" if lo["robust"] else "否"])
    style_header(ws4, 10)

    # R39：计算结论汇总 sheet
    ws5 = wb.create_sheet("计算结论")
    ws5.append(["研究", "CQA", "条件", "显著变化类型", "最优拟合模型", "最优AIC"])
    for st in studies:
        attrs = sorted({m.attribute for sm in st.samples for m in sm.measurements})
        for attr in attrs:
            conds = set(tp.condition for sm in st.samples for tp in sm.time_points)
            for cond in conds:
                sc = A.biologic_significant_change(st, attr, cond) if st.biologic else A.significant_change_assessment(st, attr, cond)
                ct = sc.get("change_type", "") if sc else ""
                best = ""
                best_aic = ""
                try:
                    bm = A.fit_best_model(st, attr, cond)
                    best = bm["best_model"]
                    best_aic = round(bm["models"][best]["aic"], 1)
                except Exception:
                    pass
                ws5.append([st.name, attr, cond, ct, best, best_aic])
    style_header(ws5, 6)

    buf = io.BytesIO()
    wb.save(buf)
    if path:
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return None
    return buf.getvalue()
