# Contributing / 贡献指南

[中文](#中文) | [English](#english)

## English

Thank you for helping. Quick start:

1. Python 3.9+. Install dependencies: `python -m pip install -r requirements.txt`.
2. Run the tests: `python -X utf8 -m unittest discover -s tests -p "suite_*.py"`.
   Each test script uses its own temporary data directory and never touches your `stability.db`.
3. Start a development instance with a scratch data directory:
   `STAB_DATA_DIR=scratch_data streamlit run app.py`.

Ground rules:

- Every change to calculations (regression, shelf life, Q1E/Q5C logic) needs a test with expected values
  that can be checked by hand or against an independent tool. Say which reference you used.
- Do not weaken the audit log, the e-signature (password re-entry) or access control without an issue
  for discussion first.
- Do not add default passwords, credentials, tokens or production data to the repository.
- Regulatory statements in docs must cite the source and its verification status (see `docs/*/regulatory_basis.md`).
- Keep user-facing text bilingual where practical; the application UI is currently Chinese only.

## 中文

感谢你的贡献。快速开始：

1. Python 3.9+，安装依赖：`python -m pip install -r requirements.txt`。
2. 运行测试：`python -X utf8 -m unittest discover -s tests -p "suite_*.py"`。
   每个测试脚本都使用独立的临时数据目录，不会改动你的 `stability.db`。
3. 使用独立数据目录启动开发实例：`STAB_DATA_DIR=scratch_data streamlit run app.py`。

基本规则：

- 任何计算逻辑（回归、有效期、Q1E/Q5C 相关）的改动，都需要带有可人工核对或与独立工具对照的预期值测试，并说明参照来源。
- 未经事先讨论，不得削弱审计日志、电子签名（口令复核）或权限控制。
- 不得在仓库中加入默认口令、凭据、令牌或生产数据。
- 文档中的法规表述须注明来源与核对状态（见 `docs/*/法规依据.md` 与 `regulatory_basis.md`）。
- 面向用户的文字尽量双语；应用界面目前仅为中文。
