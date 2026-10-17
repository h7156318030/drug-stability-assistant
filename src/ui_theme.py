"""界面主题与通用组件。

样式集中在本模块，便于统一调整颜色与间距。所有样式都是纯 CSS，
不依赖第三方前端库，也不加载外部字体（使用系统字体栈，中英文均可显示）。

颜色 token（与 .streamlit/config.toml 保持一致）：
    primary   #0F766E  主色（青绿，用于按钮、指标数值、标题强调）
    accent    #0369A1  辅助色（链接、次要强调）
    ink       #0F172A  正文
    muted     #64748B  说明文字
    line      #E2E8F0  边框
    surface   #F8FAFC  页面底色（浅色模式）
"""

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from i18n import t

APP_TITLE = "药品稳定性研究管理系统"
PAGE_ICON = "💊"

_CSS = """
:root {
  --sb-primary: #0F766E;
  --sb-accent: #0369A1;
  --sb-ink: #0F172A;
  --sb-muted: #64748B;
  --sb-line: #E2E8F0;
  --sb-surface: #F8FAFC;
  --sb-radius: 14px;
  --sb-shadow: 0 1px 2px rgba(15, 23, 42, 0.05), 0 4px 12px rgba(15, 23, 42, 0.04);
}
html, body, [class*="css"], .stApp {
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans SC",
               "Segoe UI", system-ui, -apple-system, sans-serif;
}
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1240px; }

/* 标题 */
h1 { letter-spacing: -0.02em; color: var(--sb-ink); }
h2 {
  color: var(--sb-ink); font-weight: 700; letter-spacing: -0.01em;
  border-left: 4px solid var(--sb-primary); padding-left: 0.6rem; margin-top: 0.4rem;
}
h3 { color: var(--sb-ink); font-weight: 650; }
[data-testid="stCaptionContainer"], .stCaption { color: var(--sb-muted); }

/* 侧边栏 */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #F0FDFA 0%, #F8FAFC 55%, #F8FAFC 100%);
  border-right: 1px solid var(--sb-line);
}
[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { padding-top: 0.6rem; }
.sb-brand {
  display: flex; align-items: center; gap: 0.7rem;
  padding: 0.4rem 0.2rem 0.9rem 0.2rem; margin-bottom: 0.4rem;
  border-bottom: 1px solid var(--sb-line);
}
.sb-brand-logo {
  width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center;
  justify-content: center; font-size: 22px;
  background: linear-gradient(135deg, #14B8A6 0%, #0F766E 100%);
  box-shadow: 0 4px 10px rgba(15, 118, 110, 0.28);
}
.sb-brand-name { font-weight: 750; color: var(--sb-ink); line-height: 1.2; font-size: 1.02rem; }
.sb-brand-sub { color: var(--sb-muted); font-size: 0.74rem; letter-spacing: 0.02em; }
.sb-user {
  background: #FFFFFF; border: 1px solid var(--sb-line); border-radius: 12px;
  padding: 0.6rem 0.75rem; margin: 0.4rem 0 0.8rem 0; box-shadow: var(--sb-shadow);
}
.sb-user-name { font-weight: 650; color: var(--sb-ink); }
.sb-role {
  display: inline-block; margin-top: 0.25rem; padding: 0.12rem 0.55rem; border-radius: 999px;
  font-size: 0.74rem; font-weight: 600; color: #0F766E; background: #CCFBF1;
}
[data-testid="stSidebar"] [role="radiogroup"] > label {
  border-radius: 10px; padding: 0.35rem 0.6rem; margin: 1px 0; transition: background 0.15s;
}
[data-testid="stSidebar"] [role="radiogroup"] > label:hover { background: rgba(15, 118, 110, 0.08); }

/* 指标卡片 */
[data-testid="stMetric"] {
  background: #FFFFFF; border: 1px solid var(--sb-line); border-radius: var(--sb-radius);
  padding: 0.9rem 1.1rem; box-shadow: var(--sb-shadow);
}
[data-testid="stMetricLabel"] p { color: var(--sb-muted); font-weight: 600; font-size: 0.85rem; }
[data-testid="stMetricValue"] { color: var(--sb-primary); font-weight: 750; }

/* 容器、表单、折叠面板、提示框 */
[data-testid="stExpander"] {
  border: 1px solid var(--sb-line) !important; border-radius: var(--sb-radius) !important;
  background: #FFFFFF; box-shadow: var(--sb-shadow);
}
[data-testid="stForm"] {
  border: 1px solid var(--sb-line); border-radius: var(--sb-radius); background: #FFFFFF;
  box-shadow: var(--sb-shadow); padding: 1rem 1.1rem;
}
[data-testid="stAlert"] { border-radius: 12px; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid var(--sb-line); }
hr { border-color: var(--sb-line); }

/* 按钮与输入 */
.stButton > button, .stDownloadButton > button {
  border-radius: 10px; font-weight: 600; border: 1px solid #CBD5E1;
  transition: transform 0.08s ease, box-shadow 0.15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--sb-primary); color: var(--sb-primary);
  box-shadow: 0 2px 8px rgba(15, 118, 110, 0.15);
}
.stButton > button:active { transform: translateY(1px); }
[data-baseweb="input"] > div, [data-baseweb="select"] > div, textarea {
  border-radius: 10px !important;
}

/* 标签页 */
[data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--sb-line); }
[data-baseweb="tab"] { border-radius: 10px 10px 0 0; font-weight: 600; }
[data-baseweb="tab"][aria-selected="true"] { color: var(--sb-primary) !important; }

/* 页面组件 */
.sb-hero {
  border-radius: 18px; padding: 1.1rem 1.4rem; margin: 0 0 1.1rem 0;
  background: linear-gradient(120deg, #0F766E 0%, #0EA5A4 55%, #0369A1 100%);
  color: #F0FDFA; box-shadow: 0 8px 24px rgba(15, 118, 110, 0.22);
}
.sb-hero h3 { color: #FFFFFF; margin: 0; font-size: 1.25rem; font-weight: 700; }
.sb-hero p { margin: 0.25rem 0 0 0; opacity: 0.92; font-size: 0.9rem; }
.sb-login-brand { text-align: center; margin: 0.5rem 0 1.2rem 0; }
.sb-login-brand .sb-brand-logo { margin: 0 auto 0.6rem auto; width: 64px; height: 64px; font-size: 34px; }
.sb-login-brand h1 { font-size: 1.7rem; margin: 0; }
.sb-login-brand p { color: var(--sb-muted); margin: 0.35rem 0 0 0; font-size: 0.9rem; }
.sb-footer { color: var(--sb-muted); font-size: 0.78rem; margin-top: 2rem; text-align: center; }

/* 窄屏 */
@media (max-width: 760px) {
  .block-container { padding-left: 1rem; padding-right: 1rem; }
}
"""


# 图表配色（与主题一致的色盘；色盲友好的深色为主）
CHART_COLORWAY = ["#0F766E", "#0369A1", "#F59E0B", "#DC2626", "#7C3AED", "#059669", "#DB2777", "#64748B"]

pio.templates["stability"] = go.layout.Template(
    layout=dict(
        colorway=CHART_COLORWAY,
        font=dict(family="Microsoft YaHei, PingFang SC, Noto Sans SC, Segoe UI, sans-serif", color="#0F172A"),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(gridcolor="#E2E8F0", zerolinecolor="#CBD5E1"),
        yaxis=dict(gridcolor="#E2E8F0", zerolinecolor="#CBD5E1"),
        legend=dict(bgcolor="rgba(255,255,255,0.8)"),
    )
)
pio.templates.default = "stability"


def setup_page() -> None:
    """页面基础设置。必须是脚本中第一个 Streamlit 调用。"""
    st.set_page_config(page_title=APP_TITLE, page_icon=PAGE_ICON, layout="wide",
                       initial_sidebar_state="expanded")


def inject_css() -> None:
    """注入全局样式（每次运行调用一次，开销很小）。"""
    st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


def sidebar_brand(user_name: str, role_label: str) -> None:
    """侧边栏品牌区与当前用户卡片。"""
    st.sidebar.markdown(
        '<div class="sb-brand">'
        '<div class="sb-brand-logo">💊</div>'
        f'<div><div class="sb-brand-name">{_esc(t("稳定性研究系统"))}</div>'
        '<div class="sb-brand-sub">Stability Study Manager</div></div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.sidebar.markdown(
        f'<div class="sb-user"><div class="sb-user-name">{_esc(user_name)}</div>'
        f'<span class="sb-role">{_esc(role_label)}</span></div>',
        unsafe_allow_html=True,
    )


def login_brand() -> None:
    """登录页品牌区（居中）。"""
    st.markdown(
        '<div class="sb-login-brand">'
        '<div class="sb-brand-logo">💊</div>'
        f'<h1>{_esc(t(APP_TITLE))}</h1>'
        f'<p>{_esc(t("登录后使用"))} &nbsp;|&nbsp; {_esc(t("多用户权限 · 审计追踪 · 21 CFR Part 11 设计参考"))}</p>'
        '</div>',
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str = "") -> None:
    """页面顶部横幅（用于重要页面的概要说明）。"""
    sub = f"<p>{_esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f'<div class="sb-hero"><h3>{_esc(title)}</h3>{sub}</div>', unsafe_allow_html=True)


def footer() -> None:
    st.markdown(f'<div class="sb-footer">{_esc(t("研究辅助工具，未经 GxP 验证"))}</div>',
                unsafe_allow_html=True)


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
