"""
matplotlib 中文字体配置，避免趋势图中文乱码。
优先使用系统 SimHei(黑体)，回退到常见中文字体。
"""

import os
import matplotlib

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def setup_chinese_font():
    """配置 matplotlib 使用支持中文的字体，返回是否成功"""
    for fp in _FONT_CANDIDATES:
        if os.path.exists(fp):
            try:
                matplotlib.font_manager.fontManager.addfont(fp)
                name = matplotlib.font_manager.FontProperties(fname=fp).get_name()
                matplotlib.rcParams["font.family"] = name
                matplotlib.rcParams["axes.unicode_minus"] = False
                return True
            except Exception:
                continue
    # 回退：尝试常见字体名
    matplotlib.rcParams["font.family"] = ["SimHei", "Microsoft YaHei", "WenQuanYi Zen Hei", "sans-serif"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    return False
