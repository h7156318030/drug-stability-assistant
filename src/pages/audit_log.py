"""审计日志页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import auth as AU


def render(ctx):
    st.header(t("🛡 审计日志 (21 CFR Part 11)"))
    st.caption(t("审计记录仅追加、不可修改/删除，包含操作人、时间(UTC)、IP、会话、前/后值。"))
    logs = AU.read_audit(limit=2000)
    if logs:
        df = pd.DataFrame(logs)
        # 筛选
        users = ["全部"] + sorted(df["username"].unique().tolist())
        actions = ["全部"] + sorted(df["action"].unique().tolist())
        c1, c2 = st.columns(2)
        fu = c1.selectbox(t("按用户筛选"), users)
        fa = c2.selectbox(t("按动作筛选"), actions)
        df_f = df.copy()
        if fu != "全部":
            df_f = df_f[df_f["username"] == fu]
        if fa != "全部":
            df_f = df_f[df_f["action"] == fa]
        show_cols = ["ts", "username", "role", "action", "object_type", "object_id", "ip", "note"]
        show_cols = [c for c in show_cols if c in df_f.columns]
        st.dataframe(df_f[show_cols], width='stretch')
        # 导出 CSV
        csv = df_f[show_cols].to_csv(index=False).encode("utf-8-sig")
        st.download_button(t("导出筛选后审计日志 (CSV)"), csv, "audit_log.csv", "text/csv")
        # R13：审计完整性校验（防篡改哈希链）
        if st.button(t("🔐 校验审计链完整性 (21 CFR Part 11)")):
            integ = AU.verify_audit_integrity()
            if integ["ok"]:
                st.success(t("✅ 审计链完整：共 {0} 条记录，未检测到篡改。").format(integ['total']))
            else:
                st.error(t("❌ 审计链在记录 {0} 处断裂，疑似被篡改！").format(integ['broken_at']))
        with st.expander(t("查看某条记录的前/后值(JSON)")):
            opts = [f'{l["ts"]} {l["username"]} {l["action"]}' for l in logs]
            idx = st.selectbox(t("选择记录"), opts)
            rec = next(l for l in logs if f'{l["ts"]} {l["username"]} {l["action"]}' == idx)
            st.json({"before": rec.get("before_val"), "after": rec.get("after_val")})
    else:
        st.info(t("暂无审计记录。"))


# ----------------------------------------------------------------------------
# 用户管理
# ----------------------------------------------------------------------------
