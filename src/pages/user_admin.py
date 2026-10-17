"""用户管理页面（由 app.py 拆分而来）。"""

import streamlit as st
from i18n import t
import pandas as pd
import auth as AU
from ui_common import check_perm


def render(ctx):
    user = ctx["user"]
    role = ctx["role"]

    st.header(t("👥 用户管理"))
    if not check_perm("user:manage"):
        st.error(t("权限不足：需 user:manage。"))
    else:
        with st.form("add_user"):
            nu = st.text_input(t("新用户名"))
            npw = st.text_input(t("初始密码"), type="password")
            nn = st.text_input(t("姓名"))
            nr = st.selectbox(t("角色"), [r for r in AU.ROLE_LABELS if r != "admin"] + ["admin"],
                             format_func=lambda r: t(AU.ROLE_LABELS.get(r, r)))
            reauth_new = st.text_input(t("请输入您的登录口令以确认（电子签名）"), type="password", key="reauth_newuser")
            if st.form_submit_button(t("创建用户")):
                if not AU.reauthenticate(user["username"], reauth_new):
                    st.error(t("口令错误，未创建用户。（错误次数计入锁定策略）"))
                elif AU.create_user(nu, npw, nn, nr, operator=user["username"]):
                    AU.audit("USER_CREATE", "user", nu, user["username"], role,
                             st.session_state.client_ip, st.session_state.session_id, note=f"role={nr}")
                    AU.e_signature(nu, "USER_CREATE", user.get("name") or user["username"], role,
                                   f"创建用户（角色={nr}）", username=user["username"],
                                   ip=st.session_state.client_ip)
                    st.success(t("已创建用户 {0}（{1}）").format(nu, AU.ROLE_LABELS.get(nr, nr)))
                else:
                    st.error(t("创建失败（用户名可能已存在）。"))
        st.subheader(t("现有用户"))
        us = AU.list_users()
        if us:
            df = pd.DataFrame(us)
            st.dataframe(df, width='stretch')
            dis = st.selectbox(t("禁用/启用用户"), [u["username"] for u in us if u["username"] != user["username"]])
            reauth_dis = st.text_input(t("请输入您的登录口令以确认禁用/启用（电子签名）"), type="password",
                                       key="reauth_enable")
            c1, c2 = st.columns(2)
            if c1.button(t("禁用")):
                if not AU.reauthenticate(user["username"], reauth_dis):
                    st.error(t("口令错误，未执行。（错误次数计入锁定策略）"))
                else:
                    AU.set_enabled(dis, False)
                    AU.audit("USER_DISABLE", "user", dis, user["username"], role,
                             st.session_state.client_ip, st.session_state.session_id)
                    AU.e_signature(dis, "USER_DISABLE", user.get("name") or user["username"], role,
                                   "禁用用户账户", username=user["username"], ip=st.session_state.client_ip)
                    st.rerun()
            if c2.button(t("启用")):
                if not AU.reauthenticate(user["username"], reauth_dis):
                    st.error(t("口令错误，未执行。（错误次数计入锁定策略）"))
                else:
                    AU.set_enabled(dis, True)
                    AU.audit("USER_ENABLE", "user", dis, user["username"], role,
                             st.session_state.client_ip, st.session_state.session_id)
                    AU.e_signature(dis, "USER_ENABLE", user.get("name") or user["username"], role,
                                   "启用用户账户", username=user["username"], ip=st.session_state.client_ip)
                    st.rerun()


# ----------------------------------------------------------------------------
# 系统维护（管理员）
# ----------------------------------------------------------------------------
