"""界面国际化：中文为源语言，英文译文位于 i18n_en.py（键为中文原文）。

用法::

    from i18n import t
    st.header(t("研究管理"))                 # 按当前语言返回文本
    st.success(t("共{0}条").format(n))       # 含占位符的模板

语言由 app.py 在每次运行时通过 set_language() 设置。状态保存在线程局部变量中，
Streamlit 为每个会话使用独立线程执行脚本，因此不同会话的语言互不影响。
译文缺失时回退为中文原文，因此新增界面文字不会导致页面报错。
"""

import threading

from i18n_en import EN

SUPPORTED = {"zh": "中文", "en": "English"}
DEFAULT_LANGUAGE = "zh"

_local = threading.local()


def set_language(lang: str) -> None:
    """设置当前线程的界面语言（未知语言回退为中文）。"""
    _local.lang = lang if lang in SUPPORTED else DEFAULT_LANGUAGE


def get_language() -> str:
    return getattr(_local, "lang", DEFAULT_LANGUAGE)


def t(text: str) -> str:
    """返回 text 在当前语言下的显示文本；英文缺译时回退为原文。"""
    if get_language() == "en":
        return EN.get(text, text)
    return text
