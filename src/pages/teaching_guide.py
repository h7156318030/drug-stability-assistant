"""教学指南页面（由 app.py 拆分而来）。"""

import sys
import streamlit as st
from i18n import t


def render(ctx):
    st.header(t("📚 稳定性研究教学指南 (学习模式)"))
    st.caption(t("本页提供法规术语、阶段合规清单与常见误区，供学习与方案自查。法规依据：ICH Q1A/Q1E/Q1D/Q5C/Q6B、NMPA 生物制品指导原则、21 CFR Part 11、USP <1049>。"))
    import importlib
    if "src" not in sys.path:
        sys.path.insert(0, "src")
    T = importlib.import_module("teaching")
    tab_g, tab_c, tab_p, tab_q = st.tabs([t("术语表"), t("阶段合规清单"), t("常见误区"), t("自测题")])
    with tab_g:
        q = st.text_input(t("搜索术语"), "")
        items = {k: v for k, v in T.GLOSSARY.items() if not q or q.lower() in k.lower() or q.lower() in v.lower()}
        for k, v in items.items():
            st.markdown(t("**{0}**：{1}").format(t(k), t(v)))
    with tab_c:
        stage_sel = st.selectbox(t("选择开发阶段"), list(T.CHECKLISTS.keys()), format_func=t)
        chk = T.checklist_for(stage_sel)
        # R23：可勾选交互 + 完成度
        done_key = f"chk_{stage_sel}"
        if done_key not in st.session_state:
            st.session_state[done_key] = set()
        cols = st.columns(2)
        for i, item in enumerate(chk, 1):
            checked = st.checkbox(f"{i}. {t(item)}", value=(i in st.session_state[done_key]), key=f"c_{stage_sel}_{i}")
            if checked:
                st.session_state[done_key].add(i)
            else:
                st.session_state[done_key].discard(i)
        total = len(chk)
        done = len(st.session_state[done_key])
        st.progress(done / total if total else 0)
        st.caption(t("完成度：{0}/{1}（勾选项仅会话内有效，用于自查练习）").format(done, total))
        st.info(t("提示：在研究管理中创建研究时选择对应临床阶段，可在『生物CQA』页对照本清单自查。"))
    with tab_p:
        for i, item in enumerate(T.PITFALLS, 1):
            st.markdown(f"{i}. {t(item)}")
    # R40：常见误区自测 quiz
    with tab_q:
        st.caption(t("自测题（仅学习用，勾选后显示答案与解析）："))
        for i, q in enumerate(T.QUIZ):
            st.subheader(f"Q{i+1}. {t(q['q'])}")
            choice = st.radio(t("选择"), q["options"], key=f"quiz_{i}", format_func=t)
            if st.button(t("显示答案 Q{0}").format(i+1), key=f"qa_{i}"):
                correct = (choice.startswith(q["answer"]))
                if correct:
                    st.success(t("✅ 正确！答案：{0}。{1}").format(q['answer'], t(q['explain'])))
                else:
                    st.error(t("❌ 错误。正确答案：{0}。{1}").format(q['answer'], t(q['explain'])))
