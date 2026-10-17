"""
药品稳定性研究 —— 数据库后端（PostgreSQL / SQLite 可切换）

通过环境变量 DATABASE_URL 控制后端：
  - 设置 postgresql://user:pass@host:5432/db  -> 使用 PostgreSQL
  - 未设置                                   -> 使用本地 SQLite (stability.db)

研究数据四张表：studies / samples / time_points / measurements
认证与审计相关表在 auth.py 中维护。

占位符适配：SQLite 用 '?'，PostgreSQL 用 '%s'，统一用 _sql() 转换。
"""

import os
import json
import uuid
from datetime import datetime
from contextlib import contextmanager
from typing import Dict, List, Optional

# 复用 auth 的后端连接（统一 PG / SQLite 切换）
from auth import _conn as _base_conn, _pg_url


def _sql(sql: str) -> str:
    """将 SQLite 占位符 '?' 转换为 PG 的 '%s'（当使用 PG 时）"""
    if _pg_url():
        return sql.replace("?", "%s")
    return sql


def get_conn():
    conn, _ = _base_conn()
    return conn


@contextmanager
def transaction():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_DDL = [
    """CREATE TABLE IF NOT EXISTS studies (
        study_id      TEXT PRIMARY KEY,
        name          TEXT NOT NULL,
        study_type    TEXT NOT NULL,
        drug_name     TEXT,
        sponsor       TEXT,
        design        TEXT,
        biologic      INTEGER DEFAULT 0,
        molecule_type TEXT,
        stage         TEXT DEFAULT '',
        related_study_id   TEXT DEFAULT '',
        related_study_type TEXT DEFAULT '',
        meta_json     TEXT,
        start_date    TEXT,
        created_at    TEXT,
        updated_at    TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS samples (
        sample_id    TEXT PRIMARY KEY,
        study_id     TEXT NOT NULL,
        batch_id     TEXT,
        packaging    TEXT,
        strength     TEXT,
        molecule_type TEXT,
        FOREIGN KEY (study_id) REFERENCES studies(study_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS time_points (
        tp_id        TEXT PRIMARY KEY,
        sample_id    TEXT NOT NULL,
        month        REAL,
        planned_date TEXT,
        condition    TEXT,
        status       TEXT,
        pulled       INTEGER DEFAULT 0,
        FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE IF NOT EXISTS measurements (
        m_id         TEXT PRIMARY KEY,
        sample_id    TEXT NOT NULL,
        tp_id        TEXT,
        month        REAL,
        attribute    TEXT,
        cqa_category TEXT,
        value        REAL,
        unit         TEXT,
        limit_spec   REAL,
        is_limit     INTEGER DEFAULT 0,
        direction    TEXT,
        note         TEXT,
        FOREIGN KEY (sample_id) REFERENCES samples(sample_id) ON DELETE CASCADE,
        FOREIGN KEY (tp_id) REFERENCES time_points(tp_id) ON DELETE CASCADE
    )""",
    "CREATE INDEX IF NOT EXISTS idx_samples_study ON samples(study_id)",
    "CREATE INDEX IF NOT EXISTS idx_tp_sample ON time_points(sample_id)",
    "CREATE INDEX IF NOT EXISTS idx_m_sample ON measurements(sample_id)",
]


def init_db():
    with transaction() as conn:
        cur = conn.cursor()
        for stmt in _DDL:
            cur.execute(_sql(stmt))
        # 兼容已有库：补全 studies 新列（stage/related/meta_json）
        if _pg_url():
            cur.execute("SELECT column_name AS name FROM information_schema.columns WHERE table_name='studies'")
        else:
            cur.execute("PRAGMA table_info(studies)")
        cols = {dict(r)["name"] for r in cur.fetchall()}
        for col, ctype in [("stage", "TEXT DEFAULT ''"),
                           ("related_study_id", "TEXT DEFAULT ''"),
                           ("related_study_type", "TEXT DEFAULT ''"),
                           ("meta_json", "TEXT")]:
            if col not in cols:
                cur.execute(f"ALTER TABLE studies ADD COLUMN {col} {ctype}")
        cur.close()


# ----------------------------------------------------------------------------
# 研究 CRUD
# ----------------------------------------------------------------------------
def save_study(data: Dict):
    now = datetime.now().isoformat(timespec="seconds")
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute(_sql(
            """INSERT INTO studies
               (study_id,name,study_type,drug_name,sponsor,design,biologic,molecule_type,stage,related_study_id,related_study_type,meta_json,start_date,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (study_id) DO UPDATE SET
                 name=excluded.name, study_type=excluded.study_type, drug_name=excluded.drug_name,
                 sponsor=excluded.sponsor, design=excluded.design, biologic=excluded.biologic,
                 molecule_type=excluded.molecule_type, stage=excluded.stage,
                 related_study_id=excluded.related_study_id, related_study_type=excluded.related_study_type,
                 meta_json=excluded.meta_json, start_date=excluded.start_date,
                 updated_at=excluded.updated_at"""),
            (data["study_id"], data["name"], data["study_type"], data.get("drug_name"),
             data.get("sponsor"), data.get("design"), int(data.get("biologic", 0)),
             data.get("molecule_type"), data.get("stage", ""),
             data.get("related_study_id", ""), data.get("related_study_type", ""),
             data.get("meta_json"), data.get("start_date"),
             data.get("created_at", now), now),
        )
        cur.execute(_sql("DELETE FROM measurements WHERE sample_id IN (SELECT sample_id FROM samples WHERE study_id=?)"), (data["study_id"],))
        cur.execute(_sql("DELETE FROM time_points WHERE sample_id IN (SELECT sample_id FROM samples WHERE study_id=?)"), (data["study_id"],))
        cur.execute(_sql("DELETE FROM samples WHERE study_id=?"), (data["study_id"],))
        for s in data["samples"]:
            cur.execute(_sql(
                "INSERT INTO samples (sample_id,study_id,batch_id,packaging,strength,molecule_type) VALUES (?,?,?,?,?,?)"),
                (s["sample_id"], data["study_id"], s["batch_id"], s["packaging"],
                 s.get("strength", ""), s.get("molecule_type", data.get("molecule_type"))))
            for tp in s["time_points"]:
                cur.execute(_sql(
                    """INSERT INTO time_points (tp_id,sample_id,month,planned_date,condition,status,pulled)
                       VALUES (?,?,?,?,?,?,?)"""),
                    (tp.get("tp_id") or str(uuid.uuid4())[:8], s["sample_id"], tp["month"], tp["planned_date"],
                     tp["condition"], tp.get("status", "计划中"), int(tp.get("pulled", False))))
            for m in s["measurements"]:
                cur.execute(_sql(
                    """INSERT INTO measurements
                       (m_id,sample_id,tp_id,month,attribute,cqa_category,value,unit,limit_spec,is_limit,direction,note)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""),
                    (str(uuid.uuid4())[:8], s["sample_id"], m.get("tp_ref"), m.get("time_point_id"),
                     m["attribute"], m.get("cqa_category"), m.get("value"),
                     m.get("unit", ""), m.get("limit_spec"), int(m.get("is_limit", False)),
                     m.get("direction"), m.get("note", "")))
        cur.close()


def load_study(study_id: str) -> Optional[Dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(_sql("SELECT * FROM studies WHERE study_id=?"), (study_id,))
        row = cur.fetchone()
        if not row:
            return None
        study = dict(row)
        samples = []
        cur.execute(_sql("SELECT * FROM samples WHERE study_id=?"), (study_id,))
        for s in cur.fetchall():
            sd = dict(s)
            cur.execute(_sql("SELECT * FROM time_points WHERE sample_id=?"), (sd["sample_id"],))
            tps = [dict(t) for t in cur.fetchall()]
            cur.execute(_sql("SELECT * FROM measurements WHERE sample_id=?"), (sd["sample_id"],))
            ms = [dict(m) for m in cur.fetchall()]
            sd["time_points"] = [{
                "tp_id": t["tp_id"], "month": t["month"], "planned_date": t["planned_date"],
                "condition": t["condition"], "status": t["status"], "pulled": bool(t["pulled"]),
            } for t in tps]
            sd["measurements"] = [{
                "time_point_id": m["month"], "attribute": m["attribute"],
                "cqa_category": m["cqa_category"], "value": m["value"], "unit": m["unit"],
                "limit_spec": m["limit_spec"], "is_limit": bool(m["is_limit"]),
                "direction": m["direction"], "note": m["note"],
                "tp_ref": m.get("tp_id", ""),
            } for m in ms]
            samples.append(sd)
        study["samples"] = samples
        cur.close()
        return study


def list_studies() -> List[Dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(_sql(
            "SELECT study_id,name,drug_name,study_type,design,biologic,molecule_type,stage,related_study_id,related_study_type,start_date,updated_at FROM studies"))
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows


def delete_study(study_id: str):
    with transaction() as conn:
        cur = conn.cursor()
        # 显式级联删除子表（双保险，避免外键约束未生效时残留孤儿数据）
        cur.execute(_sql(
            "DELETE FROM measurements WHERE sample_id IN (SELECT sample_id FROM samples WHERE study_id=?)"), (study_id,))
        cur.execute(_sql(
            "DELETE FROM time_points WHERE sample_id IN (SELECT sample_id FROM samples WHERE study_id=?)"), (study_id,))
        cur.execute(_sql("DELETE FROM samples WHERE study_id=?"), (study_id,))
        cur.execute(_sql("DELETE FROM studies WHERE study_id=?"), (study_id,))
        cur.close()


def init():
    init_db()


# ----------------------------------------------------------------------------
# 备份 / 恢复（整库 JSON 导出导入）
# ----------------------------------------------------------------------------
def export_all_json() -> str:
    """导出整库为 JSON 字符串（研究 + 样品 + 时间点 + 检测值 + 审计 + 用户）。"""
    conn, _ = _base_conn()
    try:
        cur = conn.cursor()
        def fetch(table):
            cur.execute(f"SELECT * FROM {table}")
            return [dict(r) for r in cur.fetchall()]
        payload = {
            "tables": {
                "studies": fetch("studies"),
                "samples": fetch("samples"),
                "time_points": fetch("time_points"),
                "measurements": fetch("measurements"),
                "audit_log": fetch("audit_log"),
                "users": fetch("users"),
            }
        }
        cur.close()
    finally:
        conn.close()
    return json.dumps(payload, ensure_ascii=False, default=str)


def import_all_json(data: str, merge: bool = False):
    """
    从 JSON 字符串恢复整库。
    merge=False：清空现有研究数据后重建（studies/samples/time_points/measurements），
                 但【保留 audit_log 与 users】（不破坏 21 CFR Part 11 合规与账号）。
                 并在恢复后追加一条『数据库恢复』审计记录。
    merge=True：仅追加不存在的研究；audit_log/users 均跳过。
    """
    payload = json.loads(data)
    tables = payload.get("tables", {})
    is_pg = _pg_url() is not None
    conn, _ = _base_conn()
    # autocommit 模式：使 PRAGMA foreign_keys=OFF 在事务外生效（SQLite 不允许在事务内更改该 pragma）
    if not is_pg:
        conn.isolation_level = None
    try:
        cur = conn.cursor()
        if not merge:
            # 注意：不清空 audit_log / users，确保审计链与账号不丢失
            for t in ["measurements", "time_points", "samples", "studies"]:
                cur.execute(f"DELETE FROM {t}")
        ph = "?" if not is_pg else "%s"
        # 受信任本地备份还原：临时关闭外键约束，避免瞬时/顺序不一致导致 IntegrityError
        if not is_pg:
            cur.execute("PRAGMA foreign_keys=OFF")
        # 按外键依赖顺序插入（父表先于子表）
        for table in ["studies", "samples", "time_points", "measurements"]:
            rows = tables.get(table)
            if not rows:
                continue
            cols = list(rows[0].keys())
            for r in rows:
                rcols = [c for c in cols if c in r]
                placeholders = ", ".join([ph] * len(rcols))
                col_sql = ", ".join(rcols)
                if not is_pg:
                    cur.execute(f"INSERT OR IGNORE INTO {table} ({col_sql}) VALUES ({placeholders})",
                                [r[c] for c in rcols])
                else:
                    cur.execute(f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders}) "
                                f"ON CONFLICT DO NOTHING", [r[c] for c in rcols])
        # 追加恢复审计（保留可追溯性，不破坏既有 audit_log）
        # 注意：audit_log 实际列名为 username/role/object_type/object_id/note（见 auth._init_db）
        cur.execute(
            f"INSERT INTO audit_log (log_id, ts, username, role, action, object_type, object_id, note) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (str(__import__("uuid").uuid4()),
             datetime.now().isoformat(timespec="seconds"),
             (os.environ.get("STABILITY_RESTORE_USER") or "system"), "system",
             "DB_RESTORE", "database", "-",
             f"恢复模式={'全量覆盖' if not merge else '追加'}（audit_log/users 保留）"))
        conn.commit()
        cur.close()
    finally:
        conn.close()
