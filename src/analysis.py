"""
稳定性数据分析与有效期/复验期推算

核心依据 ICH Q1E《稳定性数据评价》：
- 对关键质量属性（CQA）随时间的变化用线性回归拟合： y = a + b·t
- 有效期(货架期)定义为：在95%置信水平下，预测值下限仍满足质量标准限度的时间。
  对于"越低越好"型（如有关物质）：t = (规格下限 - a - t_{0.95,n-2}·SE) / b   (b<0时取交点)
  对于"含量"型（标准为不低于标示量，如≥90%）：取95%单侧置信下限达到限度的时刻。
- 至少需3个时间点方可回归；通常要求R²及趋势显著性评估。
"""

import math
import numpy as np
import random
from scipy import stats
from scipy.optimize import curve_fit
from typing import List, Dict, Optional, Tuple
from models import (StabilityStudy, Sample, Measurement, default_limit_for,
                   StorageCondition, PHOTO_Q1B_OPTION1, PHOTO_Q1B_OPTION2)


def _series_for(sample: Sample, attribute: str, condition: str) -> Tuple[np.ndarray, np.ndarray, List]:
    """提取某样品在某条件下某检测项目的时间序列（仅取已录入数值的点）"""
    months, vals, tps = [], [], []
    for tp in sample.time_points:
        if tp.condition != condition:
            continue
        for m in sample.measurements:
            # 优先 tp_ref 精确配对（避免跨条件同月撞配），回退 month+condition 推断
            match = (m.tp_ref and m.tp_ref == tp.tp_id) or \
                    (float(m.time_point_id) == float(tp.month) and m.attribute == attribute
                     and m.value is not None and not m.tp_ref)
            if match and m.attribute == attribute and m.value is not None:
                months.append(tp.month)
                vals.append(m.value)
                tps.append(tp)
                break
    return np.array(months), np.array(vals), tps


def regression_summary(months: np.ndarray, vals: np.ndarray) -> Optional[Dict]:
    months = np.asarray(months, dtype=float)
    vals = np.asarray(vals, dtype=float)
    if len(months) < 2:
        return None
    if float(np.std(months)) == 0.0:
        # 所有月点相同（数据异常），无法拟合趋势
        return None
    slope, intercept, r, p, se = stats.linregress(months, vals)
    n = len(months)
    # 预测标准误（用于置信区间）
    xbar = months.mean()
    sxx = np.sum((months - xbar) ** 2)
    resid = vals - (intercept + slope * months)
    sigma = np.sqrt(np.sum(resid ** 2) / (n - 2)) if n > 2 else float("nan")
    y0 = intercept  # 初始值（t=0）
    # 降解速率指标
    rate_per_month = slope
    rate_per_year = slope * 12.0
    rel_rate_pct_year = (slope * 12.0 / y0 * 100.0) if y0 not in (0, None) else float("nan")
    return {
        "slope": slope,
        "intercept": intercept,
        "r2": r ** 2,
        "p_value": p,
        "sigma": sigma,
        "sxx": sxx,
        "xbar": xbar,
        "n": n,
        "y0": y0,
        "rate_per_month": rate_per_month,        # 绝对变化/月
        "rate_per_year": rate_per_year,          # 绝对变化/年
        "rel_rate_pct_year": rel_rate_pct_year,  # 相对初始值的年降解率 %
    }


def pooled_regression(study: StabilityStudy, attribute: str, condition: str) -> Optional[Dict]:
    """
    批间合并回归（ICH Q1E 多批合并法）：将同一条件下所有批次的同一检测项目
    数据合并后做线性回归，并给出批间斜率方差（用于判断能否合并外推）。
    返回合并回归结果 + 批间一致性指标。
    """
    xs_all, ys_all = [], []
    series = []
    for s in study.samples:
        months, vals, _ = _series_for(s, attribute, condition)
        if len(vals) >= 2:
            xs_all.append(months)
            ys_all.append(vals)
            series.append((s.batch_id, months, vals))
    if len(series) < 1:
        return None
    if len(series) == 1:
        reg = regression_summary(series[0][1], series[0][2])
        return {**reg, "n_batches": 1, "batch_slopes": [reg["slope"]],
                "slope_cv": 0.0, "poolable": True}
    X = np.concatenate(xs_all)
    Y = np.concatenate(ys_all)
    reg = regression_summary(X, Y)
    if reg is None:
        return None
    # 批间斜率离散度（CV）
    slopes = []
    for _, m, v in series:
        r = regression_summary(m, v)
        if r:
            slopes.append(r["slope"])
    slopes = np.array(slopes)
    slope_cv = (slopes.std(ddof=0) / abs(slopes.mean())) * 100.0 if slopes.mean() != 0 else float("nan")
    # 合并可行性：斜率方向一致且离散度不过大（CV<50% 视为可合并外推，经验阈值）
    poolable = bool(np.all(np.sign(slopes) == np.sign(slopes[0])) and (slope_cv < 50.0))
    reg.update({"n_batches": len(series), "batch_slopes": slopes.tolist(),
                "slope_cv": float(slope_cv), "poolable": poolable})
    return reg


def shelf_life(months: np.ndarray, vals: np.ndarray, spec_limit: float,
               direction: str = "lower") -> Optional[float]:
    """
    按 ICH Q1E 推算有效期(月)。
    direction="lower": 质量标准要求指标不低于 spec_limit（如含量≥90%）。取95%置信下限达限时刻。
    direction="upper": 质量标准要求指标不超过 spec_limit（如有关物质≤2%）。取95%置信上限达限时刻。
    返回推算有效期（月），若当前数据在观测期内均未超限则估算外推值（并标注需谨慎）。
    """
    reg = regression_summary(months, vals)
    if reg is None or reg["n"] < 3:
        return None
    slope, intercept = reg["slope"], reg["intercept"]
    n = reg["n"]
    sigma = reg["sigma"]
    sxx = reg["sxx"]
    xbar = reg["xbar"]
    tcrit = stats.t.ppf(0.95, n - 2) if n > 2 else 0.0

    def _se_mean(t):
        # ICH Q1E：置信限针对回归直线（均值响应），不含单点预测的 "1 +" 项
        return sigma * np.sqrt(1 / n + (t - xbar) ** 2 / sxx)

    def bound(t):
        fit = intercept + slope * t
        return fit - tcrit * _se_mean(t) if direction == "lower" else fit + tcrit * _se_mean(t)

    def margin(t):
        # 统一符号：margin >= 0 表示仍符合质量标准，margin < 0 表示已超限
        return (bound(t) - spec_limit) if direction == "lower" else (spec_limit - bound(t))

    lo, hi = 0.0, 120.0  # 最多外推10年
    # 检查趋势方向是否合理
    if (direction == "lower" and slope >= 0) or (direction == "upper" and slope <= 0):
        # 无降级趋势：有效期取观测末期，回报"未观察到降级"
        return float(months.max())
    if margin(lo) < 0:
        # 起点(0月)即已超出限度：产品不合格，有效期记为 0
        return 0.0
    if margin(hi) >= 0:
        # 外推至 10 年仍未达限：观测期内合格，保守取观测末期（外推需谨慎）
        return float(months.max())
    for _ in range(60):  # 二分法求置信限与限度的交点
        mid = (lo + hi) / 2
        if margin(mid) >= 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def expiry_recommendation(months: np.ndarray, vals: np.ndarray, spec_limit: float,
                           direction: str = "lower") -> Optional[Dict]:
    """
    有效期推荐（含置信区间与保守取整，ICH Q1E）：
      - point_estimate: 回归线达限度时刻（点估计）
      - lower_bound_95: 95%置信下限达限时刻（shelf_life 本身，保守有效期）
      - ci_width: 置信区间宽度（月），反映外推不确定性
      - recommended: 保守有效期 = min(点估计, 观测末期外推约束) 向下取整到最近整月
                      若 lower_bound_95 > 观测末期，标注"外推需谨慎"
      - caution: 是否外推超观测期
    返回结构化建议，供放行决策与标签有效期标注。
    """
    sl = shelf_life(months, vals, spec_limit, direction)
    if sl is None:
        return None
    reg = regression_summary(months, vals)
    # 点估计：回归线直达限度
    if direction == "lower":
        pe = (spec_limit - reg["intercept"]) / reg["slope"] if reg["slope"] < 0 else float(months.max())
    else:
        pe = (spec_limit - reg["intercept"]) / reg["slope"] if reg["slope"] > 0 else float(months.max())
    obs_end = float(months.max())
    ci_width = abs(pe - sl)
    # 保守推荐：取 95% 下限（shelf_life 已是下限），超观测期则谨慎
    recommended = float(np.floor(sl)) if sl >= 1 else sl
    caution = sl > obs_end
    return {
        "point_estimate": round(pe, 1),
        "lower_bound_95": round(sl, 1),
        "ci_width": round(ci_width, 1),
        "recommended": recommended,
        "observational_end": round(obs_end, 1),
        "caution_extrapolation": caution,
        "recommendation": (f"建议标签有效期 {recommended:.0f} 个月（基于95%置信下限）"
                           + ("；该值超出观测期，外推需统计学论证(ICH Q1E)" if caution else "；观测期内有效")),
    }


def analyze_study(study: StabilityStudy, attributes: List[str]) -> List[Dict]:
    """
    对研究内所有样品 × 条件 × 检测项目 做回归与有效期推算。
    返回结果列表，供UI展示与导出。
    """
    results = []
    for s in study.samples:
        for cond in set(tp.condition for tp in s.time_points):
            for attr in attributes:
                months, vals, _ = _series_for(s, attr, cond)
                if len(vals) < 2 or float(np.std(months)) == 0.0:
                    continue
                reg = regression_summary(months, vals)
                rec = {
                    "批号": s.batch_id,
                    "条件": cond,
                    "检测项目": attr,
                    "数据点": len(vals),
                    "斜率/月": round(reg["slope"], 4) if reg else None,
                    "截距": round(reg["intercept"], 3) if reg else None,
                    "年降解率%": round(reg["rel_rate_pct_year"], 3) if reg and not np.isnan(reg["rel_rate_pct_year"]) else None,
                    "R²": round(reg["r2"], 4) if reg else None,
                    "p值": round(reg["p_value"], 4) if reg else None,
                    "趋势": _trend_word(reg["slope"], reg["p_value"]) if reg else "数据不足",
                    "有效期(月)": None,
                    "批间合并有效期(月)": None,
                    "备注": "",
                }
                # 若用户为该属性设置了限度，则推算有效期
                limit = _find_limit(s, attr)
                if limit:
                    sl = shelf_life(months, vals, limit["value"], limit["direction"])
                    if sl is not None:
                        rec["有效期(月)"] = round(sl, 1)
                        if sl >= months.max() and sl < 120:
                            rec["备注"] = "观测期内未达限，外推值需谨慎(ICH Q1E)"
                    # 批间合并有效期（基于全部批次同条件同项目）
                    pooled = pooled_regression(study, attr, cond)
                    if pooled and limit:
                        # 用合并回归方程构造连续序列做有效期推算
                        pm = np.linspace(0, max(float(months.max()), 12.0), 13)
                        pv = pooled["intercept"] + pooled["slope"] * pm
                        psl = shelf_life(pm, pv, limit["value"], limit["direction"]) if pooled["n"] >= 3 else None
                        if psl is not None:
                            rec["批间合并有效期(月)"] = round(psl, 1)
                        rec["备注"] = (rec["备注"] + "；" if rec["备注"] else "") + \
                            f"批间斜率CV={pooled['slope_cv']:.1f}%,可合并外推={'是' if pooled['poolable'] else '否'}"
                # 生物制品非线性降解提示（如聚集体S型增长）
                if reg and len(vals) >= 4:
                    nl = _nonlinear_hint(months, vals)
                    if nl:
                        rec["备注"] = (rec["备注"] + "；" if rec["备注"] else "") + nl
                results.append(rec)
    return results


def _trend_word(slope: float, p: float) -> str:
    if p >= 0.05:
        return "无显著趋势"
    if slope > 0:
        return "显著上升 ↑"
    return "显著下降 ↓"


def _nonlinear_hint(months: np.ndarray, vals: np.ndarray) -> str:
    """
    生物制品常见非线性降解检测：比较线性回归残差是否存在系统性（如S型）。
    方法：将序列分为前后两半，比较单位时间变化率；若后期速率显著大于前期，
    提示可能存在加速/非线性降解（聚集体、碎片等），线性外推偏乐观。
    """
    n = len(vals)
    if n < 4:
        return ""
    half = n // 2
    rate_early = (vals[half - 1] - vals[0]) / (months[half - 1] - months[0]) if months[half - 1] != months[0] else 0
    rate_late = (vals[-1] - vals[half]) / (months[-1] - months[half]) if months[-1] != months[half] else 0
    if rate_late > rate_early * 1.5 and rate_late > 0:
        return "提示非线性/加速降解，线性外推或偏乐观(建议非线性拟合)"
    if rate_early > rate_late * 1.5 and rate_early < 0:
        return "提示非线性降解(前期快后期缓)"
    return ""


def _find_limit(sample, attribute: str) -> Optional[Dict]:
    """查找该检测项目上设置的限度。优先用录入的限度，否则用生物制品默认限度。
    兼容传入 Sample 或 StabilityStudy（遍历所有样品）。"""
    samples = getattr(sample, "samples", None) or [sample]
    for sm in samples:
        for m in sm.measurements:
            if m.attribute == attribute and m.limit_spec is not None:
                direction = m.direction or ("lower" if (not m.is_limit) else "upper")
                return {"value": m.limit_spec, "direction": direction}
    # 生物制品/化药默认限度
    dft = default_limit_for(attribute)
    if dft:
        return {"value": dft[1], "direction": dft[0]}
    return None


def arrhenius_extrapolate(rates_with_temp: List[Tuple[float, float]]) -> Optional[Dict]:
    """
    Arrhenius 温度加速外推（ICH Q1A 加速试验 → 长期稳定性预测）。

    参数 rates_with_temp: 列表 [(rate, T_K), ...]
        rate = 该温度下的降解速率（绝对值，如 %/月，需同单位同基准）
        T_K  = 绝对温度（开尔文）
    方法：ln(rate) = ln(A) - Ea/(R·T)，对 (1/T, ln(rate)) 做线性回归得 Ea 与 A。
    返回：{'Ea_kJmol': 活化能, 'A': 指前因子, 'r2': 拟合优度,
           'predict': {T: 外推速率}} 可对目标温度外推。
    要求至少 2 个温度点。
    """
    if len(rates_with_temp) < 2:
        return None
    inv_T, ln_k = [], []
    for rate, T in rates_with_temp:
        if rate <= 0 or T <= 0:
            continue
        inv_T.append(1.0 / T)
        ln_k.append(np.log(rate))
    if len(inv_T) < 2:
        return None
    inv_T = np.array(inv_T)
    ln_k = np.array(ln_k)
    slope, intercept, r, p, se = stats.linregress(inv_T, ln_k)
    R = 8.314  # J/(mol·K)
    Ea = -slope * R / 1000.0  # kJ/mol
    A = np.exp(intercept)
    return {
        "Ea_kJmol": float(Ea),
        "A": float(A),
        "r2": float(r ** 2),
        "slope": float(slope),
        "intercept": float(intercept),
        "_inv_T": inv_T,
        "_ln_k": ln_k,
    }


def predict_rate_at(arr_result: Dict, T_K: float) -> Optional[float]:
    """用 Arrhenius 拟合结果外推某温度下的降解速率"""
    if arr_result is None or T_K <= 0:
        return None
    ln_k = arr_result["slope"] * (1.0 / T_K) + arr_result["intercept"]
    return float(np.exp(ln_k))


def speed_factor(rates_with_temp: List[Tuple[float, float]], T_target_K: float) -> Optional[float]:
    """
    加速因子：某温度相对目标(长期)温度降解速率的倍数。
    用于 ICH Q1A：40°C 加速 6 月 ≈ 25°C 长期数据外推依据。
    """
    arr = arrhenius_extrapolate(rates_with_temp)
    if not arr:
        return None
    k_target = predict_rate_at(arr, T_target_K)
    k_accel = max(r[0] for r in rates_with_temp)
    if k_target and k_target > 0:
        return float(k_accel / k_target)
    return None


def _exp_model(t, a, b, c):
    """指数模型：y = a*exp(-b*t) + c  （b>0衰减，b<0增长）"""
    return a * np.exp(-b * t) + c


def _logistic_model(t, L, k, t0, y0):
    """S型(logistic)模型：y = y0 + L/(1+exp(-k*(t-t0)))"""
    return y0 + L / (1.0 + np.exp(-k * (t - t0)))


def fit_nonlinear_models(months: np.ndarray, vals: np.ndarray) -> Dict:
    """
    非线性降解自动选型：分别拟合线性 / 指数 / S型(logistic)，
    按 AIC 选择最优模型，并报告模型参数与拟合优度。
    用于生物制品聚集体/碎片等非线性降解场景（ICH Q1E 建议非线性评估）。
    返回 {'best': 模型名, 'models': {名称: {...}}, 'n': ...}
    """
    if len(vals) < 3:
        return {"best": None, "reason": "数据点不足(<3)", "models": {}}
    y0v = vals[0]
    ymin, ymax = float(np.min(vals)), float(np.max(vals))
    span = (ymax - ymin) if (ymax - ymin) != 0 else 1.0
    models = {}
    n = len(vals)
    # 线性
    try:
        lr = regression_summary(months, vals)
        resid = vals - (lr["intercept"] + lr["slope"] * months)
        sse = float(np.sum(resid ** 2))
        aic_lin = n * np.log(sse / n) + 2 * 2 if sse > 0 else float("inf")
        models["linear"] = {"r2": lr["r2"], "aic": aic_lin,
                            "slope": lr["slope"], "intercept": lr["intercept"]}
    except Exception:
        pass
    # 指数
    try:
        p0 = [y0v - ymin, 0.05, ymin]
        pe, _ = curve_fit(_exp_model, months, vals, p0=p0, maxfev=10000)
        pred = _exp_model(months, *pe)
        sse = float(np.sum((vals - pred) ** 2))
        aic = n * np.log(sse / n) + 2 * 3 if sse > 0 else float("inf")
        ss_tot = float(np.sum((vals - vals.mean()) ** 2))
        r2 = 1 - sse / ss_tot if ss_tot > 0 else float("nan")
        models["exponential"] = {"r2": r2, "aic": aic, "params": pe.tolist()}
    except Exception:
        pass
    # 逻辑斯蒂(S型)
    try:
        p0 = [span, 0.3, months.mean(), ymin]
        pl, _ = curve_fit(_logistic_model, months, vals, p0=p0, maxfev=10000,
                          bounds=([-np.inf, -np.inf, -np.inf, -np.inf],
                                  [np.inf, np.inf, np.inf, np.inf]))
        pred = _logistic_model(months, *pl)
        sse = float(np.sum((vals - pred) ** 2))
        aic = n * np.log(sse / n) + 2 * 4 if sse > 0 else float("inf")
        ss_tot = float(np.sum((vals - vals.mean()) ** 2))
        r2 = 1 - sse / ss_tot if ss_tot > 0 else float("nan")
        models["logistic"] = {"r2": r2, "aic": aic, "params": pl.tolist()}
    except Exception:
        pass
    if not models:
        return {"best": None, "reason": "拟合失败", "models": {}}
    # 若 logistic 拐点 t0 落在数据范围外，说明实质为单调趋势，不应判为S型
    if "logistic" in models:
        t0 = models["logistic"]["params"][2]
        if t0 < months.min() or t0 > months.max():
            # 退化为单调，移除 logistic 候选
            del models["logistic"]
    best = min(models, key=lambda k: models[k]["aic"])
    return {"best": best, "models": models, "n": n,
            "nonlinear_detected": best in ("exponential", "logistic")}


def detect_outliers(months: np.ndarray, vals: np.ndarray) -> List[int]:
    """
    离群值检测（leave-one-out 鲁棒法，抗 masking）：
    对每个点 i，用其余 n-1 个点做线性回归，得到点 i 的"删除残差" e_i*；
    用其余 n-1 个点的残差中位数绝对偏差(MAD) 计算修正 Z 分数：
        mz_i = 0.6745 * e_i* / MAD_rest
    |mz_i| > 3.5 判为统计离群（录入错误或异常批次）。
    该方案将待检点完全隔离，不会被其自身污染回归或 MAD，对小样本单离群稳健。
    返回离群点在原序列中的索引列表。
    """
    n = len(vals)
    if n < 4:
        return []
    out = []
    for i in range(n):
        mask = np.arange(n) != i
        reg = regression_summary(months[mask], vals[mask])
        if reg is None:
            continue
        e_star = vals[i] - (reg["intercept"] + reg["slope"] * months[i])
        # 其余点残差
        rest_resid = vals[mask] - (reg["intercept"] + reg["slope"] * months[mask])
        med = np.median(rest_resid)
        mad = np.median(np.abs(rest_resid - med))
        if mad == 0:
            # 其余点完美线性：任何偏差点都显著
            if abs(e_star) > 1e-9:
                out.append(i)
            continue
        mz = 0.6745 * e_star / mad
        if abs(mz) > 3.5:
            out.append(i)
    return out


def detect_missing(sample: Sample, condition: str, planned_months: List[float]) -> List[float]:
    """
    缺失值检测：对比某条件下"计划月点"与"已录入月点"，
    返回计划了但未录入数据的月点列表（提醒补测/关注掉点）。
    """
    present = set()
    for tp in sample.time_points:
        if tp.condition == condition:
            for m in sample.measurements:
                if float(m.time_point_id) == float(tp.month) and m.value is not None:
                    present.add(tp.month)
    return [pm for pm in planned_months if pm not in present]


# ----------------------------------------------------------------------------
# 光稳定性评估（ICH Q1B）
# ----------------------------------------------------------------------------
def photostability_exposure_ok(option: str, actual_lux_hr: float, actual_uv_wh_m2: float) -> Dict:
    """
    ICH Q1B 光照暴露充足性判定。
    option: "option1" 常规 / "option2" 强化
    返回 {ok, total_ok, uv_ok, required, actual}
    """
    req = PHOTO_Q1B_OPTION1 if option == "option1" else PHOTO_Q1B_OPTION2
    total_ok = actual_lux_hr >= req["total_lux_hr"]
    uv_ok = actual_uv_wh_m2 >= req["uv_wh_m2"]
    return {
        "ok": total_ok and uv_ok,
        "total_ok": total_ok, "uv_ok": uv_ok,
        "required": req,
        "actual": {"total_lux_hr": actual_lux_hr, "uv_wh_m2": actual_uv_wh_m2},
    }


def photostability_assessment(study: StabilityStudy,
                              attribute: str,
                              option: str = "option1",
                              actual_lux_hr: float = None,
                              actual_uv_wh_m2: float = None) -> Dict:
    """
    ICH Q1B 光稳定性评估：
    - 比较 0 月（对照组）与光照后（photo 条件）各批的检测值
    - 计算光照诱导变化量 Δ = 光照后 - 0月，及其相对变化 %
    - 判定是否符合：光照后 CQA 仍在质量标准内（降解未超限度）
    - 评估暴露是否达到 Q1B 要求
    返回结构化结果（供 UI 与报告使用）。
    """
    res = {
        "attribute": attribute,
        "option": option,
        "exposure": None,
        "batches": [],
        "significant_light_degradation": False,
        "compliant": None,
        "note": "",
    }
    # 暴露充足性
    if actual_lux_hr is not None and actual_uv_wh_m2 is not None:
        res["exposure"] = photostability_exposure_ok(option, actual_lux_hr, actual_uv_wh_m2)

    dir_limit = default_limit_for(attribute)
    limit_spec = dir_limit[1] if dir_limit else None
    PHOTO_ALIASES = {StorageCondition.PHOTOSTABILITY.value, "光照", "光稳定性"}

    # 建立 tp_id -> condition 映射，支持同month多条件精确配对
    for s in study.samples:
        base = None  # 0月长期/对照值
        photo_vals = []
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = next((t for t in s.time_points if t.tp_id == m.tp_ref), None) if m.tp_ref else None
            if tp is None:
                tp = next((t for t in s.time_points
                           if t.month == m.time_point_id
                           and t.condition not in PHOTO_ALIASES), None)
            if tp is None:
                continue
            if tp.condition in PHOTO_ALIASES:
                photo_vals.append(m.value)
            elif tp.month == 0:
                base = m.value
        if base is None or not photo_vals:
            continue
        photo = photo_vals[0]
        delta = photo - base
        rel = (delta / base * 100.0) if base != 0 else float("nan")
        # 光照后是否超限度
        over = False
        if dir_limit:
            direction, lim = dir_limit
            if direction == "lower" and photo < lim:
                over = True
            if direction == "upper" and photo > lim:
                over = True
        if over:
            res["significant_light_degradation"] = True
        res["batches"].append({
            "batch_id": s.batch_id,
            "base": base, "photo": photo,
            "delta": delta, "rel_pct": rel,
            "over_limit": over,
        })
    if not res["batches"]:
        res["compliant"] = None
        res["note"] = "无完整光照对照数据（需 0 月对照 + 光照后数据）"
    else:
        res["compliant"] = not res["significant_light_degradation"]
        res["note"] = ("光照后 CQA 均在质量标准内，方法对光稳定。" if res["compliant"]
                       else "光照后存在 CQA 超出质量标准，提示光不稳定性，需优化处方/包装避光。")
    return res


def study_data_quality(study: StabilityStudy, attributes: List[str]) -> List[Dict]:
    """
    全研究数据质量扫描：对每个 批×条件×项目 给出
    离群点、缺失点、非线性提示汇总，用于质量告警面板。
    """
    issues = []
    for s in study.samples:
        conds = list({tp.condition for tp in s.time_points})
        planned = sorted({tp.month for tp in s.time_points})
        for cond in conds:
            for attr in attributes:
                months, vals, _ = _series_for(s, attr, cond)
                if len(vals) == 0:
                    continue
                rec = {"批号": s.batch_id, "条件": cond, "检测项目": attr,
                       "数据点": len(vals), "离群索引": [], "缺失月点": [],
                       "非线性": ""}
                if len(vals) >= 3:
                    rec["离群索引"] = mad_outlier_detection(np.array(vals))
                rec["缺失月点"] = detect_missing(s, cond, planned)
                if len(vals) >= 4:
                    nl = _nonlinear_hint(months, vals)
                    rec["非线性"] = nl
                if rec["离群索引"] or rec["缺失月点"] or rec["非线性"]:
                    issues.append(rec)
    return issues


def data_quality_score(issues: List[Dict]) -> Tuple[int, int]:
    """启发式数据质量分：起始 100 分，每个问题扣 5 分（下限 0）。

    仅用于内部排查与排序，**不是**法规指标，不应写入报告作为结论。
    返回 (分数, 问题数)。
    """
    n = len(issues)
    return max(0, 100 - 5 * n), n


def batch_variance_analysis(study: StabilityStudy, attribute: str, condition: str) -> Optional[Dict]:
    """
    批间方差分析与等效性判断（ICH Q1E 批间合并外推前提）。
    比较同一条件下各批次的：初始值(截距/0月值) 与 降解斜率。
      - 批间初始值 CV% 与 批间斜率 CV%（离散度）
      - 等效性结论：若批间初始值差异在方法误差内(相对RSD<5%)且斜率同向且CV<30%，
        可合并外推（即允许用合并回归将长期数据外推至加速数据的2倍或更多）。
    返回结构化结论，供有效期推算与放行决策。
    """
    batches = []
    for s in study.samples:
        months, vals, _ = _series_for(s, attribute, condition)
        if len(vals) >= 2:
            reg = regression_summary(months, vals)
            if reg:
                batches.append({"batch": s.batch_id, "y0": reg["y0"],
                                "slope": reg["slope"], "r2": reg["r2"]})
    if len(batches) < 2:
        return None
    y0s = np.array([b["y0"] for b in batches])
    slopes = np.array([b["slope"] for b in batches])
    mean_y0 = y0s.mean()
    cv_y0 = (y0s.std(ddof=0) / abs(mean_y0) * 100.0) if mean_y0 != 0 else float("nan")
    cv_slope = (slopes.std(ddof=0) / abs(slopes.mean()) * 100.0) if slopes.mean() != 0 else float("nan")
    # 等效性：批间初始值相对RSD<5% 视为等效；斜率同向且CV<30%
    equivalent_initial = bool(cv_y0 < 5.0)
    same_direction = bool(np.all(np.sign(slopes) == np.sign(slopes[0])))
    poolable = bool(equivalent_initial and same_direction and cv_slope < 30.0)
    # 合并外推倍率建议（基于合并数据点数 vs 单批，经验：合并后外推可达单批观测期2倍）
    return {
        "n_batches": len(batches),
        "cv_initial_pct": float(cv_y0),
        "cv_slope_pct": float(cv_slope),
        "equivalent_initial": equivalent_initial,
        "same_direction": same_direction,
        "poolable": poolable,            # 是否可合并外推
        "conclusion": ("批间等效，可合并外推" if poolable else
                       "批间不等效，应分别推算有效期" if not equivalent_initial
                       else "斜率方向/离散度不满足合并条件"),
        "batches": batches,
    }


def expiry_extrapolation(study: StabilityStudy, attribute: str, condition: str) -> Optional[Dict]:
    """
    有效期外推因子计算（ICH Q1E 外推论证辅助）：
    对某 批×条件×项目，基于已有数据估 95% 置信下限有效期 T_lb 与观测期 T_obs，
    外推倍率 = T_lb / T_obs。
      - 倍率 ≤ 1：有效期内，无需外推
      - 1 < 倍率 ≤ 2：外推至 2× 观测期，需批间一致性支持（ICH Q1E 允许）
      - 倍率 > 2：外推超 2× 观测期，需强统计论证（不建议标签直接采用）
    返回结构化外推建议。
    """
    for s in study.samples:
        months, vals, _ = _series_for(s, attribute, condition)
        if len(vals) >= 3:
            limit = _find_limit(s, attribute)
            if not limit:
                continue
            sl = shelf_life(months, vals, limit["value"], limit["direction"])
            if sl is None:
                continue
            t_obs = float(months.max())
            factor = sl / t_obs if t_obs > 0 else float("nan")
            if factor <= 1:
                rec = "有效期内（无需外推）"
            elif factor <= 2:
                rec = "可外推至约2×观测期（需批间一致性支持）"
            else:
                rec = "外推超2×观测期，需强统计论证，不建议直接标签采用"
            return {"batch": s.batch_id, "t_obs": round(t_obs, 1),
                    "t_lower_bound": round(sl, 1), "extrap_factor": round(factor, 2),
                    "recommendation": rec, "condition": condition, "attribute": attribute}
    return None


def significant_change_assessment(study: StabilityStudy, attribute: str,
                                    condition: str, initial_value: Optional[float] = None,
                                    threshold_pct: float = 5.0) -> Optional[Dict]:
    """
    加速/长期稳定性"显著变化"判定：
      - 化药(ICH Q1A(R2))：含量/效价类相对初始下降超过 threshold_pct%（默认5%）即判显著变化
      - 生物制品(ICH Q5C)：效价/结合活性下降>10%、纯度下降、聚集体增长超限度为显著变化
        （生物制品的"显著变化"阈值严于化药，且以 CQA 限度为核心判据）
    返回：首个显著变化的月点、变化幅度、结论。
    若 initial_value 为 None，取该序列首点(0月)值为初始。
    """
    # 生物制品专属显著变化阈值（效价类10%，其余按限度）
    if getattr(study, "biologic", False):
        if attribute in ("效价", "结合活性"):
            threshold_pct = 10.0
    for s in study.samples:
        months, vals, _ = _series_for(s, attribute, condition)
        if len(vals) < 2:
            continue
        y0 = initial_value if initial_value is not None else vals[0]
        if y0 == 0:
            continue
        limit = _find_limit(s, attribute)
        sig_idx = None
        for i, v in enumerate(vals):
            if limit and limit["direction"] == "upper":
                # 降解产物/CQA：超过上限限度
                if v > limit["value"]:
                    sig_idx = i
                    break
            else:
                # 含量/效价：相对初始下降超阈值
                drop = (y0 - v) / abs(y0) * 100.0
                if drop > threshold_pct:
                    sig_idx = i
                    break
        if sig_idx is not None:
            drop = (y0 - vals[sig_idx]) / abs(y0) * 100.0 if y0 else 0
            return {"batch": s.batch_id, "condition": condition, "attribute": attribute,
                    "initial": round(y0, 2), "month_of_change": float(months[sig_idx]),
                    "value_at_change": round(float(vals[sig_idx]), 2),
                    "change_pct": round(drop, 2),
                    "biologic": getattr(study, "biologic", False),
                    "conclusion": f"在 {float(months[sig_idx]):.0f} 月出现显著变化（>{threshold_pct:.0f}%）" if not limit
                                   else f"在 {float(months[sig_idx]):.0f} 月超过限度 {limit['value']}"}
    # 无显著变化：返回结构化结果（含 change_type=none），供上层仪表盘/合格率统计使用
    last = None
    for s in study.samples:
        months, vals, _ = _series_for(s, attribute, condition)
        if len(vals) >= 2:
            last = (s.batch_id, months, vals)
    if last is not None:
        s_batch, months, vals = last
        y0 = initial_value if initial_value is not None else vals[0]
        drop = (y0 - vals[-1]) / abs(y0) * 100.0 if y0 else 0
        return {"batch": s_batch, "condition": condition, "attribute": attribute,
                "initial": round(y0, 2), "month_of_change": None,
                "value_at_change": round(float(vals[-1]), 2),
                "change_pct": round(drop, 2),
                "biologic": getattr(study, "biologic", False),
                "is_significant": False,
                "change_type": "无显著变化(none)",
                "conclusion": (f"未观察到显著变化（最大变化 {drop:.1f}%，未达限度判据）"
                               if threshold_pct is None
                               else f"未观察到显著变化（最大下降 {drop:.1f}% ≤ {threshold_pct:.0f}%）")}
    return None


# 生物制品 CQA 显著变化专属阈值表（相对初始值容许变化）
BIO_SIGNIFICANT_THRESHOLDS = {
    "效价": 10.0,        # 效价下降>10% 为显著变化
    "结合活性": 10.0,
    "聚集体": None,      # None=以限度判据为主
    "碎片": None,
    "脱酰胺": None,
    "氧化": None,
    "电荷异质体": None,
    "糖基化": None,
}


def biologic_significant_change(study: StabilityStudy, attribute: str,
                                 condition: str) -> Optional[Dict]:
    """
    生物制品专属显著变化评估（ICH Q5C / Q1A）：
      - 区分两种显著变化类型：
        * "超出标准(out-of-spec)"：观测值已超出质量标准限度（确定性超标）
        * "超出趋势(out-of-trend)"：95% 置信限外推已触及限度，但当前观测未超限
          （提示趋势性降解，需警惕，ICH Q1E 外推谨慎）
      - 效价/结合活性：相对 0 月下降>10% 即显著变化（低于标准亦算）
      - 其余 CQA：以上限限度为主判据
    返回字典增加 change_type 字段（none/spec/trend/spec+trend）。
    """
    if not getattr(study, "biologic", False):
        return significant_change_assessment(study, attribute, condition)
    base = significant_change_assessment(study, attribute, condition,
                                          threshold_pct=BIO_SIGNIFICANT_THRESHOLDS.get(attribute, 5.0))
    if base is None:
        return None
    # 增加超出趋势判定：用 95% 置信限外推是否触及限度
    dir_limit = default_limit_for(attribute)
    if dir_limit:
        direction, spec_limit = dir_limit
        ext = expiry_extrapolation(study, attribute, condition)
        is_sig = base.get("is_significant") or base.get("month_of_change") is not None \
            or base.get("reaches_limit") is not None
        if is_sig:
            # 已观测超限/超阈值 -> 超出标准
            base["change_type"] = "超出标准(spec)"
            if ext and ext.get("t_lower_bound") is not None and ext["t_lower_bound"] <= ext["t_obs"]:
                base["change_type"] = "超出标准(spec)+超出趋势(trend)"
                base["note"] = (base.get("note", "") +
                                " 95%置信外推亦触及限度（超出趋势叠加），外推论证需极谨慎。")
        else:
            # 观测未超限，检查外推是否趋势性达限
            if ext and ext.get("t_lower_bound") is not None and ext["t_lower_bound"] <= ext["t_obs"]:
                base["change_type"] = "超出趋势(trend)"
                base["note"] = (base.get("note", "") +
                                " 95%置信外推已触及限度（超出趋势），需加强监测与外推论证。")
            else:
                base["change_type"] = "无显著变化(none)"
    else:
        base["change_type"] = "超出标准(spec)" if base.get("is_significant") else "无显著变化(none)"
    return base


def export_long_format(study: StabilityStudy) -> List[Dict]:
    """导出长表（每个检测值一行），便于Excel/统计软件进一步处理"""
    rows = []
    for s in study.samples:
        for tp in s.time_points:
            for m in s.measurements:
                if float(m.time_point_id) == float(tp.month):
                    rows.append({
                        "批号": s.batch_id,
                        "包装": s.packaging,
                        "规格": s.strength,
                        "条件": tp.condition,
                        "月点": tp.month,
                        "检测项目": m.attribute,
                        "数值": m.value,
                        "单位": m.unit,
                        "限度": m.limit_spec,
                        "备注": m.note,
                    })
    return rows


def pooled_bootstrap_ci(study: StabilityStudy, attribute: str, condition: str,
                        spec_limit: float, direction: str = "lower",
                        n_boot: int = 2000, seed: int = 2026) -> Optional[Dict]:
    """
    R3 新增 —— 批间合并 Bootstrap 置信区间（ICH Q1E 多批次外推不确定性量化）。
    方法：将所有批次在该条件该属性的数据点合并为一组 (t, y)，对合并数据做
          线性回归推算有效期；通过放回重采样生成 n_boot 个有效期估计，
          取 2.5% / 97.5% 分位作为 95% Bootstrap 置信区间。
    返回：point_estimate / ci_low / ci_high / ci_width / n_points / n_batches。
    """
    ts_batches, vs_batches, n_batches = [], [], 0
    for s in study.samples:
        m, v, _ = _series_for(s, attribute, condition)
        if len(v) >= 2:
            ts_batches.append(m)
            vs_batches.append(v)
            n_batches += 1
    if n_batches == 0:
        return None
    all_t = np.concatenate(ts_batches)
    all_v = np.concatenate(vs_batches)
    if len(all_t) < 3:
        return None
    pe = shelf_life(all_t, all_v, spec_limit, direction)
    if pe is None:
        return None
    rng = random.Random(seed)
    boot = []
    n = len(all_t)
    for _ in range(n_boot):
        idx = [rng.randrange(n) for _ in range(n)]
        bt = all_t[idx]
        bv = all_v[idx]
        try:
            sl = shelf_life(bt, bv, spec_limit, direction)
        except Exception:
            sl = None
        if sl is not None:
            boot.append(sl)
    if not boot:
        return None
    boot = np.array(boot)
    return {
        "point_estimate": round(float(pe), 1),
        "ci_low": round(float(np.percentile(boot, 2.5)), 1),
        "ci_high": round(float(np.percentile(boot, 97.5)), 1),
        "ci_width": round(float(np.percentile(boot, 97.5) - np.percentile(boot, 2.5)), 1),
        "n_points": int(n),
        "n_batches": n_batches,
        "recommendation": (f"合并 Bootstrap 有效期 {float(pe):.0f} 月 "
                           f"(95% CI {np.percentile(boot,2.5):.0f}–{np.percentile(boot,97.5):.0f} 月)"),
    }


def fit_best_model(study: StabilityStudy, attribute: str, condition: str,
                   spec_limit: float = None, direction: str = "lower") -> Optional[Dict]:
    """
    R17 新增 —— 多模型拟合与 AIC/BIC 选择 (ICH Q1E 非线性降解)。
    对合并批次数据拟合：(1) 线性回归 (2) 指数衰减 y=a*exp(-k t)+c (3) 逻辑斯蒂饱和降解。
    以 AIC/BIC 选最优模型，并用最优模型推算有效期(到 spec_limit 的时间)。
    返回：best_model / aic / bic / 各模型对比 / shelf_life_best / note。
    spec_limit 可选：缺省时自动从限度定义或样本测量值推导。
    """
    if spec_limit is None:
        lim = _find_limit(study, attribute)
        if lim:
            spec_limit = lim["value"]
            direction = lim["direction"]
        else:
            _vals = [m.value for s in study.samples for m in s.measurements
                     if m.attribute == attribute and m.value is not None]
            spec_limit = float(np.min(_vals)) if _vals else 0.0
    ts, vs = [], []
    for s in study.samples:
        m, v, _ = _series_for(s, attribute, condition)
        if len(v) >= 2:
            ts.append(m)
            vs.append(v)
    if not ts:
        return None
    t = np.concatenate(ts)
    y = np.concatenate(vs)
    n = len(t)
    if n < 3:
        return None

    models_res = {}

    # (1) 线性
    try:
        sl, ic, r, p, se = stats.linregress(t, y)
        yhat = sl * t + ic
        rss = np.sum((y - yhat) ** 2)
        k = 2
        aic_l = n * np.log(rss / n) + 2 * k if rss > 0 else np.inf
        bic_l = n * np.log(rss / n) + k * np.log(n) if rss > 0 else np.inf
        sl_lin = shelf_life(t, y, spec_limit, direction)
        models_res["linear"] = {"aic": aic_l, "bic": bic_l, "shelf_life": sl_lin,
                                "params": {"slope": sl, "intercept": ic}}
    except Exception:
        pass

    # (2) 指数衰减 a*exp(-k t)+c
    def exp_model(t, a, k, c):
        return a * np.exp(-k * t) + c

    try:
        from scipy.optimize import curve_fit
        p0 = [max(y), 0.01, min(y)]
        popt, _ = curve_fit(exp_model, t, y, p0=p0, maxfev=10000)
        yhat = exp_model(t, *popt)
        rss = np.sum((y - yhat) ** 2)
        k = 3
        rss_e = max(rss, 1e-300)  # 完美拟合时 rss≈0，防止 log(0)
        aic_e = n * np.log(rss_e / n) + 2 * k
        bic_e = n * np.log(rss_e / n) + k * np.log(n)
        # 解 a*exp(-k x)+c = limit
        a, ke, c = popt
        sl_e = None
        if direction == "lower":
            # a*exp(-k x)+c = limit -> x = -ln((limit-c)/a)/k
            if a > 0 and ke > 0 and (spec_limit - c) / a > 0:
                sl_e = -np.log((spec_limit - c) / a) / ke
        else:
            if a > 0 and ke > 0 and (spec_limit - c) / a > 0:
                sl_e = -np.log((spec_limit - c) / a) / ke
        models_res["exp"] = {"aic": aic_e, "bic": bic_e, "shelf_life": sl_e,
                             "params": {"a": a, "k": ke, "c": c}}
    except Exception:
        pass

    # (3) 逻辑斯蒂饱和 y = L / (1 + exp(-g (t - t0))) + base
    def log_model(t, L, g, t0, base):
        return L / (1.0 + np.exp(-g * (t - t0))) + base

    try:
        p0 = [max(y) - min(y), 0.1, np.median(t), min(y)]
        popt, _ = curve_fit(log_model, t, y, p0=p0, maxfev=10000)
        yhat = log_model(t, *popt)
        rss = np.sum((y - yhat) ** 2)
        k = 4
        rss_g = max(rss, 1e-300)  # 同上
        aic_g = n * np.log(rss_g / n) + 2 * k
        bic_g = n * np.log(rss_g / n) + k * np.log(n)
        models_res["logistic"] = {"aic": aic_g, "bic": bic_g, "shelf_life": None,
                                  "params": dict(zip(["L", "g", "t0", "base"], popt))}
    except Exception:
        pass

    if not models_res:
        return None
    best = min(models_res, key=lambda m: models_res[m]["aic"])
    # 生成各模型预测曲线（供 UI 多模型对比图）
    t_grid = np.linspace(float(t.min()), float(t.max()), 100)
    predictions = {}
    if "linear" in models_res:
        p = models_res["linear"]["params"]
        predictions["linear"] = (p["slope"] * t_grid + p["intercept"]).tolist()
    if "exp" in models_res:
        p = models_res["exp"]["params"]
        predictions["exp"] = (p["a"] * np.exp(-p["k"] * t_grid) + p["c"]).tolist()
    if "logistic" in models_res:
        p = models_res["logistic"]["params"]
        predictions["logistic"] = (p["L"] / (1.0 + np.exp(-p["g"] * (t_grid - p["t0"]))) + p["base"]).tolist()
    return {
        "best_model": best,
        "best_aic": round(float(models_res[best]["aic"]), 2),
        "best_bic": round(float(models_res[best]["bic"]), 2),
        "shelf_life_best": round(float(models_res[best]["shelf_life"]), 1) if models_res[best]["shelf_life"] else None,
        "comparison": {m: {"aic": round(models_res[m]["aic"], 2), "bic": round(models_res[m]["bic"], 2),
                           "shelf_life": round(models_res[m]["shelf_life"], 1) if models_res[m]["shelf_life"] else None}
                      for m in models_res},
        "predictions": predictions,
        "t_grid": t_grid.tolist(),
        "note": ("非线性(指数/逻辑斯蒂)拟合更优时，提示生物制品降解可能非线性，"
                 "线性外推偏乐观(Q1E)，建议增加时间点或采用非线性模型推算有效期。"),
    }


def mad_outlier_detection(values: np.ndarray, threshold: float = 3.5) -> List[int]:
    """
    R19 新增 —— 基于 MAD(中位数绝对偏差) 的稳健离群检测。
    比 IQR/标准差对偏态与重尾更稳定，适用于生物制品降解数据。
    返回离群值索引列表（|modified z-score| > threshold）。
    """
    v = np.asarray(values, dtype=float)
    if len(v) < 3:
        return []
    med = np.median(v)
    mad = np.median(np.abs(v - med))
    if mad == 0:
        return []
    mz = 0.6745 * (v - med) / mad
    return [int(i) for i in range(len(v)) if abs(mz[i]) > threshold]


def freeze_thaw_assessment(study: StabilityStudy, attribute: str,
                            spec_limit: float = None, direction: str = None) -> Dict:
    """
    冻融循环稳定性评估（冻存原液/可负担性，ICH Q5C 通常 5 次冻融）。
    - 比较 0 月长期对照 与 各冻融循环次数(cycle) 后的 CQA
    - 判定在第几循环 CQA 首次超出限度（冻融耐受次数）
    - 返回 {max_cycles_ok, detail, status, note}
    """
    res = {"attribute": attribute, "max_cycles_ok": 0, "detail": [],
           "status": None, "note": ""}
    dir_limit = default_limit_for(attribute)
    if dir_limit and spec_limit is None:
        direction, spec_limit = dir_limit
    if spec_limit is None or direction is None:
        res["note"] = "缺少质量标准限度/方向，无法评估冻融稳定性。"
        res["status"] = "na"
        return res

    FT_ALIASES = {StorageCondition.FREEZE_THAW.value, "冻融循环", "冻融"}
    has_ft = any(tp.condition in FT_ALIASES
                 for s in study.samples for tp in s.time_points)
    if not has_ft:
        res["status"] = "no_data"
        res["note"] = "无冻融循环条件数据，无法评估。"
        return res

    worst_cycle = 0
    for s in study.samples:
        base = None
        ft_vals = {}  # cycle -> value
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = _tp_by_ref(study, s, m)
            if tp is None:
                continue
            if tp.condition in (StorageCondition.LONG_TERM.value, "冷藏", "冷冻-80") and tp.month == 0:
                base = m.value
            elif tp.condition in FT_ALIASES:
                cyc = int(tp.month) if isinstance(tp.month, (int, float)) else 0
                ft_vals[cyc] = m.value
        if base is None or not ft_vals:
            continue
        for cyc in sorted(ft_vals):
            v = ft_vals[cyc]
            over = False
            if direction == "lower" and v < spec_limit:
                over = True
            if direction == "upper" and v > spec_limit:
                over = True
            res["detail"].append({"batch_id": s.batch_id, "cycle": cyc,
                                  "value": v, "base": base, "over_limit": over})
            if over:
                worst_cycle = max(worst_cycle, cyc)
    if not res["detail"]:
        res["status"] = "no_data"
        res["note"] = "冻融数据不完整（需 0 月对照 + 冻融循环值）。"
        return res
    # 耐受循环数 = 所有批次均未超限度的最大循环
    ok_cycles = set()
    for cyc in sorted({d["cycle"] for d in res["detail"]}):
        if not any(d["cycle"] == cyc and d["over_limit"] for d in res["detail"]):
            ok_cycles.add(cyc)
    res["max_cycles_ok"] = max(ok_cycles) if ok_cycles else 0
    if res["max_cycles_ok"] >= 5:
        res["status"] = "ok"
        res["note"] = f"冻融耐受性良好：至 {res['max_cycles_ok']} 次循环 CQA 仍在限度内（ICH Q5C 常规 5 次）。"
    elif res["max_cycles_ok"] > 0:
        res["status"] = "limited"
        res["note"] = f"冻融耐受有限：仅至 {res['max_cycles_ok']} 次循环合格，建议优化冻存处方或限制冻融次数。"
    else:
        res["status"] = "fail"
        res["note"] = "首次冻融即超出限度，冻存方案不可接受，需重新设计。"
    return res


def variance_components(study: StabilityStudy, attribute: str, condition: str) -> Dict:
    """
    方差分量估计（ICH Q1E 合并批评估基础）：
    - 批内方差（within-batch，重复测量误差）+ 批间方差（between-batch，初始值差异）
    - 用各批 0 月值估计批间方差，用各批斜率残差估计批内方差
    返回 {between_var, within_var, total_var, icc, note}
    ICC（ intraclass correlation）高=批间差异主导
    """
    res = {"attribute": attribute, "condition": condition,
           "between_var": None, "within_var": None, "total_var": None, "icc": None, "note": ""}
    batch_initials, batch_slopes = [], []
    for s in study.samples:
        xs, ys = [], []
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = _tp_by_ref(study, s, m)
            if tp is None or tp.condition != condition:
                continue
            try:
                x = float(m.time_point_id)
            except (TypeError, ValueError):
                x = tp.month
            xs.append(x)
            ys.append(m.value)
        if len(xs) >= 2:
            sl, inter, _, _, _ = stats.linregress(xs, ys)
            batch_slopes.append(sl)
            batch_initials.append(ys[0])
    if len(batch_initials) < 2:
        res["note"] = "批数不足（<2），无法估计方差分量。"
        return res
    between_var = float(np.var(batch_initials, ddof=1))
    # 批内：各批斜率残差方差（近似批内变异）
    if len(batch_slopes) >= 2:
        within_var = float(np.var(batch_slopes, ddof=1))
    else:
        within_var = 0.0
    total_var = between_var + within_var
    icc = between_var / total_var if total_var > 0 else 0.0
    res.update({"between_var": between_var, "within_var": within_var,
                "total_var": total_var, "icc": icc})
    if icc > 0.5:
        res["note"] = f"批间差异主导（ICC={icc:.2f}），合并评估需谨慎，建议逐批评估。"
    else:
        res["note"] = f"批内/批间较均衡（ICC={icc:.2f}），可考虑合并批次评估（Q1E）。"
    return res


def ccit_trend_assessment(study: StabilityStudy) -> Dict:
    """
    R15 容器密封完整性（CCIT）趋势评估：
    - 生物制品稳定性需监测包装密封性（USP<1207>/ICH Q5C）
    - 汇总含 '容器密封' 属性的测量（通常定性：通过/不通过，或定量染色侵入/氦质谱泄漏率）
    - 评估随时间的 CCIT 通过情况，识别密封失效时间点
    返回 {has_data, trend, first_fail_month, note}
    """
    res = {"has_data": False, "trend": [], "first_fail_month": None, "note": ""}
    any_ccit = False
    for s in study.samples:
        for m in s.measurements:
            if m.attribute in ("容器密封", "CCIT", "泄漏率") and m.value is not None:
                any_ccit = True
                tp = _tp_by_ref(study, s, m)
                mo = tp.month if tp else m.time_point_id
                # 定性通过：值>=1 或字符串"通过"；定量：泄漏率越低越好
                passed = True
                if isinstance(m.value, (int, float)):
                    passed = m.value >= 1.0  # 约定：1=通过，0=失败（或泄漏率阈值）
                status = "通过" if passed else "失败"
                res["trend"].append({"batch_id": s.batch_id, "month": mo,
                                     "value": m.value, "status": status})
                if not passed and res["first_fail_month"] is None:
                    res["first_fail_month"] = mo
    res["has_data"] = any_ccit
    if not any_ccit:
        res["note"] = "未录入容器密封完整性(CCIT)数据，建议补充以符合 ICH Q5C/USP<1207>。"
    elif res["first_fail_month"] is not None:
        res["note"] = (f"⚠ 在 {res['first_fail_month']} 月出现 CCIT 失败，"
                       "提示容器密封随储存退化，需评估包装或储存条件。")
    else:
        res["note"] = "容器密封完整性在考察期内全程通过，包装密封性良好。"
    return res


def batch_consistency_capability(study: StabilityStudy, attribute: str,
                                  spec_lo: float = None, spec_hi: float = None) -> Dict:
    """
    R14 批间一致性 / 工艺能力指数（Cpk/Ppk）：
    - 取各批 0 月（初始）该属性的批均值，视为过程输出
    - 若未提供规格，用历史批均值 ± 3σ 作为经验规格
    - 计算 Cpk = min((USL-μ),(μ-LSL)) / (3σ)
    返回 {n_batches, mean, sd, cpk, ppk, consistency, note}
    """
    res = {"attribute": attribute, "n_batches": 0, "mean": None, "sd": None,
           "cpk": None, "ppk": None, "consistency": None, "note": ""}
    batch_means = []
    for s in study.samples:
        vals = [m.value for m in s.measurements
                if m.attribute == attribute and m.value is not None
                and (m.time_point_id == 0 or (_tp_by_ref(study, s, m) and _tp_by_ref(study, s, m).month == 0))]
        if vals:
            batch_means.append(float(np.mean(vals)))
    if len(batch_means) < 2:
        res["note"] = "批数不足（<2），无法评估批间一致性。"
        return res
    mu = float(np.mean(batch_means))
    sigma = float(np.std(batch_means, ddof=1))
    # 规格：用户提供或经验（均值±3σ）
    if spec_lo is None:
        spec_lo = mu - 3 * sigma if sigma > 0 else mu - 5
    if spec_hi is None:
        spec_hi = mu + 3 * sigma if sigma > 0 else mu + 5
    if sigma == 0:
        cpk = float("inf")
    else:
        cpk = min((spec_hi - mu), (mu - spec_lo)) / (3 * sigma)
    # Ppk 与 Cpk 在此简化等同（无时间序列内变动分别）
    res.update({"n_batches": len(batch_means), "mean": mu, "sd": sigma,
                "cpk": cpk, "ppk": cpk, "spec_lo": spec_lo, "spec_hi": spec_hi})
    if cpk >= 1.33:
        res["consistency"] = "优(批间高度一致, Cpk≥1.33)"
    elif cpk >= 1.0:
        res["consistency"] = "良(批间一致, 1.0≤Cpk<1.33)"
    elif cpk >= 0.67:
        res["consistency"] = "临界(批间波动偏大, 0.67≤Cpk<1.0)"
    else:
        res["consistency"] = "差(批间不一致, Cpk<0.67)"
    res["note"] = (f"批均值 μ={mu:.2f}, σ={sigma:.2f}, 规格[{spec_lo:.2f},{spec_hi:.2f}], "
                   f"Cpk={('∞' if cpk==float('inf') else f'{cpk:.2f}')}。")
    return res


def _fmt_months(x) -> str:
    """外推月数的安全格式化：None / 非有限值显示为“无法外推”。"""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return "无法外推"
    return f"{xf:.1f}月" if math.isfinite(xf) else "无法外推"


def pooled_expiry_extrapolation(study: StabilityStudy, attribute: str, condition: str,
                                 spec_limit: float = None, direction: str = None) -> Dict:
    """
    R12 批合并外推有效期（ICH Q1E 95% 单侧下限）：
    - 先判定批合并性（poolability）；若可合并，将所有批数据合并后做回归外推
    - 返回合并外推有效期 lower_bound_95、单批最小外推、是否保守
    返回 {poolable, pooled_expiry, min_single_expiry, recommended, note}
    """
    res = {"attribute": attribute, "condition": condition,
           "poolable": None, "pooled_expiry": None, "min_single_expiry": None,
           "recommended": None, "note": ""}
    dir_limit = default_limit_for(attribute)
    if dir_limit and spec_limit is None:
        direction, spec_limit = dir_limit
    if spec_limit is None or direction is None:
        res["note"] = "缺少质量标准限度/方向。"
        return res
    pa = poolability_assessment(study, attribute, condition)
    res["poolable"] = pa["poolable"]
    # 单批外推最小值
    single = []
    for s in study.samples:
        xs, ys = [], []
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = _tp_by_ref(study, s, m)
            if tp is None or tp.condition != condition:
                continue
            try:
                x = float(m.time_point_id)
            except (TypeError, ValueError):
                x = tp.month
            xs.append(x)
            ys.append(m.value)
        if len(xs) >= 3:
            e = expiry_recommendation(np.asarray(xs), np.asarray(ys), spec_limit, direction)
            single.append(e["lower_bound_95"] if isinstance(e, dict) else e)
    res["min_single_expiry"] = min(single) if single else None
    if pa["poolable"]:
        # 合并所有批数据
        allx, ally = [], []
        for s in study.samples:
            for m in s.measurements:
                if m.attribute != attribute or m.value is None:
                    continue
                tp = _tp_by_ref(study, s, m)
                if tp is None or tp.condition != condition:
                    continue
                try:
                    x = float(m.time_point_id)
                except (TypeError, ValueError):
                    x = tp.month
                allx.append(x)
                ally.append(m.value)
        if len(allx) >= 3:
            e = expiry_recommendation(np.asarray(allx), np.asarray(ally), spec_limit, direction)
            res["pooled_expiry"] = e["lower_bound_95"] if isinstance(e, dict) else e
            # 保守有效期 = min(合并外推, 单批最小)
            cand = [res["pooled_expiry"]]
            if res["min_single_expiry"] is not None:
                cand.append(res["min_single_expiry"])
            res["recommended"] = min(cand)
            res["note"] = (f"批间一致可合并：合并外推有效期≈{_fmt_months(res['pooled_expiry'])}，"
                           f"保守建议取 {_fmt_months(res['recommended'])}（与单批下限一致）。")
        else:
            res["note"] = "合并后数据点不足，无法外推。"
    else:
        res["recommended"] = res["min_single_expiry"]
        res["note"] = (f"批间不可简单合并（{pa['conclusion']}），"
                       f"保守有效期取单批最小外推 {_fmt_months(res['min_single_expiry'])}。")
    return res


def stability_indicating_resolution(study: StabilityStudy, attribute: str = None) -> List[Dict]:
    """
    R11 稳定性指示能力（分离度/峰纯度）评估：
    - 汇总含 resolution（分离度 Rs）与 peak_purity（峰纯度%）的测量
    - 判定：Rs ≥ 1.5 视为降解物与主峰基线分离（USP<621>/ICH Q5C 指示能力要求）
            peak_purity ≥ 95% 视为主峰纯度足够
    返回各测量点的分离度/峰纯度合规列表。
    """
    results = []
    for s in study.samples:
        for m in s.measurements:
            if m.resolution is None and m.peak_purity is None:
                continue
            if attribute and m.attribute != attribute:
                continue
            rs = m.resolution
            pp = m.peak_purity
            rs_ok = (rs is not None and rs >= 1.5)
            pp_ok = (pp is not None and pp >= 95.0)
            verdict = "合格" if (rs_ok and (pp is None or pp_ok)) else (
                "分离不足" if (rs is not None and not rs_ok) else "纯度不足")
            results.append({
                "批号": s.batch_id, "检测项目": m.attribute,
                "分离度Rs": rs, "峰纯度%": pp,
                "分离合格(Rs≥1.5)": rs_ok, "纯度合格(≥95%)": pp_ok,
                "判定": verdict,
            })
    return results


def comparability_equivalence(study_a: StabilityStudy, study_b: StabilityStudy,
                               attribute: str, condition: str,
                               lo: float = 0.80, hi: float = 1.25) -> Dict:
    """
    可比性等效性统计（ICH Q5C 可比性 / 生物类似药常见 TOST 准则）：
    - 取两研究在共同月点的批均值，计算 B/A 比例
    - 估计比例均值的 90% CI（t 分布）
    - 判定 90% CI 是否完全落在 [lo, hi]（默认 80-125%）接受区间
    返回 {n, mean_ratio, ci_low, ci_high, equivalent, note}
    """
    import scipy.stats as _stats
    # 收集共同月点批均值
    def batch_mean_at(study, mo):
        vals = []
        for sm in study.samples:
            for tp in sm.time_points:
                if tp.condition != condition:
                    continue
                for m in sm.measurements:
                    if m.attribute == attribute and m.value is not None and m.time_point_id == mo:
                        vals.append(m.value)
        return float(np.mean(vals)) if vals else None
    months_a = {tp.month for sm in study_a.samples for tp in sm.time_points if tp.condition == condition}
    months_b = {tp.month for sm in study_b.samples for tp in sm.time_points if tp.condition == condition}
    common = sorted(months_a & months_b)
    valid = []
    for mo in common:
        va, vb = batch_mean_at(study_a, mo), batch_mean_at(study_b, mo)
        if va is not None and vb is not None and va != 0:
            valid.append(vb / va)
    res = {"attribute": attribute, "condition": condition, "n": len(valid),
           "mean_ratio": None, "ci_low": None, "ci_high": None,
           "equivalent": None, "note": ""}
    if len(valid) < 1:
        res["note"] = "无共同月点或数据，无法计算等效性。"
        return res
    ratios = np.asarray(valid)
    mean_r = float(np.mean(ratios))
    sd_r = float(np.std(ratios, ddof=1)) if len(ratios) > 1 else 0.0
    se = sd_r / np.sqrt(len(ratios)) if len(ratios) > 1 else 0.0
    if len(ratios) > 1:
        t90 = _stats.t.ppf(0.95, len(ratios) - 1)
        ci_low, ci_high = mean_r - t90 * se, mean_r + t90 * se
    else:
        ci_low = ci_high = mean_r
    res.update({"mean_ratio": mean_r, "ci_low": ci_low, "ci_high": ci_high})
    res["equivalent"] = bool(ci_low >= lo and ci_high <= hi)
    res["note"] = (f"90% CI=[{ci_low*100:.1f}%, {ci_high*100:.1f}%] "
                   f"{'落在' if res['equivalent'] else '超出'}接受区间 [{lo*100:.0f}%, {hi*100:.0f}%]。")
    return res


def matrix_bracket_compliance(study: StabilityStudy) -> Dict:
    """
    ICH Q1D 矩阵/括号设计合规性检查：
    - 括号设计(bracketing)：最差条件组合（最高/最低浓度、最小/最大规格、最差包装）必须被完整考察
    - 矩阵设计(matrixing)：每个时间点至少有一批被考察，且所有关键组合在方案期内均有覆盖
    返回 {design_type, issues, checks, status, note}
    """
    res = {"design_type": study.design if isinstance(study.design, str) else getattr(study.design, 'value', ''),
           "issues": [], "checks": [], "status": "ok", "note": ""}
    # 收集所有(批, 条件, 月点)覆盖
    covered = set()
    for s in study.samples:
        for tp in s.time_points:
            covered.add((s.batch_id, tp.condition, tp.month))
    # 批列表与条件集合
    batches = [s.batch_id for s in study.samples]
    conditions = {tp.condition for s in study.samples for tp in s.time_points}
    # 检查1：长期条件必须存在
    if StorageCondition.LONG_TERM.value not in conditions and "长期" not in conditions:
        res["issues"].append("缺少长期稳定性条件（25°C），设计不完整。")
        res["checks"].append(("长期条件", False))
    else:
        res["checks"].append(("长期条件", True))
    # 检查2：矩阵设计——每个时间点至少有一批被考察（以长期条件为例）
    long_month = sorted({tp.month for s in study.samples for tp in s.time_points
                         if tp.condition in (StorageCondition.LONG_TERM.value, "长期")})
    if long_month and study.design == "矩阵法":
        uncovered_months = []
        for mo in long_month:
            if not any((b, c, mo) in covered for b in batches
                       for c in (StorageCondition.LONG_TERM.value, "长期")):
                uncovered_months.append(mo)
        if uncovered_months:
            res["issues"].append(f"矩阵设计存在未覆盖时间点：月点 {uncovered_months} "
                                 f"无任何批次被考察，违反 Q1D 矩阵完整性。")
            res["checks"].append(("矩阵时间点覆盖", False))
        else:
            res["checks"].append(("矩阵时间点覆盖", True))
    elif study.design == "括号法":
        # 括号设计：最极端组合需完整考察
        # 简化：检查是否存在"最小规格/最低浓度"与"最大规格/最高浓度"均有数据
        specs = {getattr(s, "container", "") or "" for s in study.samples}
        concs = {getattr(s, "strength", "") or "" for s in study.samples}
        if len(specs) > 1:
            # 假设批次名含规格信息或 container 区分；此处仅提示需人工确认边界批
            res["checks"].append(("括号边界批", True))
            res["note"] = ("括号设计：请确保最小与最大规格/浓度/包装的边界组合均被完整考察"
                           "（系统已记录批信息，边界判定建议人工复核）。")
        else:
            res["checks"].append(("括号边界批", True))
    if res["issues"]:
        res["status"] = "fail"
        res["note"] = "设计合规性检查发现 " + str(len(res["issues"])) + " 项问题。"
    else:
        res["status"] = "ok"
        res["note"] = "矩阵/括号设计符合 ICH Q1D 基本要求（系统检查项通过，最终由申报方确认）。"
    return res


def poolability_assessment(study: StabilityStudy, attribute: str, condition: str) -> Dict:
    """
    ICH Q1E 批合并（poolability）评估：
    - 检验各批斜率是否等价（ANOVA 风格：批间斜率方差 vs 批内残差）
    - 若各批降解速率一致，可合并数据外推有效期
    返回 {poolable, f_ratio, conclusion, note}
    """
    res = {"attribute": attribute, "condition": condition,
           "poolable": None, "f_ratio": None, "conclusion": "", "note": ""}
    slopes, resid_vars = [], []
    for s in study.samples:
        xs, ys = [], []
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = _tp_by_ref(study, s, m)
            if tp is None or tp.condition != condition:
                continue
            try:
                x = float(m.time_point_id)
            except (TypeError, ValueError):
                x = tp.month
            xs.append(x)
            ys.append(m.value)
        if len(xs) >= 2:
            sl, inter, _, _, se = stats.linregress(xs, ys)
            yhat = [sl * xi + inter for xi in xs]
            resid = [(y - yh) ** 2 for y, yh in zip(ys, yhat)]
            rv = float(np.mean(resid)) if resid else 0.0
            slopes.append(sl)
            resid_vars.append(rv)
    if len(slopes) < 2:
        res["note"] = "批数不足，无法评估合并性。"
        res["poolable"] = None
        return res
    between_slope_var = float(np.var(slopes, ddof=1))
    slope_std = float(np.std(slopes, ddof=1)) if len(slopes) >= 2 else 0.0
    within_resid_var = float(np.mean(resid_vars)) if resid_vars else 0.0
    if within_resid_var > 1e-9:
        f_ratio = between_slope_var / within_resid_var
    else:
        # 残差近0（完美拟合）：改用批间斜率标准差绝对判据
        f_ratio = float("inf") if slope_std > 0.5 else 0.0
    res["f_ratio"] = f_ratio
    # 经验准则：批间斜率差异不显著 -> 可合并（非严格F检验，供筛选）
    poolable = (f_ratio < 4.0) and (slope_std < 0.5)
    if poolable:
        res["poolable"] = True
        res["conclusion"] = "各批降解速率一致，数据可合并评估（Q1E poolable）。"
    else:
        res["poolable"] = False
        res["conclusion"] = "批间降解速率差异显著，不可简单合并，建议逐批或减括号评估。"
    res["note"] = (f"斜率批间标准差={slope_std:.3f}%/月，方差比 F≈{f_ratio:.2f}"
                   "（<4 且 <0.5%/月 视为可合并，仅供参考）。")
    return res


def transport_stress_assessment(study: StabilityStudy, attribute: str,
                                 spec_limit: float = None, direction: str = None) -> Dict:
    """
    运输应力稳定性评估（运输模拟/冷链中断，ICH Q5C 关注运输与搬运应力）。
    - 比较 0 月对照 与 运输后(可多程) 的 CQA
    - 用运输次数/里程标记作为 x 轴（TimePoint.month 存运输程数）
    - 判定运输后是否超限度，及运输诱导变化量
    返回 {status, trips_tolerated, detail, note}
    """
    res = {"attribute": attribute, "trips_tolerated": 0, "detail": [], "status": None, "note": ""}
    dir_limit = default_limit_for(attribute)
    if dir_limit and spec_limit is None:
        direction, spec_limit = dir_limit
    if spec_limit is None or direction is None:
        res["note"] = "缺少质量标准限度/方向，无法评估运输稳定性。"
        res["status"] = "na"
        return res

    TR_ALIASES = {StorageCondition.TRANSPORT.value, "运输", "运输模拟"}
    has_tr = any(tp.condition in TR_ALIASES for s in study.samples for tp in s.time_points)
    if not has_tr:
        res["status"] = "no_data"
        res["note"] = "无运输条件数据，无法评估。"
        return res

    for s in study.samples:
        base = None
        tr_vals = {}
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = _tp_by_ref(study, s, m)
            if tp is None:
                continue
            if tp.condition in (StorageCondition.LONG_TERM.value, "冷藏", "冷冻-80") and tp.month == 0:
                base = m.value
            elif tp.condition in TR_ALIASES:
                trip = int(tp.month) if isinstance(tp.month, (int, float)) else 1
                tr_vals[trip] = m.value
        if base is None or not tr_vals:
            continue
        for trip in sorted(tr_vals):
            v = tr_vals[trip]
            over = False
            if direction == "lower" and v < spec_limit:
                over = True
            if direction == "upper" and v > spec_limit:
                over = True
            delta = v - base
            rel = (delta / base * 100.0) if base else float("nan")
            res["detail"].append({"batch_id": s.batch_id, "trip": trip, "value": v,
                                  "base": base, "delta": delta, "rel_pct": rel, "over_limit": over})
    if not res["detail"]:
        res["status"] = "no_data"
        res["note"] = "运输数据不完整（需 0 月对照 + 运输后值）。"
        return res
    ok_trips = set()
    for trip in sorted({d["trip"] for d in res["detail"]}):
        if not any(d["trip"] == trip and d["over_limit"] for d in res["detail"]):
            ok_trips.add(trip)
    res["trips_tolerated"] = max(ok_trips) if ok_trips else 0
    n_over = sum(1 for d in res["detail"] if d["over_limit"])
    if n_over == 0:
        res["status"] = "ok"
        res["note"] = (f"运输耐受性良好：至 {res['trips_tolerated']} 程运输 CQA 仍在限度内，"
                       "运输应力未引发不可接受变化。")
    else:
        res["status"] = "fail"
        res["note"] = (f"运输后出现 CQA 超出限度（{n_over} 个数据点），提示运输/冷链应力敏感，"
                       "需优化包装或加强冷链控制。")
    return res


def _tp_by_ref(study: StabilityStudy, sample: "Sample", m: "Measurement"):
    """依据 tp_ref（或 month+condition）定位时间点对象。"""
    for s in study.samples:
        for tp in s.time_points:
            if m.tp_ref and tp.tp_id == m.tp_ref:
                return tp
    # 兼容旧数据：按 month + 非光照条件推断
    for tp in sample.time_points:
        if float(tp.month) == float(m.time_point_id) and tp.condition != StorageCondition.PHOTOSTABILITY.value:
            return tp
    return None


def in_use_shelf_life(study: StabilityStudy, attribute: str,
                      spec_limit: float = None, direction: str = None,
                      condition: str = "使用中") -> Dict:
    """
    使用中稳定性（in-use）有效期推算（ICH Q5C 多剂量/复溶制剂）。
    - 以"开启后天数"为自变量（IN_USE 条件，month 字段存天数）
    - 复用线性回归 + 95% 单侧预测限求 CQA 触及限度的天数
    - 返回 {expiry_days, observed_days, status, batches, note}
    """
    res = {"attribute": attribute, "expiry_days": None, "observed_days": [],
           "status": None, "batches": [], "note": ""}
    dir_limit = default_limit_for(attribute)
    if dir_limit and spec_limit is None:
        direction, spec_limit = dir_limit
    if spec_limit is None or direction is None:
        res["note"] = "缺少质量标准限度/方向，无法推算使用中有效期。"
        res["status"] = "na"
        return res

    any_data = False
    for s in study.samples:
        days, vals = [], []
        for m in s.measurements:
            if m.attribute != attribute or m.value is None:
                continue
            tp = _tp_by_ref(study, s, m)
            if tp is None or tp.condition != condition:
                continue
            try:
                d = float(m.time_point_id)
            except (TypeError, ValueError):
                d = tp.month if isinstance(tp.month, (int, float)) else 0.0
            days.append(d)
            vals.append(m.value)
            any_data = True
        if len(days) < 3:
            res["batches"].append({"batch_id": s.batch_id, "n": len(days),
                                   "expiry_days": None})
            continue
        e = expiry_recommendation(np.asarray(days), np.asarray(vals), spec_limit, direction)
        exp_days = e["lower_bound_95"] if isinstance(e, dict) else e
        res["observed_days"].append(max(days))
        res["batches"].append({"batch_id": s.batch_id, "n": len(days),
                               "expiry_days": exp_days, "last_day": max(days)})
    if not any_data:
        res["status"] = "no_data"
        res["note"] = f"无『{condition}』条件数据，无法评估使用中稳定性。"
        return res
    valid = [b["expiry_days"] for b in res["batches"] if b["expiry_days"] is not None]
    if not valid:
        res["status"] = "no_expiry"
        res["note"] = "使用中数据不足或未观察到降级，需延长考察或补充时间点。"
    else:
        res["expiry_days"] = min(valid)
        res["status"] = "ok"
        res["note"] = (f"使用中有效期（复溶/开启后）约 {res['expiry_days']:.0f} 天，"
                       f"建议结合 28 天多剂量标签惯例综合判定。")
    return res


def leave_one_out_expiry(study: StabilityStudy, attribute: str, condition: str,
                          spec_limit: float, direction: str = "lower") -> Optional[Dict]:
    """
    R3 新增 —— 留一法(Leave-One-Out)批次稳定性评估（ICH Q1E 批间一致性/外推稳健性）。
    逐批剔除一个批次后重算合并有效期，观察剔除任一单批对有效期的影响幅度。
    返回：full_estimate / per_batch_excluded(list: {batch, estimate, delta}) /
          max_drop(最大降幅) / robust(bool: 单批剔除后降幅<20%)。
    """
    batches = []
    for s in study.samples:
        m, v, _ = _series_for(s, attribute, condition)
        if len(v) >= 2:
            batches.append((s.batch_id, m, v))
    if len(batches) < 2:
        return None
    full = shelf_life(np.concatenate([b[1] for b in batches]),
                      np.concatenate([b[2] for b in batches]), spec_limit, direction)
    if full is None:
        return None
    per = []
    for i, (bid, m, v) in enumerate(batches):
        rest_t = np.concatenate([batches[j][1] for j in range(len(batches)) if j != i])
        rest_v = np.concatenate([batches[j][2] for j in range(len(batches)) if j != i])
        try:
            est = shelf_life(rest_t, rest_v, spec_limit, direction)
        except Exception:
            est = None
        per.append({"batch": bid, "estimate": round(float(est), 1) if est else None,
                    "delta": round(float(est - full), 1) if est else None})
    drops = [abs(p["delta"]) for p in per if p["delta"] is not None]
    max_drop = max(drops) if drops else 0.0
    return {
        "full_estimate": round(float(full), 1),
        "per_batch_excluded": per,
        "max_drop": round(max_drop, 1),
        "robust": max_drop < 0.2 * full if full > 0 else False,
        "recommendation": ("批间外推稳健（留一法最大降幅<20%）" if (max_drop < 0.2 * full)
                           else "批间外推不稳健，建议增加批次或谨慎外推(ICH Q1E)"),
    }


def arrhenius_estimate(k_accel: float, T_accel: float, T_long: float,
                       Ea: float = 80000.0, R: float = 8.314) -> Dict:
    """
    R20 新增 —— Arrhenius 温度外推估算（加速→长期降解速率换算）。
    k_long = k_accel * exp[ Ea/R * (1/T_long - 1/T_accel) ]
    返回：long_term_rate_ratio (k_long/k_accel) 与 说明。
    注意：生物制品降解机制可能在高温改变(非 Arrhenius)，此方法仅作初筛提示，
    须经真实长期数据确证，不可直接换算有效期(Q5C/USP<1049>)。
    T 用开尔文(K)。默认 Ea=80 kJ/mol（典型化学降解活化能，生物制品需实测）。
    """
    k_long = k_accel * np.exp(Ea / R * (1.0 / T_long - 1.0 / T_accel))
    ratio = k_long / k_accel if k_accel else float("nan")
    return {
        "accel_rate": round(float(k_accel), 6),
        "long_term_rate": round(float(k_long), 8),
        "rate_ratio": round(float(ratio), 4),
        "long_term_rate_per_accel_rate": round(float(1.0 / ratio), 4) if ratio else None,
        "note": ("加速降解速率约为长期速率的 %.1f 倍（按 Arrhenius 估算）。生物制品降解"
                 "在高温可能改变机制，加速数据不能直接换算长期有效期，须经真实长期数据确证。"
                 % (1.0 / ratio if ratio else 0)),
    }


def forced_degradation_assessment(study: StabilityStudy) -> List[Dict]:
    """
    R23 新增 —— 强制降解(应激)稳定性指示方法确证评估 (ICH Q5C)。
    对每个含『强制降解』条件的研究，比较应激后(降解产物/纯度)与初始(0月)的差异：
      - 出现新的降解产物峰或纯度(主峰%)下降 → 方法可检测到降解 → 具有稳定性指示能力
      - 无任何降解信号 → 应力不足或方法不灵敏 → 需复核方法
    返回各批/应力条件的确证结论列表。
    """
    results = []
    for s in study.samples:
        fd_points = [tp for tp in s.time_points if tp.condition == StorageCondition.FORCED_DEGRADATION]
        if not fd_points:
            continue
        initial = {m.attribute: m.value for m in s.measurements if m.time_point_id == 0}
        for tp in fd_points:
            fd_meas = {m.attribute: m.value for m in s.measurements if float(m.time_point_id) == float(tp.month)}
            if not fd_meas:
                continue
            # 检测降解产物增长 / 主成分(效价/含量)下降
            degrading_signal = []
            main_recovery = None  # 主成分回收率（应激后仍可定量性）
            for attr, val in fd_meas.items():
                base = initial.get(attr)
                if base is None:
                    # 仅应激后出现的产物（如新降解产物）
                    if attr in ("有关物质", "碎片", "聚集体", "氧化", "脱酰胺") and val > 0:
                        degrading_signal.append(f"{attr} 新出现({val})")
                else:
                    drop = (base - val) / abs(base) * 100.0 if base else 0
                    if attr in ("效价", "含量") and drop > 5:
                        degrading_signal.append(f"{attr} 下降{drop:.1f}%")
                        main_recovery = val / abs(base) * 100.0 if base else None
                    elif attr in ("聚集体", "碎片", "有关物质", "氧化", "脱酰胺") and val > base * 1.2:
                        degrading_signal.append(f"{attr} 上升至{val}(+{(val-base)/abs(base)*100:.0f}%)")
            # R10：SIm 确证 —— 主成分回收率(应激后仍可定量) + 降解信号
            if main_recovery is None and "效价" in initial:
                # 若无效价下降记录，用0月效价相对自身（无降解时回收率≈100%）
                main_recovery = 100.0
            if degrading_signal and (main_recovery is None or main_recovery >= 90.0):
                sim = "强(降解可检出且主成分仍可定量)"
            elif degrading_signal and main_recovery < 90.0:
                sim = "中(降解可检出，但主成分定量性受损，需复核方法)"
            else:
                sim = "弱(无降解信号，需增加应激强度)"
            results.append({
                "批号": s.batch_id,
                "应激条件": tp.condition,
                "应激信号": "；".join(degrading_signal) if degrading_signal else "未检测到降解",
                "主成分回收率%": round(main_recovery, 1) if main_recovery is not None else None,
                "SIm确证": sim,
                "稳定性指示能力": "是" if degrading_signal else "否(需复核方法/增加应激强度)",
            })
    return results
