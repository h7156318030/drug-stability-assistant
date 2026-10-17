"""
稳定性研究方案设计 —— 时间点计划生成

依据 ICH Q1A(R2) 推荐时间点，结合研究起始日期自动推算各取样时间点计划日期。
支持：
- 长期 / 加速 / 中间 / 光照 条件
- 括号法(Bracketing) / 矩阵法(Matrixing) 设计的取样点缩减提示（Q1D）
"""

import json
import uuid
from datetime import date, timedelta
from typing import List, Dict
from models import (
    StabilityStudy, Sample, StorageCondition, RECOMMENDED_TIME_POINTS,
    BIO_TIME_POINTS, CONDITION_SPEC, DesignType, MoleculeType,
)


def add_sample_with_plan(study: StabilityStudy, batch_id: str, packaging: str,
                         strength: str, conditions: List[str],
                         start_date: str = None, molecule_type: str = "",
                         custom_months: List[int] = None) -> Sample:
    """
    为研究添加一个样品，并根据所选条件生成取样时间点计划。
    conditions: 条件名列表，如 ["长期","加速"]
    custom_months: R41 可选自定义时间点方案（如 [0,3,6,9,12,18,24]），覆盖默认方案
    """
    sd = start_date or study.start_date
    base = date.fromisoformat(sd)
    sample = Sample(batch_id, packaging, strength, molecule_type)
    tp_source = BIO_TIME_POINTS if study.biologic else RECOMMENDED_TIME_POINTS
    for cond_name in conditions:
        cond = StorageCondition(cond_name)
        if custom_months:
            pts = custom_months
        else:
            pts = tp_source.get(cond, RECOMMENDED_TIME_POINTS.get(cond, [0]))
        for month in pts:
            planned = _add_months(base, month)
            sample.time_points.append(
                __import__("models").TimePoint(month, planned.isoformat(), cond_name)
            )
    study.samples.append(sample)
    return sample


# R41：ICH 标准时间点方案库
TIME_POINT_PRESETS = {
    "标准(0/3/6/9/12/18/24月)": [0, 3, 6, 9, 12, 18, 24],
    "标准(0/1/2/3/6/9/12月)": [0, 1, 2, 3, 6, 9, 12],
    "加速为主(0/1/2/3/6月)": [0, 1, 2, 3, 6],
    "长期精简(0/6/12/24月)": [0, 6, 12, 24],
    "含36月(0/3/6/9/12/18/24/36月)": [0, 3, 6, 9, 12, 18, 24, 36],
}


def _add_months(d: date, months: int) -> date:
    """日期加N个月（按30天/月近似，符合稳定性研究惯例中的月份计数）"""
    # 稳定性研究惯例：月份以30天近似，或按日历月。此处用日历月更直观。
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # 处理月末溢出（如1月31日+1月）
    day = min(d.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def plan_summary(study: StabilityStudy) -> List[Dict]:
    """返回取样计划概览（用于UI表格）"""
    rows = []
    for s in study.samples:
        for tp in s.time_points:
            rows.append({
                "样品批号": s.batch_id,
                "包装": s.packaging,
                "规格": s.strength,
                "条件": tp.condition,
                "月点": tp.month,
                "计划日期": tp.planned_date,
                "状态": tp.status,
                "已取样": "是" if tp.pulled else "否",
            })
    return rows


def design_advice(study: StabilityStudy) -> str:
    """根据设计类型给出 Q1D 设计提示"""
    if study.design == DesignType.BRACKETING:
        return ("括号法(Bracketing, Q1D)：仅对极端条件（如最小/最大包装、最低/最高规格）"
                "的样品在所有时间点全检，中间批次可省略。适用于包装/规格因子明确且影响方向已知的场景。")
    if study.design == DesignType.MATRIXING:
        return ("矩阵法(Matrixing, Q1D)：在全部时间点中，对每个样品仅取部分时间点检测，"
                "各样品互补覆盖完整时间点。可减少检测量，但需统计学论证并增加不确定性。")
    return ("全检设计(Full)：所有样品在所有推荐时间点均检测，数据最完整，统计把握度最高。")


def condition_specs() -> Dict[str, str]:
    return {c.value: CONDITION_SPEC[c] for c in StorageCondition}


# ----------------------------------------------------------------------------
# 方案模板库（常见产品稳定性研究设计模板）
# ----------------------------------------------------------------------------
TEMPLATES = {
    "化药片剂(室温)": {
        "molecule_type": "化学药", "biologic": False, "design": "全检",
        "conditions": ["长期", "加速"],
        "attributes": ["含量", "有关物质", "水分", "溶出度"],
        "limits": {"含量": (90.0, "lower"), "有关物质": (2.0, "upper"), "水分": (5.0, "upper")},
    },
    "单抗注射剂(冷藏)": {
        "molecule_type": "单抗", "biologic": True, "design": "全检",
        "conditions": ["冷藏", "加速"],
        "attributes": ["效价", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体"],
        "limits": {"效价": (80.0, "lower"), "聚集体": (5.0, "upper"), "碎片": (10.0, "upper"),
                   "脱酰胺": (15.0, "upper"), "电荷异质体": (30.0, "upper")},
    },
    "质粒DNA(冷冻)": {
        "molecule_type": "质粒", "biologic": True, "design": "全检",
        "conditions": ["冷冻-20", "冷冻-80"],
        "attributes": ["超螺旋比例", "含量", "杂质"],
        "limits": {"超螺旋比例": (80.0, "lower"), "含量": (90.0, "lower")},
    },
    "冻干粉(室温)": {
        "molecule_type": "化学药", "biologic": False, "design": "全检",
        "conditions": ["长期", "加速"],
        "attributes": ["含量", "有关物质", "水分", "pH"],
        "limits": {"含量": (90.0, "lower"), "有关物质": (3.0, "upper"), "水分": (2.0, "upper")},
    },
    # ---- 生物制品专属模板 (ICH Q5C / NMPA 生物制品指导原则) ----
    "单抗原液DS(冷冻)": {
        "molecule_type": "单抗", "biologic": True, "design": "全检",
        "stage": "III期临床",
        "conditions": ["冷冻-80", "强制降解", "冻融循环"],
        "attributes": ["效价", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体", "不溶性微粒"],
        "limits": {"效价": (80.0, "lower"), "聚集体": (5.0, "upper"), "碎片": (10.0, "upper"),
                   "脱酰胺": (15.0, "upper"), "电荷异质体": (30.0, "upper"), "不溶性微粒": (6000.0, "upper")},
        "note": "原液(DS)稳定性为制剂(DP)有效期的上游支撑。强制降解确证稳定性指示方法；冻融循环考察5次。",
    },
    "单抗制剂DP(冷藏)": {
        "molecule_type": "单抗", "biologic": True, "design": "全检",
        "stage": "III期临床",
        "conditions": ["冷藏", "强制降解", "冻融循环", "使用中", "运输"],
        "attributes": ["效价", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体", "不溶性微粒", "可见异物"],
        "limits": {"效价": (80.0, "lower"), "聚集体": (5.0, "upper"), "碎片": (10.0, "upper"),
                   "脱酰胺": (15.0, "upper"), "电荷异质体": (30.0, "upper"), "不溶性微粒": (6000.0, "upper")},
        "note": "制剂(DP)为核心申报单元。含复溶后使用中(in-use)与运输稳定性。",
    },
    "重组蛋白(冷藏)": {
        "molecule_type": "蛋白", "biologic": True, "design": "全检",
        "stage": "II期临床",
        "conditions": ["冷藏", "强制降解", "冻融循环", "运输"],
        "attributes": ["效价", "聚集体", "碎片", "氧化", "糖基化", "不溶性微粒"],
        "limits": {"效价": (80.0, "lower"), "聚集体": (5.0, "upper"), "碎片": (10.0, "upper"),
                   "糖基化": (50.0, "upper")},
    },
    "疫苗(冷藏)": {
        "molecule_type": "疫苗", "biologic": True, "design": "全检",
        "stage": "II期临床",
        "conditions": ["冷藏", "强制降解", "运输"],
        "attributes": ["效价", "聚集体", "不溶性微粒", "可见异物", "pH"],
        "limits": {"效价": (80.0, "lower"), "聚集体": (8.0, "upper"), "不溶性微粒": (6000.0, "upper")},
    },
    "细胞治疗产品(液氮/冷藏)": {
        "molecule_type": "细胞", "biologic": True, "design": "全检",
        "stage": "I期临床",
        "conditions": ["冷冻-80", "冷藏", "运输"],
        "attributes": ["效价", "活细胞率", "聚集体", "不溶性微粒", "可见异物"],
        "limits": {"效价": (70.0, "lower"), "活细胞率": (70.0, "lower"), "聚集体": (10.0, "upper")},
        "note": "细胞治疗产品通常考察冷链(2-8°C)运输及复温后使用窗，液氮/冻存为长期储存。",
    },
    "基因治疗载体(冻存)": {
        "molecule_type": "病毒载体", "biologic": True, "design": "全检",
        "stage": "I期临床",
        "conditions": ["冷冻-80", "冷冻-20", "冻融循环", "运输"],
        "attributes": ["效价", "感染滴度", "聚集体", "不溶性微粒", "可见异物"],
        "limits": {"效价": (70.0, "lower"), "感染滴度": (70.0, "lower"), "聚集体": (10.0, "upper")},
        "note": "病毒载体/AAV 关注感染滴度(infectious titer)与物理滴度(physical titer)比值。",
    },
    "生物类似药可比性(冷藏)": {
        "molecule_type": "单抗", "biologic": True, "design": "全检",
        "stage": "BLA申报",
        "conditions": ["冷藏", "强制降解", "冻融循环", "使用中"],
        "attributes": ["效价", "聚集体", "碎片", "脱酰胺", "氧化", "电荷异质体", "糖基化", "不溶性微粒"],
        "limits": {"效价": (80.0, "lower"), "聚集体": (5.0, "upper"), "碎片": (10.0, "upper")},
        "note": "可比性(comparability)研究：变更前后稳定性对比，关注 CQA 漂移是否等效。",
    },
}


def create_from_template(template_name: str, study_name: str, sponsor: str,
                          batches: List[str], start_date: str,
                          stage: str = "") -> StabilityStudy:
    """
    基于模板创建研究：自动设置分子类型、生物制品标识、设计、条件、检测项目、
    限度（含方向）、并为各批次按条件生成推荐时间点取样计划。
    支持临床阶段(stage)与 DS/DP 关联（related 由调用方设置）。
    返回新建的 StabilityStudy 对象（调用方负责入库）。
    """
    tpl = TEMPLATES[template_name]
    study = StabilityStudy(
        name=study_name, study_type="稳定性研究", drug_name=study_name,
        sponsor=sponsor, design=tpl["design"], start_date=start_date,
        biologic=tpl["biologic"], molecule_type=tpl["molecule_type"],
        stage=stage or tpl.get("stage", ""),
    )
    for b in batches:
        add_sample_with_plan(study, b, "市售包装", "", tpl["conditions"])
    study._template_limits = tpl.get("limits", {})
    study._template_attrs = tpl.get("attributes", [])
    study._template_conditions = tpl.get("conditions", [])
    study._template_note = tpl.get("note", "")
    return study


def template_note(template_name: str) -> str:
    """返回模板备注（教学/合规提示）"""
    return TEMPLATES.get(template_name, {}).get("note", "")


def list_templates() -> List[str]:
    return list(TEMPLATES.keys())


def matrix_design_reduction(study: StabilityStudy) -> Dict:
    """
    矩阵/括号设计取样点缩减计算（ICH Q1D）。
    输入：研究设计类型、样品组合数（批次×包装×规格）。
    输出：全检取样单元总数、采用设计后的实际取样单元数、缩减比例(%)、
          各组合的取样覆盖说明，以及是否符合 Q1D 缩减适用条件。
    计算规则（基于 Q1D 经验，适用于因子水平≤3、组合完整的两两正交设计）：
      - 全检(Full)：N_total = 组合数 × 时间点
      - 矩阵(Matrixing, k 因子各 2 水平)：取样单元 ≈ N_total / 2（互补覆盖）
      - 括号(Bracketing)：仅极端组合（最小-最小…最大-最大）全检，中间组合免检；
            实际组合数 = 2^k（k 为括号因子数），其余免检
    返回结构化结论供方案优化与成本估算。
    """
    # 组合数：按 批次×包装×规格 去重计数
    combos = set()
    for s in study.samples:
        combos.add((s.batch_id, s.packaging, s.strength))
    n_combos = len(combos)
    # 每个样品的时间点（取第一个样品的时间点集合作为代表）
    rep_tp = set()
    for s in study.samples:
        for tp in s.time_points:
            rep_tp.add(tp.month)
    n_tp = len(rep_tp)
    full = n_combos * n_tp
    if study.design == DesignType.MATRIXING:
        reduced = full // 2 if full >= 2 else full
        reduction = (1 - reduced / full) * 100.0 if full else 0.0
        advice = "矩阵法：各组合互补覆盖时间点，取样单元约减半。"
        compliant = n_combos >= 2 and n_tp >= 3
    elif study.design == DesignType.BRACKETING:
        # 括号因子=批次/包装/规格中水平数>1的维度数（这里以批次数估算极端组合）
        n_batches = len({s.batch_id for s in study.samples})
        if n_batches >= 2:
            bracket_combos = 2  # 最小与最大批次组合
            reduced = bracket_combos * n_tp
        else:
            reduced = full
        reduction = (1 - reduced / full) * 100.0 if full else 0.0
        advice = "括号法：仅极端批次组合全检，中间批次免检。"
        compliant = n_batches >= 2
    else:
        reduced = full
        reduction = 0.0
        advice = "全检设计：无缩减。"
        compliant = True
    return {
        "n_combos": n_combos,
        "n_time_points": n_tp,
        "full_units": full,
        "reduced_units": reduced,
        "reduction_pct": round(reduction, 1),
        "advice": advice,
        "q1d_compliant": compliant,
        "note": "" if compliant else "当前组合不满足 Q1D 缩减适用条件（因子/水平不足）",
    }
