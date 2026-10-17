"""界面国际化测试：语言切换、译文占位符一致性、英文界面无异常、页眉全部已译。

全部使用临时数据目录，不会改动正式的 stability.db。
"""
import sys, os, re, tempfile, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, ROOT)
os.environ['STAB_DATA_DIR'] = tempfile.mkdtemp(prefix='stab_i18n_')  # isolated DB
os.environ['STAB_ADMIN_PASSWORD'] = 'Test-Admin#2026'

import i18n
from i18n_en import EN

PASS, FAIL = [], []
CJK = re.compile(r"[一-鿿]")


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [XX] ") + name)


print("== 1. 语言切换")
i18n.set_language("zh")
check("默认/中文时返回原文", i18n.t("研究管理") == "研究管理")
i18n.set_language("en")
check("英文时返回译文", i18n.t("研究管理") == "Study management")
check("缺译时回退为原文", i18n.t("这是一个不存在的键") == "这是一个不存在的键")
i18n.set_language("fr")
check("未知语言回退为中文", i18n.get_language() == "zh")
i18n.set_language("zh")

print("== 2. 译文占位符与源文一致")
bad = []
for zh, en in EN.items():
    ph_zh = sorted(set(re.findall(r"\{\d+(?::[^}]*)?\}", zh)))
    ph_en = sorted(set(re.findall(r"\{\d+(?::[^}]*)?\}", en)))
    ph_zh = [re.sub(r":.*", "", x) for x in ph_zh]
    ph_en = [re.sub(r":.*", "", x) for x in ph_en]
    if ph_zh != ph_en:
        bad.append(zh[:30])
check(f"所有译文占位符与中文原文一致 (不一致: {bad[:3]})", not bad)
check("译文表非空（至少 400 条）", len(EN) >= 400)

print("== 3. 英文界面：全部页面无异常，页眉无中文")
from streamlit.testing.v1 import AppTest
subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "seed_example.py")],
               capture_output=True, encoding="utf-8", errors="replace")
at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=180)
at.session_state["user"] = {"username": "admin", "name": "Admin", "role": "admin"}
at.session_state["lang"] = "en"
i18n.set_language("en")  # AppTest evaluates format_func in the test thread
at.run()
check("英文登录后首页无异常", len(at.exception) == 0)
pages = list(at.sidebar.radio[0].options)
exc_pages, cjk_headers = [], []
for p in pages:
    at.sidebar.radio[0].set_value(p).run()
    if at.exception:
        exc_pages.append((p, at.exception[0].value[:80]))
    for h in at.header:
        if CJK.search(h.value):
            cjk_headers.append((p, h.value[:40]))
check(f"英文模式下 {len(pages)} 个页面无异常 (失败: {exc_pages})", not exc_pages)
check(f"英文模式下页眉全部已译 (未译: {cjk_headers[:3]})", not cjk_headers)
check("英文导航菜单可见", "Dashboard" in pages and "Study management" in pages)
i18n.set_language("zh")

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    sys.exit(1)
print("全部通过")
