"""
药品稳定性研究管理与分析系统 —— Streamlit 应用入口（含登录鉴权 + 审计）

运行：
    pip install -r requirements.txt
    python tools/seed_example.py      # 可选：示例数据
    streamlit run app.py
访问： http://localhost:8501

多用户 / 权限 / 21 CFR Part 11：
    - 首次启动自动创建管理员 admin；口令取自环境变量 STAB_ADMIN_PASSWORD，
      未设置时在控制台输出一次性随机口令（登录后请立即修改）
    - 数据目录：环境变量 STAB_DATA_DIR（默认项目根目录，即 stability.db 所在处）
    - 后端可切换 PostgreSQL：设置环境变量 DATABASE_URL=postgresql://...
    - 所有写操作记录不可篡改审计日志（操作人/时间/IP/前后值）
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import streamlit as st
from i18n import t


import db as DB
import fonts as F
import auth as AU
import ui_theme as UI
from i18n import t, SUPPORTED, set_language
from ui_common import check_perm, client_ip
from pages import (
    dashboard,
    study_management,
    data_entry,
    trend_analysis,
    shelf_life,
    cross_comparison,
    quality_alerts,
    biologic_cqa,
    photostability,
    statistics_summary,
    export_reports,
    design_advice,
    comparability,
    audit_log,
    user_admin,
    maintenance,
    teaching_guide,
)

UI.setup_page()   # 必须是第一个 Streamlit 调用
UI.inject_css()

# 界面语言：会话级设置（默认中文），在每次运行开始时应用到当前线程
if "lang" not in st.session_state:
    st.session_state.lang = "zh"
set_language(st.session_state.lang)


def language_picker(key: str) -> None:
    """语言切换下拉框；切换后立即重新运行以刷新全部界面文字。"""
    options = list(SUPPORTED)
    choice = st.selectbox(t("语言"), options, index=options.index(st.session_state.lang),
                          format_func=lambda k: SUPPORTED[k], key=key)
    if choice != st.session_state.lang:
        st.session_state.lang = choice
        set_language(choice)
        st.rerun()

F.setup_chinese_font()
DB.init()
AU.init_auth()


# ----------------------------------------------------------------------------
# 会话初始化
# ----------------------------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "session_id" not in st.session_state:
    st.session_state.session_id = os.urandom(8).hex()
if "client_ip" not in st.session_state:
    st.session_state.client_ip = client_ip()


# ----------------------------------------------------------------------------
# 登录页
# ----------------------------------------------------------------------------
def login_page():
    UI.login_brand()
    language_picker("lang_login")
    with st.form("login"):
        u = st.text_input(t("用户名"))
        p = st.text_input(t("密码"), type="password")
        if st.form_submit_button(t("登录")):
            user, reason = AU.verify_password(u, p)
            if user:
                st.session_state.user = dict(user)
                AU.audit("LOGIN", "session", "", u, user["role"],
                         st.session_state.client_ip, st.session_state.session_id, note="登录成功")
                st.rerun()
            else:
                msg = t("用户名或密码错误，或账户已禁用。")
                if reason and reason.startswith("locked"):
                    msg = t("账户已锁定，请 {0} 分钟后再试。").format(reason.split(":")[1])
                elif reason == "no_user":
                    msg = t("用户名不存在。")
                elif reason == "disabled":
                    msg = t("账户已禁用，请联系管理员。")
                st.error(msg)


if not st.session_state.user:
    login_page()
    st.stop()


user = st.session_state.user
# 防御：任何导致 user 为 None 的路径（如会话失效/裸导入）不至于整页 TypeError 崩溃白屏
if not user:
    st.stop()  # 真实 streamlit 下终止脚本
role = user["role"] if user else "viewer"  # 裸模式 st.stop 不生效时仍有默认，避免崩溃
name = user.get("name", "") if user else ""
uname = user.get("username", "") if user else ""


# ----------------------------------------------------------------------------
# 侧边栏导航
# ----------------------------------------------------------------------------
UI.sidebar_brand(name, t(AU.ROLE_LABELS.get(role, role)))
language_picker("lang_sidebar")
if st.sidebar.button(t("退出登录")):
    AU.audit("LOGOUT", "session", "", uname, role,
             st.session_state.client_ip, st.session_state.session_id, note="退出登录")
    st.session_state.user = None
    st.rerun()
if role == "admin":
    st.sidebar.caption(t("⚠ 若仍在使用初始口令，请立即在下方『修改密码』中更换。"))

with st.sidebar.expander(t("🔑 修改密码")):
    old_p = st.text_input(t("当前密码"), type="password", key="oldp")
    new_p = st.text_input(t("新密码(≥8位)"), type="password", key="newp")
    if st.button(t("更新密码")):
        ok, why = AU.change_password(user["username"], old_p, new_p)
        if ok:
            AU.audit("PWD_CHANGE", "user", user["username"], user["username"], role,
                     st.session_state.client_ip, st.session_state.session_id)
            st.success(t("密码已更新。"))
        else:
            st.error(t("修改失败：{0}").format(why))

nav_options = ["仪表盘", "研究管理", "数据录入", "分析与时序图", "有效期推算", "横向比较", "质量告警", "生物CQA", "光稳定性", "统计汇总", "导出报告", "设计建议", "教学指南", "可比性"]
if check_perm("audit:read"):
    nav_options.append("审计日志")
if check_perm("user:manage"):
    nav_options.append("用户管理")
if user and user.get("role") == "admin":
    nav_options.append("系统维护")
page = st.sidebar.radio(t("导航"), nav_options, format_func=t)

studies = DB.list_studies()


# ----------------------------------------------------------------------------
# 页面分发（各页面位于 src/pages/，见 docs/zh/架构与测试.md）
# ----------------------------------------------------------------------------
ctx = {"user": user, "role": role, "name": name, "uname": uname, "studies": studies}
PAGE_RENDERERS = {
    "仪表盘": dashboard.render,
    "研究管理": study_management.render,
    "数据录入": data_entry.render,
    "分析与时序图": trend_analysis.render,
    "有效期推算": shelf_life.render,
    "横向比较": cross_comparison.render,
    "质量告警": quality_alerts.render,
    "生物CQA": biologic_cqa.render,
    "光稳定性": photostability.render,
    "统计汇总": statistics_summary.render,
    "导出报告": export_reports.render,
    "设计建议": design_advice.render,
    "可比性": comparability.render,
    "审计日志": audit_log.render,
    "用户管理": user_admin.render,
    "系统维护": maintenance.render,
    "教学指南": teaching_guide.render,
}
PAGE_RENDERERS[page](ctx)

UI.footer()
