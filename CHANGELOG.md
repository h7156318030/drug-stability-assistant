# Changelog / 更新日志

## Unreleased — 2026-10-17 · Repository reorganisation / 仓库重组

**English**

- Reorganised the project for public release: documentation is now bilingual (`README.md` 中文 / `README_en.md` English; `docs/zh/` and `docs/en/`). Version notes, handoff notes and build logs were consolidated into this changelog and archived outside the repository.
- **Security**: removed the hard-coded default administrator password (`Admin@2026`) from the code and documentation. The initial password now comes from `STAB_ADMIN_PASSWORD`, or is generated randomly and printed once to the console.
- **Data isolation**: added `STAB_DATA_DIR`. Test scripts previously ignored the variable they set (`STAB_DB_DIR`) and wrote test studies into the live database; they now use a temporary directory.
- Removed a dead legacy JSON storage layer from `src/models.py` (superseded by SQLite in `src/db.py`).
- Fixed a `log(0)` warning in model selection when a fit is exact (`src/analysis.py`).
- `requirements.txt`: added the missing `plotly` dependency; PostgreSQL driver marked optional.
- Layout: tests in `tests/` (runnable via `python tests/run_all.py`); tools in `tools/` (`seed_example.py`, `backup.py`).
- Licence: Apache License 2.0 (`LICENSE`), with `NOTICE`, `CONTRIBUTING.md` and `SECURITY.md`. Git repository initialised (no commit yet).
- Continuous integration: `.github/workflows/test.yml` runs the test suite on Python 3.9 and 3.11; `tests/suite_scripts.py` wraps every test script as a unittest case.
- Electronic signature: deleting a study and restoring a backup now require re-entering the login password (`AU.reauthenticate`); the signing event is recorded in the audit log (`ESIGN`). Wrong passwords count toward the lockout policy.
- Administrators see a reminder in the sidebar to change the initial password.
- Regulatory references were checked against public sources; unverified items are marked in `docs/*/regulatory_basis.md`.
- Tests for the new re-authentication helper: `tests/test_reauth.py`.
- **Fixed (UI)**: on the study-management page, the study selector, delete, JSON import/export and "add sample" sections were nested inside the "load teaching examples" button, so they only appeared for the single run right after that button was clicked. They are now always shown. Covered by `tests/test_admin_flow.py`.
- **Fixed (seed tool)**: `tools/seed_example.py` failed on an empty database because measurements were not linked to their time points (foreign keys are enforced since V2.3). Covered by `tests/test_seed.py`.
- **Statistics (correction, needs statistical review)**: the shelf-life estimate now uses the one-sided 95% confidence bound of the regression line (ICH Q1E), not the prediction bound, which added an extra variance term and made results more conservative than Q1E describes. Shelf lives for existing studies will therefore be longer. Cross-checked against an independent implementation in `tests/test_functional.py`.
- **Fixed (statistics)**: for upper-limit attributes (e.g. related substances) the shelf life was reported as 0 because the start-of-study check used the lower-limit logic. The check is now direction-aware.
- **Fixed (pages)**: four pages raised exceptions in normal use: data entry (undefined template limits), expiry estimation (undefined condition list, and a formatting error on non-finite values), the analysis page (quality score expected a dict), and real-time entry validation (invalid argument). Found by the new page-sweep tests.
- **Changed**: the data-quality score is a heuristic (100 minus 5 per issue), labelled as internal and not a regulatory metric.
- **Refactor**: CSV bulk import moved to `src/importers.py`; UTF-8 and GBK files are accepted, and skipped rows are reported with reasons.
- **Interface**: new visual theme (`src/ui_theme.py`, `.streamlit/config.toml`): colour palette, metric cards, sidebar brand block, redesigned login page, branded Plotly template. Removed the Plotly keyword-argument deprecation warning.
- **Tests**: `tests/test_functional.py` (numerical cross-checks, all 11 templates, storage/audit/backup, exports, authentication, lockout, roles, CSV import) and `tests/test_ui_workflows.py` (login, role navigation, study → sample → data entry, teaching examples, user management, password change, every page for four roles). The old `tests/test_app_flow.py` smoke test was removed: it used hard-coded widget indexes and was superseded by the workflow tests.
- **Structure**: `app.py` is split into `src/ui_common.py` and 17 page modules in `src/pages/`; `app.py` is now a short entry point (about 150 lines).
- **Interface language**: Chinese / English switch (`src/i18n.py`, `src/i18n_en.py`). About 450 interface strings, the teaching content and domain terms are translated. Analysis narrative text, chart titles and Excel/PDF reports remain Chinese. `tests/test_i18n.py` checks that every English page renders and that all headers are translated.
- **PostgreSQL**: testing against PostgreSQL 16.2 found and fixed incompatibilities (SQLite-only upsert, PRAGMA-based migration, row handling for export, restore audit entry). `tests/test_postgres.py` runs when `STAB_TEST_PG_URL` is set.
- **Statistics (ICH Q1E)**: batch poolability now uses the Q1E ANCOVA procedure (slopes first, then intercepts; significance level 0.25). It replaces three different empirical rules. p-values are reported. Checked in `tests/test_statistics_benchmark.py` against independent calculations (16 checks). Needs statistical review.
- **Fixed**: the multi-model plot on the shelf-life page raised an error when testing an array's truth value.
- **Electronic signatures extended**: creating users, enabling or disabling users, and generating a full backup now require password re-entry and write `ESIGN` records.
- **One-click start (Windows)**: `start.bat` creates a private `.venv`, installs the pinned dependencies, starts the server and opens the browser. Dependency ranges are pinned to the tested majors. The full test suite passes in a fresh venv (Python 3.11, Streamlit 1.66).
- **Regulatory gap analysis**: `docs/en/gap_analysis.md` and `docs/zh/法规符合性差距分析.md` benchmark the program against ICH Q1A–Q1E, Q1B, Q1D, Q5C, Q2(R2)/Q14, Chinese guidance, 21 CFR Part 11 and ALCOA+, listing P0/P1/P2 gaps and items to verify against official texts.

**中文**

- 为公开发布重组项目：文档改为中英双语（`README.md` 中文 / `README_en.md` English；`docs/zh/` 与 `docs/en/`）。版本说明、交接文档和调试记录已合并到本更新日志，并移至仓库之外归档。
- **安全**：从代码与文档中移除了写死的默认管理员口令 `Admin@2026`。初始口令改为读取环境变量 `STAB_ADMIN_PASSWORD`，未设置时生成随机口令并在控制台输出一次。
- **数据隔离**：新增 `STAB_DATA_DIR`。原测试脚本设置的 `STAB_DB_DIR` 从未生效，测试研究记录会写入正式数据库；现在测试使用临时目录。
- 删除 `src/models.py` 中已被 SQLite 取代的旧 JSON 存储代码（`src/db.py` 为唯一存储层）。
- 修复模型选择中完美拟合时 `log(0)` 的运行警告（`src/analysis.py`）。
- `requirements.txt`：补充遗漏的 `plotly` 依赖；PostgreSQL 驱动标注为可选。
- 目录：测试位于 `tests/`（运行 `python tests/run_all.py`）；工具位于 `tools/`（`seed_example.py`、`backup.py`）。
- 法规依据已对照公开资料核查，未核实条目在 `docs/*/法规依据.md` 与 `regulatory_basis.md` 中标注。
- 许可证：Apache License 2.0（`LICENSE`），并新增 `NOTICE`、`CONTRIBUTING.md`、`SECURITY.md`。已初始化 git 仓库（尚未提交）。
- 持续集成：`.github/workflows/test.yml` 在 Python 3.9 与 3.11 上运行测试；`tests/suite_scripts.py` 将每个测试脚本封装为 unittest 用例。
- 电子签名：删除研究与恢复备份时需重新输入登录口令（`AU.reauthenticate`），签名事件写入审计日志（`ESIGN`）。口令错误计入锁定策略。
- 管理员在侧边栏会看到修改初始口令的提醒。
- 新增重新验证口令的测试：`tests/test_reauth.py`。
- **修复（界面）**：研究管理页中的“选择研究、删除、JSON 导入导出、添加样品”区块被嵌套在“加载教学示例”按钮内，只有点击该按钮的那一次刷新才会显示。现已恢复为常驻显示。由 `tests/test_admin_flow.py` 覆盖。
- **修复（示例工具）**：`tools/seed_example.py` 在空库上运行失败，因为检测值未与时间点关联（V2.3 起外键已启用）。由 `tests/test_seed.py` 覆盖。
- **统计修正（需统计人员复核）**：有效期推算改用回归直线的 95% 单侧置信限（ICH Q1E），不再使用预测限。原先的预测限多了一项方差，结果比 Q1E 的描述更保守。因此既有研究的有效期会变长。已由 `tests/test_functional.py` 中的独立实现对照。
- **修复（统计）**：上限类指标（如有关物质）的有效期被报告为 0，原因是“起点是否超限”的判断套用了下限逻辑。现已区分方向。
- **修复（页面）**：四个页面在正常使用时抛出异常：数据录入（模板限度变量未定义）、有效期推算（条件列表未定义，且非有限值格式化出错）、分析页（质量分期望字典）、录入实时校验（参数错误）。由新增的全页面扫描测试发现。
- **变更**：数据质量分为启发式（100 减去每个问题 5 分），标注为内部排查用途，不是法规指标。
- **重构**：CSV 批量导入迁移至 `src/importers.py`；支持 UTF-8 与 GBK，跳过的行会给出原因。
- **界面**：新视觉主题（`src/ui_theme.py`、`.streamlit/config.toml`）：配色、指标卡片、侧边栏品牌区、重新设计的登录页、统一的 Plotly 图表模板。消除了 Plotly 关键字参数弃用警告。
- **测试**：`tests/test_functional.py`（数值对照、全部 11 个模板、存储/审计/备份、导出、认证、锁定、角色、CSV 导入）与 `tests/test_ui_workflows.py`（登录、角色导航、研究→样品→录入、教学示例、用户管理、改口令、四个角色下的全部页面）。旧的 `tests/test_app_flow.py` 依赖硬编码的控件序号，已被工作流测试取代并删除。
- **结构**：`app.py` 拆分为 `src/ui_common.py` 与 `src/pages/` 下的 17 个页面模块；`app.py` 成为约 150 行的入口。
- **界面语言**：中文 / English 切换（`src/i18n.py`、`src/i18n_en.py`）。约 450 条界面文字、教学内容与领域术语已译。分析叙述文字、图表标题与 Excel/PDF 报告仍为中文。`tests/test_i18n.py` 检查英文模式下全部页面可渲染、页眉全部已译。
- **PostgreSQL**：在 PostgreSQL 16.2 上测试发现并修复了兼容性问题（仅 SQLite 支持的 upsert、基于 PRAGMA 的迁移、导出时的行处理、恢复审计记录）。设置 `STAB_TEST_PG_URL` 后运行 `tests/test_postgres.py`。
- **统计（ICH Q1E）**：批合并判断改用 Q1E 的 ANCOVA 检验（先斜率、再截距，显著性水平 0.25），替换了原先三处各不相同的经验规则，并输出 p 值。由 `tests/test_statistics_benchmark.py` 与独立计算对照（16 项）。需要统计人员复核。
- **修复**：有效期页的多模型图对数组做真值判断，导致报错。
- **电子签名扩展**：创建用户、启用或禁用用户、生成整库备份均需重新输入口令，并写入 `ESIGN` 记录。
- **一键启动（Windows）**：`start.bat` 自动创建独立的 `.venv`、安装锁定范围内的依赖、启动服务并打开浏览器。依赖范围已限定在测试过的主版本。完整测试在全新 venv（Python 3.11、Streamlit 1.66）中通过。
- **法规符合性差距分析**：`docs/zh/法规符合性差距分析.md` 与 `docs/en/gap_analysis.md` 对标 ICH Q1A–Q1E、Q1B、Q1D、Q5C、Q2(R2)/Q14、中国指导原则、21 CFR Part 11 与 ALCOA+，列出 P0/P1/P2 差距，并标注需对照官方原文核实的条目。

> **升级提示 / Upgrade note**: if an existing database still has the `admin` account with `Admin@2026`, log in and change the password. / 若现有数据库的 `admin` 账号仍使用 `Admin@2026`，请登录后立即修改。

---

## Version history / 版本历史

| Version | Date | Summary (EN) | 摘要（中文） |
|---------|------|--------------|--------------|
| V1.0 | 2026-08-06 | Baseline after 25 iterations | 25 轮迭代基线 |
| V2.0 | 2026-08-07 | Biologics module, regulatory gap closure, teaching mode | 生物制品专项、法规差距整改、教学版 |
| V2.1 | 2026-08-08 | Iterations R1–R50: features and performance | R1–R50 功能与性能迭代 |
| V2.2 | 2026-08-08 | Five rounds of test-and-fix hardening | 五轮测试与修复加固 |
| V2.3 | 2026-08-08 | Security and integrity hardening: six serious defects fixed (missing `numpy`/`scipy` imports, foreign keys not enforced, restore wiping the audit log, shelf-life boundary, authentication datetime crash and lockout on password change, `None` user guard) | 安全与数据完整性加固：修复六类严重缺陷（缺失 numpy/scipy 导入、外键未启用、恢复备份清空审计日志、有效期边界、认证时间比较崩溃与改密误锁定、用户为空防御） |
| Unreleased | 2026-10-17 | Repository reorganisation, bilingual documentation, security and isolation fixes (above) | 仓库重组、双语文档、安全与数据隔离修复（见上） |
