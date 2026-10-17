"""批量数据导入（CSV）。与界面解耦，便于单元测试。

CSV 列（必需）：批号, 条件, 月点, 检测项目, 数值
CSV 列（可选）：单位, 限度, 方向（lower/upper；留空按项目默认判断）
"""

import io
from typing import List, Tuple

import pandas as pd

import models as M

REQUIRED_COLUMNS = ["批号", "条件", "月点", "检测项目", "数值"]
TEMPLATE_CSV = (
    "批号,条件,月点,检测项目,数值,单位,限度,方向\n"
    "B2026-001,冷藏(2-8C),0,效价,100.0,%,80,lower\n"
    "B2026-001,冷藏(2-8C),3,效价,99.5,%,80,lower\n"
)


def read_bulk_csv(data: bytes) -> pd.DataFrame:
    """读取 CSV 字节流。依次尝试 UTF-8（含 BOM）与 GBK（中文 Excel 常见编码）。"""
    last_err = None
    for enc in ("utf-8-sig", "gbk"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, dtype=str, keep_default_na=False)
        except UnicodeDecodeError as e:
            last_err = e
    raise ValueError(f"无法识别的文件编码（请使用 UTF-8 或 GBK）：{last_err}")


def _opt(row, col: str):
    """可选列：列不存在或为空返回 None。"""
    if col not in row.index:
        return None
    v = str(row[col]).strip()
    return v if v else None


def import_bulk_csv(study: M.StabilityStudy, bulk: pd.DataFrame) -> Tuple[int, List[str]]:
    """把 CSV 各行写入研究（就地修改 study，不负责持久化）。

    返回 (写入条数, 跳过说明列表)。缺少必需列时抛出 ValueError。
    同一批号 + 条件 + 月点的时间点若不存在，会自动补建。
    """
    miss = [c for c in REQUIRED_COLUMNS if c not in bulk.columns]
    if miss:
        raise ValueError(f"缺少列：{miss}")

    sample_by_batch = {s.batch_id: s for s in study.samples}
    cnt = 0
    skipped: List[str] = []
    for line_no, (_, row) in enumerate(bulk.iterrows(), start=2):  # 第 1 行为表头
        batch = str(row["批号"]).strip()
        sample = sample_by_batch.get(batch)
        if sample is None:
            skipped.append(f"第 {line_no} 行：批号 {batch} 不属于本研究")
            continue
        try:
            tp_month = float(row["月点"])
            value = float(row["数值"])
        except ValueError:
            skipped.append(f"第 {line_no} 行：月点或数值不是数字")
            continue
        cond = str(row["条件"]).strip()
        attr = str(row["检测项目"]).strip()
        if not attr:
            skipped.append(f"第 {line_no} 行：检测项目为空")
            continue

        match_tp = next((tp for tp in sample.time_points
                         if abs(tp.month - tp_month) < 1e-6 and tp.condition == cond), None)
        if match_tp is None:
            match_tp = M.TimePoint(tp_month, "", cond)
            sample.time_points.append(match_tp)

        unit = _opt(row, "单位") or "%"
        lim_txt = _opt(row, "限度")
        lim = float(lim_txt) if lim_txt is not None else None
        direction = _opt(row, "方向")
        if not direction:
            dft = M.default_limit_for(attr)
            direction = dft[0] if dft else ("upper" if attr in ("有关物质", "杂质", "聚集体", "碎片") else "lower")
        cqa = attr if study.biologic else ""
        sample.measurements.append(M.Measurement(tp_month, attr, value, unit, lim, lim is not None,
                                                 "", cqa, direction, tp_ref=match_tp.tp_id))
        cnt += 1
    return cnt, skipped
