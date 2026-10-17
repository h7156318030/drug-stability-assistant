"""
生成示例研究数据，便于首次体验系统。
运行： python tools/seed_example.py
（数据写入 STAB_DATA_DIR 或项目根目录的 stability.db；请勿在生产数据库上运行）

生成：
  - 示例1：化药片剂稳定性研究（含量/有关物质）
  - 示例2：生物制品单抗稳定性研究（效价/聚集体/碎片，冷藏条件，含非线性降解演示）
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import models as M
import planner as P
import db as DB


def build_chem():
    study = M.StabilityStudy(
        name="示例：某片剂稳定性研究",
        study_type=M.StudyType.DRUG_PRODUCT,
        drug_name="盐酸XX片",
        sponsor="研发质量部",
        design=M.DesignType.FULL,
        start_date="2026-01-15",
    )
    P.add_sample_with_plan(study, "B2026-001", "铝塑+复合膜", "10mg", ["长期", "加速"])
    sample = study.samples[0]

    long_tps = {tp.month: tp for tp in sample.time_points if tp.condition == "长期"}
    long_vals = {0: 100.0, 3: 99.4, 6: 98.8, 9: 98.2, 12: 97.6}
    for m, v in long_vals.items():
        sample.measurements.append(M.Measurement(long_tps[m].month, "含量", v, "%", 90.0, False, tp_ref=long_tps[m].tp_id))
    imp_vals = {0: 0.3, 3: 0.5, 6: 0.8, 9: 1.1, 12: 1.4}
    for m, v in imp_vals.items():
        sample.measurements.append(M.Measurement(long_tps[m].month, "有关物质", v, "%", 2.0, True, tp_ref=long_tps[m].tp_id))

    acc_tps = {tp.month: tp for tp in sample.time_points if tp.condition == "加速"}
    acc_assay = {0: 100.0, 3: 98.0, 6: 95.5}
    acc_imp = {0: 0.3, 3: 0.9, 6: 1.6}
    for m, v in acc_assay.items():
        sample.measurements.append(M.Measurement(acc_tps[m].month, "含量", v, "%", 90.0, False, tp_ref=acc_tps[m].tp_id))
    for m, v in acc_imp.items():
        sample.measurements.append(M.Measurement(acc_tps[m].month, "有关物质", v, "%", 2.0, True, tp_ref=acc_tps[m].tp_id))

    DB.save_study(study.to_dict())
    print(f"[化药] 示例已生成：{study.name} (ID={study.study_id})")


def build_bio():
    study = M.StabilityStudy(
        name="示例：单抗注射液稳定性研究",
        study_type=M.StudyType.DRUG_PRODUCT,
        drug_name="抗XX单抗注射液",
        sponsor="生物药研发部",
        design=M.DesignType.FULL,
        start_date="2026-03-01",
        biologic=True,
        molecule_type=M.MoleculeType.ANTIBODY,
    )
    P.add_sample_with_plan(study, "MAB-2026-001", "2R玻璃瓶+橡胶塞", "100mg/mL",
                           ["冷藏"], molecule_type=M.MoleculeType.ANTIBODY)
    sample = study.samples[0]
    tp_by_month = {tp.month: tp for tp in sample.time_points if tp.condition == "冷藏"}

    # 效价：缓慢下降（下限80%）
    potency = {0: 100.0, 3: 99.0, 6: 98.0, 9: 96.5, 12: 95.0}
    for m, v in potency.items():
        sample.measurements.append(M.Measurement(tp_by_month[m].month, "效价", v, "%", 80.0, False, tp_ref=tp_by_month[m].tp_id))
    # 聚集体：S型增长（上限5%）—— 演示非线性降解
    agg = {0: 1.2, 3: 1.5, 6: 2.1, 9: 3.4, 12: 4.8}
    for m, v in agg.items():
        sample.measurements.append(M.Measurement(tp_by_month[m].month, "聚集体", v, "%", 5.0, True, tp_ref=tp_by_month[m].tp_id))
    # 碎片：缓升（上限10%）
    frag = {0: 2.0, 3: 2.4, 6: 3.0, 9: 3.8, 12: 4.6}
    for m, v in frag.items():
        sample.measurements.append(M.Measurement(tp_by_month[m].month, "碎片", v, "%", 10.0, True, tp_ref=tp_by_month[m].tp_id))

    DB.save_study(study.to_dict())
    print(f"[生物制品] 示例已生成：{study.name} (ID={study.study_id})")


if __name__ == "__main__":
    DB.init()
    build_chem()
    build_bio()
    print("示例数据生成完成。")
