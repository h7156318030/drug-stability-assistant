"""
药品稳定性研究 —— 数据模型（持久化由 db.py 负责）

设计依据（ICH规范要点）：
- ICH Q1A(R2): 新原料药和制剂的稳定性试验
    * 长期条件(Long Term): 25°C ±2°C / 60%RH ±5%RH，时间点 0,3,6,9,12,18,24,36,...月
    * 加速条件(Accelerated): 40°C ±2°C / 75%RH ±5%RH，时间点 0,3,6月(个别6月)
    * 中间条件(Intermediate): 30°C ±2°C / 65%RH ±5%RH，当加速6月显著变化时启用，时间点 0,6,9,12,18月
- ICH Q1B: 光照稳定性（总照度≥1.2×10^6 lux·hr，紫外≥200 Wh/m²）
- ICH Q1C: 新剂型
- ICH Q1D: 括号法(Bracketing)与矩阵法(Matrixing)设计
- ICH Q1E: 稳定性数据评价（有效期/复验期推算）
- ICH Q2(R1): 分析方法论证（含量、有关物质等）
"""

import math
import uuid
from datetime import date, datetime
from enum import Enum
from typing import List, Dict, Optional, Any


# ----------------------------------------------------------------------------
# 枚举定义
# ----------------------------------------------------------------------------
class StorageCondition(str, Enum):
    LONG_TERM = "长期"          # 25°C/60%RH（化药）
    ACCELERATED = "加速"        # 40°C/75%RH
    INTERMEDIATE = "中间"       # 30°C/65%RH
    PHOTOSTABILITY = "光照"     # Q1B
    # 生物制品常用条件 (ICH Q5C)
    REFRIGERATED = "冷藏"       # 2–8°C（生物制品长期主流）
    FROZEN_MINUS20 = "冷冻-20"  # -20°C ±5°C
    FROZEN_MINUS80 = "冷冻-80"  # -80°C ±10°C（质粒/细胞/病毒载体）
    # 生物制品特殊稳定性条件 (ICH Q5C / NMPA 生物制品指导原则)
    FORCED_DEGRADATION = "强制降解"  # 强制降解/应激(stress)：高温/高湿/光照/氧化/酸碱
    FREEZE_THAW = "冻融循环"         # 冻融循环（通常 5 次，-20/-80 ↔ 室温）
    IN_USE = "使用中"                # 复溶后/使用中(in-use)稳定性
    TRANSPORT = "运输"               # 运输稳定性（模拟运输振动/温度偏移）


# ICH Q1A(R2) 推荐时间点（月）—— 化药
RECOMMENDED_TIME_POINTS = {
    StorageCondition.LONG_TERM: [0, 3, 6, 9, 12, 18, 24, 36],
    StorageCondition.ACCELERATED: [0, 3, 6],
    StorageCondition.INTERMEDIATE: [0, 6, 9, 12, 18],
    StorageCondition.PHOTOSTABILITY: [0],  # 通常 0 与光照后
}

# 生物制品常用条件时间点 (ICH Q5C)：冷藏/冻存通常 0,3,6,9,12,18,24,36 月，冻存可延长至60月
BIO_TIME_POINTS = {
    StorageCondition.REFRIGERATED: [0, 3, 6, 9, 12, 18, 24, 36],
    StorageCondition.FROZEN_MINUS20: [0, 3, 6, 9, 12, 18, 24, 36, 48, 60],
    StorageCondition.FROZEN_MINUS80: [0, 3, 6, 9, 12, 18, 24, 36, 48, 60],
    # 生物制品特殊条件时间点
    StorageCondition.FORCED_DEGRADATION: [0],  # 通常为 0 与各应激暴露后单点评估
    StorageCondition.FREEZE_THAW: [0, 1, 2, 3, 5],  # 冻融循环次数（cycle）
    StorageCondition.IN_USE: [0, 1, 2, 7, 14, 28],  # 复溶后天数（in-use）
    StorageCondition.TRANSPORT: [0],  # 运输模拟后单点
}

# 生物制品特殊条件说明（用于教学/提示）
SPECIAL_CONDITION_DESC = {
    StorageCondition.FORCED_DEGRADATION: "强制降解研究用于确证分析方法具有稳定性指示能力(stability-indicating)，应考察高温、高湿、光照、氧化、酸/碱等应激。",
    StorageCondition.FREEZE_THAW: "冻融循环考察原液或制剂在冷冻-解冻过程中的稳定性，常见设计 5 个循环（-20/-80°C ↔ 室温），每个循环后检测 CQA。",
    StorageCondition.IN_USE: "复溶后/使用中的稳定性(in-use)，确定配制后至给药前的允许存放时间与温度。",
    StorageCondition.TRANSPORT: "运输稳定性模拟实际运输条件（温度偏移、振动、光照），ICH Q5C 要求考察。",
}

# ICH Q1B 光照条件（D65 日光荧光灯+近紫外灯）暴露要求
# 选项1（常规）：总照度≥1.2×10^6 lux·hr，近紫外能量≥200 W·hr/m²
# 选项2（强化）：总照度≥2.4×10^6 lux·hr，近紫外能量≥300 W·hr/m²
PHOTO_Q1B_OPTION1 = {"total_lux_hr": 1.2e6, "uv_wh_m2": 200.0}
PHOTO_Q1B_OPTION2 = {"total_lux_hr": 2.4e6, "uv_wh_m2": 300.0}


# 各条件的温湿度标签
CONDITION_SPEC = {
    StorageCondition.LONG_TERM: "25°C ±2°C / 60%RH ±5%RH",
    StorageCondition.ACCELERATED: "40°C ±2°C / 75%RH ±5%RH",
    StorageCondition.INTERMEDIATE: "30°C ±2°C / 65%RH ±5%RH",
    StorageCondition.PHOTOSTABILITY: "总照度≥1.2×10⁶ lux·hr, UV≥200 Wh/m²",
    StorageCondition.REFRIGERATED: "2–8°C（避光）",
    StorageCondition.FROZEN_MINUS20: "-20°C ±5°C",
    StorageCondition.FROZEN_MINUS80: "-80°C ±10°C",
    StorageCondition.FORCED_DEGRADATION: "高温/高湿/光照/氧化/酸碱(应激)",
    StorageCondition.FREEZE_THAW: "冻融循环(-20/-80°C ↔ 室温, N次)",
    StorageCondition.IN_USE: "复溶后/使用中(通常 2–8°C 或室温)",
    StorageCondition.TRANSPORT: "运输模拟(温度偏移+振动)",
}


class DevelopmentStage(str, Enum):
    """生物制品临床开发阶段 (NMPA/ICH Q5C 阶段性稳定性)"""
    PRECLINICAL = "临床前"
    PHASE_I = "I期临床"
    PHASE_II = "II期临床"
    PHASE_III = "III期临床"
    BLA = "BLA申报"
    POST_MARKET = "上市后"
    COMMERCIAL = "商业化"


# 各阶段稳定性策略要点（教学提示）
STAGE_GUIDANCE = {
    DevelopmentStage.PRECLINICAL: "临床前：原液+制剂初步稳定性，支持毒理批与早期临床。",
    DevelopmentStage.PHASE_I: "I期：原液(DS)与制剂(DP)正式稳定性启动，至少中试规模，冷藏/冻存长期+加速。",
    DevelopmentStage.PHASE_II: "II期：代表性中试/商业规模，多批次，强化 CQA 监测。",
    DevelopmentStage.PHASE_III: "III期：商业规模代表性批次，长期+加速，支撑有效期申报。",
    DevelopmentStage.BLA: "BLA：提交全套稳定性数据，外推需谨慎并附依据(ICH Q1E)。",
    DevelopmentStage.POST_MARKET: "上市后：持续稳定性考察(OOS/年度), 货架期监测。",
    DevelopmentStage.COMMERCIAL: "商业化：上市后承诺(on-going)稳定性，批次放行关联。",
}


class StudyType(str, Enum):
    DRUG_SUBSTANCE = "原料药"     # API
    DRUG_PRODUCT = "制剂"         # 制剂


class DesignType(str, Enum):
    FULL = "全检"               # 完整设计
    BRACKETING = "括号法"       # Q1D Bracketing
    MATRIXING = "矩阵法"        # Q1D Matrixing


class MoleculeType(str, Enum):
    """生物制品分子类型 (ICH Q5C/Q6B)"""
    PROTEIN = "重组蛋白"
    ANTIBODY = "单抗/抗体"
    PLASMID = "质粒DNA"
    VIRAL_VECTOR = "病毒载体"
    VACCINE = "疫苗"
    CELL = "细胞治疗"
    PEPTIDE = "多肽"
    CHEMICAL = "化学药"


class TestAttribute(str, Enum):
    # 化药通用
    ASSAY = "含量"              # 含量/效价 %
    RELATED_SUBSTANCES = "有关物质"  # 有关物质 %
    DISSOLUTION = "溶出度"      # 溶出 %
    WATER = "水分"              # 水分 %
    PH = "pH"
    APPEARANCE = "性状"
    IMPURITY = "杂质"
    # 生物制品专用 CQA (ICH Q5C / Q6B)
    POTENCY = "效价"            # 生物效价（相对标示量 %）
    AGGREGATES = "聚集体"       # 高分子量物质 / 聚集体 %
    FRAGMENTS = "碎片"          # 低分子量碎片 %
    DEAMIDATION = "脱酰胺"      # 脱酰胺异构体 %
    OXIDATION = "氧化"          # 氧化变体 %
    CLARITY = "澄清度"          # 外观/澄清度
    SUBVISIBLE = "不溶性微粒"   # 亚可见/不溶性微粒（≥10μm, ≥25μm 个/剂）
    VISIBLE = "可见异物"        # 可见异物（定性）
    GLYCOSYLATION = "糖基化"    # 糖型分布 %
    CHARGE_VARIANT = "电荷异质体"  # 酸性/碱性变体 %
    BINDING = "结合活性"        # 受体/抗原结合 %
    OSMOLARITY = "渗透压"       # 渗透压摩尔浓度 mOsm/kg
    CONTAINER_INTEGRITY = "容器密封"  # CCIT 容器密封完整性（通过/失败 或 泄漏率）
    CUSTOM = "自定义"


# ----------------------------------------------------------------------------
# 数据类
# ----------------------------------------------------------------------------
class TimePoint:
    def __init__(self, month: int, planned_date: str, condition: str):
        self.tp_id = str(uuid.uuid4())[:8]   # 唯一时间点标识（支持同month多条件精确配对）
        self.month = month
        self.planned_date = planned_date          # ISO date 字符串
        self.condition = condition
        self.status = "计划中"                    # 计划中/已取样/检测中/已完成/超期
        self.pulled = False                       # 是否已取样

    def to_dict(self) -> Dict:
        return {
            "tp_id": self.tp_id,
            "month": self.month,
            "planned_date": self.planned_date,
            "condition": self.condition,
            "status": self.status,
            "pulled": self.pulled,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "TimePoint":
        tp = cls(d["month"], d["planned_date"], d["condition"])
        tp.tp_id = d.get("tp_id", str(uuid.uuid4())[:8])
        tp.status = d.get("status", "计划中")
        tp.pulled = d.get("pulled", False)
        return tp


class Measurement:
    """单次检测值（某个时间点、某个检测项目的数值）"""

    def __init__(self, time_point_id: str, attribute: str, value: Optional[float],
                 unit: str = "", limit_spec: Optional[float] = None,
                 is_limit: bool = False, note: str = "", cqa_category: str = "",
                 direction: str = "", tp_ref: str = "", resolution: float = None,
                 peak_purity: float = None):
        self.time_point_id = time_point_id      # 关联的 month（时序图用）
        self.tp_ref = tp_ref or ""              # 关联的 tp_id（精确配对，同month多条件）
        self.attribute = attribute          # 检测项目名
        self.value = value                  # 数值（None表示未检）
        self.unit = unit
        self.limit_spec = limit_spec        # 质量标准限度
        self.is_limit = is_limit            # True=上限限度（不可超过），False=下限限度（不可低于）
        self.note = note
        self.cqa_category = cqa_category    # 生物制品CQA归类（如 聚集体/效价）
        self.direction = direction          # 有效期推算方向 lower/upper
        self.resolution = resolution        # 分离度 Rs（稳定性指示能力：降解物与主峰）
        self.peak_purity = peak_purity      # 峰纯度 %（主峰纯度）

    def to_dict(self) -> Dict:
        return {
            "time_point_id": self.time_point_id,
            "tp_ref": self.tp_ref,
            "attribute": self.attribute,
            "value": self.value,
            "unit": self.unit,
            "limit_spec": self.limit_spec,
            "is_limit": self.is_limit,
            "note": self.note,
            "cqa_category": self.cqa_category,
            "direction": self.direction,
            "resolution": self.resolution,
            "peak_purity": self.peak_purity,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Measurement":
        return cls(d["time_point_id"], d["attribute"], d.get("value"),
                   d.get("unit", ""), d.get("limit_spec"), d.get("is_limit", False),
                   d.get("note", ""), d.get("cqa_category", ""), d.get("direction", ""),
                   d.get("tp_ref", ""), d.get("resolution"), d.get("peak_purity"))


class Sample:
    def __init__(self, batch_id: str, packaging: str, strength: str = "",
                 molecule_type: str = ""):
        self.sample_id = str(uuid.uuid4())[:8]
        self.batch_id = batch_id
        self.packaging = packaging              # 包装规格/容器
        self.strength = strength                # 规格（如 10mg）
        self.molecule_type = molecule_type      # 分子类型（生物制品）
        self.time_points: List[TimePoint] = []
        self.measurements: List[Measurement] = []

    def to_dict(self) -> Dict:
        return {
            "sample_id": self.sample_id,
            "batch_id": self.batch_id,
            "packaging": self.packaging,
            "strength": self.strength,
            "molecule_type": self.molecule_type,
            "time_points": [tp.to_dict() for tp in self.time_points],
            "measurements": [m.to_dict() for m in self.measurements],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Sample":
        s = cls(d["batch_id"], d["packaging"], d.get("strength", ""),
                d.get("molecule_type", ""))
        s.sample_id = d["sample_id"]
        s.time_points = [TimePoint.from_dict(x) for x in d.get("time_points", [])]
        s.measurements = [Measurement.from_dict(x) for x in d.get("measurements", [])]
        return s


class StabilityStudy:
    def __init__(self, name: str, study_type: str, drug_name: str,
                 sponsor: str = "", design: str = DesignType.FULL,
                 start_date: str = None, biologic: bool = False,
                 molecule_type: str = "", stage: str = "",
                 related_study_id: str = "", related_study_type: str = ""):
        self.study_id = str(uuid.uuid4())[:8]
        self.name = name
        self.study_type = study_type            # 原料药/制剂
        self.drug_name = drug_name
        self.sponsor = sponsor
        self.design = design if isinstance(design, str) else design.value
        self.biologic = biologic                # 是否生物制品
        self.molecule_type = molecule_type      # 分子类型
        self.stage = stage if isinstance(stage, str) else (stage.value if stage else "")
        self.related_study_id = related_study_id      # 关联研究（DS↔DP 联动, Q5C）
        self.related_study_type = related_study_type  # 关联类型描述
        self.start_date = start_date or date.today().isoformat()
        self.samples: List[Sample] = []
        self.created_at = datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> Dict:
        return {
            "study_id": self.study_id,
            "name": self.name,
            "study_type": self.study_type,
            "drug_name": self.drug_name,
            "sponsor": self.sponsor,
            "design": self.design,
            "biologic": self.biologic,
            "molecule_type": self.molecule_type,
            "stage": self.stage,
            "related_study_id": self.related_study_id,
            "related_study_type": self.related_study_type,
            "start_date": self.start_date,
            "created_at": self.created_at,
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "StabilityStudy":
        st = cls(d["name"], d["study_type"], d["drug_name"], d.get("sponsor", ""),
                 d.get("design", DesignType.FULL), d.get("start_date"),
                 bool(d.get("biologic", False)), d.get("molecule_type", ""),
                 d.get("stage", ""), d.get("related_study_id", ""),
                 d.get("related_study_type", ""))
        st.study_id = d["study_id"]
        st.created_at = d.get("created_at", st.created_at)
        st.samples = [Sample.from_dict(x) for x in d.get("samples", [])]
        return st


# ----------------------------------------------------------------------------
# 生物制品 CQA 默认限度方向（用于有效期推算）
#   lower: 指标不应低于限度（如效价≥80%）
#   upper: 指标不应高于限度（如聚集体≤5%）
# ----------------------------------------------------------------------------
BIO_CQA_DIRECTION = {
    "效价": ("lower", 80.0),
    "结合活性": ("lower", 80.0),
    "聚集体": ("upper", 5.0),
    "碎片": ("upper", 10.0),
    "脱酰胺": ("upper", 15.0),
    "氧化": ("upper", 10.0),
    "电荷异质体": ("upper", 35.0),
    "糖基化": ("upper", 50.0),
    "不溶性微粒": ("upper", 6000.0),   # ≥10μm 个/剂 示例限度
    "含量": ("lower", 90.0),
    "有关物质": ("upper", 2.0),
    "水分": ("upper", 3.0),
    "渗透压": ("range", 0.0),          # 范围指标，具体范围见 RANGE_LIMITS
    "pH": ("range", 0.0),              # 范围指标，具体范围见 RANGE_LIMITS
    "可见异物": ("pass", 0.0),         # 定性指标（符合规定/不符合）
}

# 范围型指标（pH、渗透压）的可接受范围 [下界, 上界]
# 渗透压：通常以标示值的 ±10% 或 ±15 mOsm/kg 验收；此处给典型范围，用户可按处方覆盖
RANGE_LIMITS = {
    "pH": (5.0, 7.4),                 # 单抗注射液常见 pH 范围（可按处方调整）
    "渗透压": (240.0, 360.0),         # 接近生理渗透压（mOsm/kg）
}


def range_limit_for(attribute: str):
    """返回范围指标的可接受 [lo, hi]，否则 None"""
    return RANGE_LIMITS.get(attribute)


def default_limit_for(attribute: str):
    """返回 (direction, limit) 或 None"""
    return BIO_CQA_DIRECTION.get(attribute)


# 各检测项目的物理合理范围 [下界, 上界]（用于录入实时校验，非质量标准）
PLAUSIBLE_RANGE = {
    "效价": (0.0, 130.0),
    "结合活性": (0.0, 130.0),
    "聚集体": (0.0, 100.0),
    "碎片": (0.0, 100.0),
    "脱酰胺": (0.0, 100.0),
    "氧化": (0.0, 100.0),
    "电荷异质体": (0.0, 100.0),
    "糖基化": (0.0, 100.0),
    "不溶性微粒": (0.0, 1e6),
    "含量": (0.0, 130.0),
    "有关物质": (0.0, 100.0),
    "水分": (0.0, 100.0),
    "pH": (0.0, 14.0),
    "渗透压": (0.0, 5000.0),
}


def validate_measurement(attribute: str, value: Optional[float],
                         unit: str = "", limit_spec: Optional[float] = None,
                         direction: str = "") -> List[str]:
    """
    录入实时校验：返回告警信息列表（空列表=通过）。
    校验项：
      1) 数值非空且为有限数
      2) 在物理合理范围 PLAUSIBLE_RANGE 内（超出提示疑似录入错误）
      3) 单位非空
      4) 限度逻辑：direction=lower 时限度应>0；录入值不应已远超限度的极端情况温和提醒
    不阻断录入（仅提示），符合 GMP 数据复核"质疑而非拒绝"原则。
    """
    warns = []
    if value is None:
        return warns  # 未录入不告警
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ["数值无法解析为有效数字"]
    if not math.isfinite(v):
        warns.append("数值非有限（NaN/Inf）")
        return warns
    rng = PLAUSIBLE_RANGE.get(attribute)
    if rng and (v < rng[0] or v > rng[1]):
        warns.append(f"{attribute} 值 {v} 超出合理范围 {rng[0]}~{rng[1]}，疑似录入错误")
    if not unit:
        warns.append(f"{attribute} 未填写单位")
    if limit_spec is not None:
        try:
            lim = float(limit_spec)
            if direction == "lower" and lim <= 0:
                warns.append("下限限度应>0")
            if direction == "upper" and lim < 0:
                warns.append("上限限度不应为负")
            # 温和提醒：录入值已超限
            if direction == "lower" and v < lim:
                warns.append(f"录入值 {v} 已低于下限限度 {lim}（已超标）")
            if direction == "upper" and v > lim:
                warns.append(f"录入值 {v} 已高于上限限度 {lim}（已超标）")
        except (TypeError, ValueError):
            warns.append("限度值无法解析")
    # 范围型指标（pH / 渗透压）：依据处方可接受范围校验
    if direction == "range":
        rl = range_limit_for(attribute)
        if rl:
            lo, hi = rl
            if v < lo or v > hi:
                warns.append(f"{attribute} {v} 超出可接受范围 {lo}~{hi}（偏离处方规格，需调查）")
    # 定性指标（可见异物）：仅记录，不做数值判断
    if direction == "pass" and unit == "":
        warns.append("可见异物建议填写判定（符合规定/不符合规定）于单位或备注")
    return warns
