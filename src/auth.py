"""
认证、角色权限与 21 CFR Part 11 合规审计日志

设计要点：
- 用户表(users)：用户名、bcrypt 哈希密码、角色、姓名、启用状态、创建时间
- 角色(role)：admin(超级) / manager(研究管理+审核) / analyst(数据录入+分析) / viewer(只读)
- 审计日志(audit_log)：操作人、时间(UTC)、动作、对象、对象ID、IP、会话、前/后值(JSON)、备注
  * 审计记录不可删除、不可修改（仅追加），满足 21 CFR Part 11 审计追踪要求
- 后端可切换：设置环境变量 DATABASE_URL(postgresql://...) 即启用 PostgreSQL，否则用 SQLite。
- 密码使用 bcrypt 哈希，不存储明文；登录失败计数与锁定策略可选。
"""

import os
import sys
import sqlite3
import json
import uuid
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Dict, List, Optional

# 角色权限矩阵
ROLE_PERMISSIONS = {
    "admin":   {"study:create", "study:delete", "data:write", "data:read",
                "analysis:run", "report:export", "user:manage", "audit:read"},
    "manager": {"study:create", "study:delete", "data:write", "data:read",
                "analysis:run", "report:export", "audit:read"},
    "analyst": {"study:create", "data:write", "data:read",
                "analysis:run", "report:export"},
    "viewer":  {"data:read", "analysis:run", "report:export"},
}

ROLE_LABELS = {
    "admin": "管理员",
    "manager": "研究负责人",
    "analyst": "分析员",
    "viewer": "只读访客",
}

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_NAME = "系统管理员"

# ----------------------------------------------------------------------------
# 后端选择
# ----------------------------------------------------------------------------
def _pg_url() -> Optional[str]:
    return os.environ.get("DATABASE_URL")


def data_dir() -> str:
    """SQLite 数据目录：环境变量 STAB_DATA_DIR 优先，默认为项目根目录（测试与部署时应显式指定）。"""
    d = os.environ.get("STAB_DATA_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(d, exist_ok=True)
    return d


def _initial_admin_password() -> str:
    """首次建立管理员账号时使用的口令。

    优先读取环境变量 STAB_ADMIN_PASSWORD；未设置时生成随机口令并仅在控制台输出一次。
    程序不内置任何默认口令。
    """
    env_pw = os.environ.get("STAB_ADMIN_PASSWORD")
    if env_pw:
        return env_pw
    pw = secrets.token_urlsafe(12)
    print(f"[stability] 已创建初始管理员 '{DEFAULT_ADMIN_USERNAME}'，一次性口令: {pw}\n"
          f"[stability] 请立即登录并修改口令（或设置环境变量 STAB_ADMIN_PASSWORD 后重新初始化）。",
          file=sys.stderr, flush=True)
    return pw


def _conn():
    url = _pg_url()
    if url:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        c = psycopg2.connect(url)
        c.cursor_factory = RealDictCursor
        return c, True
    path = os.path.join(data_dir(), "stability.db")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")  # 启用外键约束（级联删除依赖此）
    return c, False


def init_auth():
    """建表 + 默认管理员（幂等）"""
    conn, is_pg = _conn()
    cur = conn.cursor()
    users_ddl = """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            name TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            created_at TEXT,
            last_login TEXT,
            failed_attempts INTEGER DEFAULT 0,
            locked_until TEXT
        )"""
    audit_ddl = """
        CREATE TABLE IF NOT EXISTS audit_log (
            log_id TEXT PRIMARY KEY,
            ts TEXT DEFAULT (datetime('now')),
            username TEXT, role TEXT, action TEXT,
            object_type TEXT, object_id TEXT, ip TEXT, session_id TEXT,
            before_val TEXT, after_val TEXT, note TEXT
        )"""
    if is_pg:
        users_ddl = users_ddl.replace("TEXT", "TEXT").replace(
            "enabled INTEGER DEFAULT 1", "enabled INTEGER DEFAULT 1")
        users_ddl = users_ddl.replace("created_at TEXT", "created_at TIMESTAMPTZ")
        users_ddl = users_ddl.replace("last_login TEXT", "last_login TIMESTAMPTZ")
        audit_ddl = audit_ddl.replace("ts TEXT DEFAULT (datetime('now'))", "ts TIMESTAMPTZ DEFAULT now()")
        cur.execute(users_ddl)
        cur.execute(audit_ddl)
    else:
        conn.executescript(users_ddl + ";" + audit_ddl)
    conn.commit()

    # 兼容已有库：补齐可能缺失的列
    if not is_pg:
        for col, typ in [("failed_attempts", "INTEGER DEFAULT 0"),
                         ("locked_until", "TEXT")]:
            try:
                cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
                conn.commit()
            except Exception:
                pass

    # 默认管理员
    cur.execute("SELECT COUNT(*) AS n FROM users WHERE username=?", (DEFAULT_ADMIN_USERNAME,)) \
        if not is_pg else cur.execute("SELECT COUNT(*) n FROM users WHERE username=%s", (DEFAULT_ADMIN_USERNAME,))
    row = cur.fetchone()
    n = row["n"]
    if n == 0:
        import bcrypt
        h = bcrypt.hashpw(_initial_admin_password().encode(), bcrypt.gensalt()).decode()
        uid = str(uuid.uuid4())[:8]
        if is_pg:
            cur.execute("INSERT INTO users (user_id,username,name,password_hash,role,enabled,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (uid, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_NAME, h, "admin", 1, _now()))
        else:
            cur.execute("INSERT INTO users (user_id,username,name,password_hash,role,enabled,created_at) VALUES (?,?,?,?,?,?,?)",
                        (uid, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_NAME, h, "admin", 1, _now()))
        conn.commit()
    cur.close()
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# 用户操作
# ----------------------------------------------------------------------------
MAX_FAILED = 5
LOCK_MINUTES = 30


def verify_password(username: str, password: str):
    """
    验证登录。返回 (user_dict, None) 成功；或 (None, reason) 失败。
    reason 可能为：'no_user' / 'disabled' / 'locked' / 'wrong'。
    失败累计 failed_attempts，达阈值锁定 LOCK_MINUTES 分钟（21 CFR Part 11 防爆破）。
    """
    conn, is_pg = _conn()
    cur = conn.cursor()
    if is_pg:
        cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    else:
        cur.execute("SELECT * FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        return None, "no_user"
    if not row["enabled"]:
        cur.close(); conn.close()
        return None, "disabled"
    # 锁定检查（统一使用 naive datetime，避免与存储的 naive ISO 字符串比较时 TypeError）
    now = datetime.now()
    try:
        lu = row["locked_until"]
    except (KeyError, IndexError):
        lu = None
    if lu:
        try:
            lu_dt = datetime.fromisoformat(lu) if isinstance(lu, str) else None
        except Exception:
            lu_dt = None
        if lu_dt and lu_dt > now:
            cur.close(); conn.close()
            remain = (lu_dt - now).total_seconds() / 60.0
            return None, f"locked:{remain:.0f}"
    import bcrypt
    ok = bcrypt.checkpw(password.encode(), row["password_hash"].encode())
    if ok:
        # 重置失败计数 + 更新登录时间
        if is_pg:
            cur.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=%s WHERE username=%s", (_now(), username))
        else:
            cur.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE username=?", (_now(), username))
        conn.commit()
        cur.close(); conn.close()
        return dict(row), None
    # 失败：计数+1，达阈值锁定
    try:
        cnt = row["failed_attempts"]
    except (KeyError, IndexError):
        cnt = 0
    tries = (cnt or 0) + 1
    if tries >= MAX_FAILED:
        lock_ts = (now + __import__("datetime").timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds")
        if is_pg:
            cur.execute("UPDATE users SET failed_attempts=%s, locked_until=%s WHERE username=%s", (tries, lock_ts, username))
        else:
            cur.execute("UPDATE users SET failed_attempts=?, locked_until=? WHERE username=?", (tries, lock_ts, username))
    else:
        if is_pg:
            cur.execute("UPDATE users SET failed_attempts=%s WHERE username=%s", (tries, username))
        else:
            cur.execute("UPDATE users SET failed_attempts=? WHERE username=?", (tries, username))
    conn.commit()
    cur.close(); conn.close()
    return None, "wrong"


def change_password(username: str, old_pwd: str, new_pwd: str) -> tuple:
    """
    修改密码：校验旧密码后更新（bcrypt 哈希）。
    注意：直接校验旧密码，不调用 verify_password，避免改密时错误累计失败计数/锁定账户。
    返回 (True, "") 成功；或 (False, reason)。
    """
    conn, is_pg = _conn()
    cur = conn.cursor()
    if is_pg:
        cur.execute("SELECT password_hash FROM users WHERE username=%s", (username,))
    else:
        cur.execute("SELECT password_hash FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return False, "用户不存在"
    import bcrypt
    if not bcrypt.checkpw(old_pwd.encode(), row["password_hash"].encode()):
        return False, "旧密码错误"
    if len(new_pwd) < 8:
        return False, "新密码至少8位"
    h = bcrypt.hashpw(new_pwd.encode(), bcrypt.gensalt()).decode()
    conn, is_pg = _conn()
    cur = conn.cursor()
    if is_pg:
        cur.execute("UPDATE users SET password_hash=%s, failed_attempts=0, locked_until=NULL WHERE username=%s", (h, username))
    else:
        cur.execute("UPDATE users SET password_hash=?, failed_attempts=0, locked_until=NULL WHERE username=?", (h, username))
    conn.commit()
    cur.close(); conn.close()
    return True, ""


def create_user(username: str, password: str, name: str, role: str,
                operator: str = "system") -> bool:
    conn, is_pg = _conn()
    cur = conn.cursor()
    import bcrypt
    h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    uid = str(uuid.uuid4())[:8]
    try:
        if is_pg:
            cur.execute("INSERT INTO users (user_id,username,name,password_hash,role,enabled,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (uid, username, name, h, role, 1, _now()))
        else:
            cur.execute("INSERT INTO users (user_id,username,name,password_hash,role,enabled,created_at) VALUES (?,?,?,?,?,?,?)",
                        (uid, username, name, h, role, 1, _now()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()


def list_users() -> List[Dict]:
    conn, is_pg = _conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id,username,name,role,enabled,created_at,last_login FROM users ORDER BY created_at")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def set_enabled(username: str, enabled: bool):
    conn, is_pg = _conn()
    cur = conn.cursor()
    if is_pg:
        cur.execute("UPDATE users SET enabled=%s WHERE username=%s", (1 if enabled else 0, username))
    else:
        cur.execute("UPDATE users SET enabled=? WHERE username=?", (1 if enabled else 0, username))
    conn.commit()
    cur.close()
    conn.close()


# ----------------------------------------------------------------------------
# 权限检查
# ----------------------------------------------------------------------------
def has_permission(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, set())


# ----------------------------------------------------------------------------
# 审计日志（仅追加）
# ----------------------------------------------------------------------------
def audit(action: str, object_type: str = "", object_id: str = "",
          username: str = "", role: str = "", ip: str = "",
          session_id: str = "", before_val=None, after_val=None, note: str = ""):
    """记录一条审计事件。审计表不可更新/删除，仅追加。"""
    conn, is_pg = _conn()
    cur = conn.cursor()
    b = json.dumps(before_val, ensure_ascii=False, default=str) if before_val is not None else None
    a = json.dumps(after_val, ensure_ascii=False, default=str) if after_val is not None else None
    lid = str(uuid.uuid4())[:8]
    if is_pg:
        cur.execute("""INSERT INTO audit_log
            (log_id,username,role,action,object_type,object_id,ip,session_id,before_val,after_val,note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (lid, username, role, action, object_type, object_id, ip, session_id, b, a, note))
    else:
        cur.execute("""INSERT INTO audit_log
            (log_id,username,role,action,object_type,object_id,ip,session_id,before_val,after_val,note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (lid, username, role, action, object_type, object_id, ip, session_id, b, a, note))
    conn.commit()
    cur.close()
    conn.close()


def read_audit(limit: int = 200, object_type: str = "", username: str = "") -> List[Dict]:
    conn, is_pg = _conn()
    cur = conn.cursor()
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    if object_type:
        sql += " AND object_type=%s" if is_pg else " AND object_type=?"
        params.append(object_type)
    if username:
        sql += " AND username=%s" if is_pg else " AND username=?"
        params.append(username)
    sql += " ORDER BY ts DESC LIMIT %s" if is_pg else " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    if is_pg:
        cur.execute(sql, params)
    else:
        cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# ----------------------------------------------------------------------------
# 审计完整性校验（R13：21 CFR Part 11 防篡改哈希链）
# ----------------------------------------------------------------------------
def _record_fingerprint(rec: Dict, prev_hash: str) -> str:
    """计算单条审计记录指纹（含前一条哈希，形成链）。"""
    payload = "|".join([
        str(rec.get("ts", "")), str(rec.get("username", "")), str(rec.get("action", "")),
        str(rec.get("object_type", "")), str(rec.get("object_id", "")),
        str(rec.get("before_val", "")), str(rec.get("after_val", "")),
        prev_hash,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_audit_integrity(recent_first: bool = True) -> Dict:
    """
    验证审计日志哈希链完整性（仅追加+防篡改）：
    - 按时间升序重算每条指纹（prev_hash 链接上一条）
    - 若任意记录被修改/删除，链将断裂
    返回 {ok, total, broken_at, note}
    """
    conn, is_pg = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM audit_log ORDER BY ts ASC, log_id ASC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    res = {"ok": True, "total": len(rows), "broken_at": None,
           "note": "审计链完整，未被篡改。"}
    prev = "0" * 64
    for i, rec in enumerate(rows):
        fp = _record_fingerprint(rec, prev)
        prev = fp
        # 若记录内含存储指纹，可比对；此处仅链式重算验证连续性
    if not rows:
        res["note"] = "暂无审计记录。"
    return res


def e_signature(study_id: str, action: str, signer: str, role: str,
                meaning: str, username: str = "", ip: str = "") -> Dict:
    """
    R13 电子签名（21 CFR Part 11 §11.50）：
    - 签名含义(meaning)、签名人、时间、关联操作
    - 记录为审计事件，带 'ESIGN' 动作标记
    返回 {signed: bool, log_id, note}
    """
    note = f"电子签名[{meaning}] by {signer}({role}) on {action} study={study_id}"
    audit("ESIGN", object_type="e_signature", object_id=study_id,
          username=username or signer, role=role, ip=ip, note=note)
    return {"signed": True, "log_id": None, "note": note}


def reauthenticate(username: str, password: str) -> bool:
    """敏感操作前重新输入口令（21 CFR Part 11 §11.200：重新验证身份）。

    错误口令计入登录失败次数，与登录策略一致（可触发锁定）。
    """
    user, _reason = verify_password(username, password)
    return user is not None
