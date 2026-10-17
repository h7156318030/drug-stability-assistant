"""PostgreSQL 后端测试（需要真实 PostgreSQL）。

启用方式：设置环境变量 STAB_TEST_PG_URL 指向一个【一次性】测试数据库，例如：
    postgresql://user:pass@127.0.0.1:5432/stability_test

警告：本测试会先删除该数据库中的 studies/samples/time_points/measurements/users/audit_log 表。
请勿指向生产库。未设置该变量时本测试跳过（退出码 0，输出 SKIP）。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PG_URL = os.environ.get("STAB_TEST_PG_URL", "").strip()

if not PG_URL:
    print("SKIP: 未设置 STAB_TEST_PG_URL，跳过 PostgreSQL 测试")
    sys.exit(0)

sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
os.environ["DATABASE_URL"] = PG_URL
os.environ["STAB_DATA_DIR"] = tempfile.mkdtemp(prefix="stab_pgtest_")  # 不会用于 PostgreSQL 数据
os.environ["STAB_ADMIN_PASSWORD"] = "Test-Admin#2026"

import psycopg2  # noqa: E402

import auth as AU  # noqa: E402
import db as DB  # noqa: E402
import planner as P  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


print("== 0. 清理测试库（仅限一次性数据库）")
conn = psycopg2.connect(PG_URL)
conn.autocommit = True
with conn.cursor() as cur:
    for t in ["measurements", "time_points", "samples", "studies", "audit_log", "users"]:
        cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
conn.close()

print("== 1. 建表与幂等初始化")
AU.init_auth()
AU.init_auth()
DB.init()
DB.init()
check("初始化后仅有 1 个管理员", len(AU.list_users()) == 1)

print("== 2. 研究保存（含 upsert）、读取与级联删除")
study = P.create_from_template("化药片剂(室温)", "PG功能测试", "测试", ["B1", "B2"], "2026-01-15", "")
DB.save_study(study.to_dict())
DB.save_study(study.to_dict())  # 第二次为更新，不应产生重复记录
check("重复保存不产生重复研究", len(DB.list_studies()) == 1)
loaded = DB.load_study(study.study_id)
check("读回研究名称一致", loaded is not None and loaded["name"] == "PG功能测试")
check("读回样品数量一致", len(loaded["samples"]) == 2)
DB.delete_study(study.study_id)
check("删除研究后无残留样品", DB.load_study(study.study_id) is None)

print("== 3. 审计哈希链与备份恢复")
AU.audit("PG_TEST", "study", "x", "admin", "admin", "127.0.0.1", "t", None, None, note="pg")
check("审计哈希链校验通过", AU.verify_audit_integrity()["ok"] is True)
study2 = P.create_from_template("化药片剂(室温)", "PG备份测试", "测试", ["B1"], "2026-01-15", "")
DB.save_study(study2.to_dict())
backup = DB.export_all_json()
DB.import_all_json(backup, merge=True)
check("追加式恢复后研究仍存在", DB.load_study(study2.study_id) is not None)
n_users = len(AU.list_users())
DB.import_all_json(backup, merge=False)
check("全量恢复不清空用户表", len(AU.list_users()) == n_users)
check("全量恢复后审计链仍完整", AU.verify_audit_integrity()["ok"] is True)

print("== 4. 口令复核")
check("正确口令复核通过", AU.reauthenticate("admin", "Test-Admin#2026") is True)
check("错误口令复核失败", AU.reauthenticate("admin", "wrong-password") is False)

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
