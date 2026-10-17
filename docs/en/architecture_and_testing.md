# Architecture, Testing and Known Limitations

**English** | [中文](../zh/架构与测试.md)

## 1. Code layout

```
app.py                  entry point: setup, login, sidebar, language switch, page dispatch (about 150 lines)
src/
  ui_common.py          shared UI helpers: study loading, persistence, permission checks, teaching examples, constants
  pages/*.py            17 pages; each module provides render(ctx)
  ui_theme.py           theme, CSS, sidebar brand block, login page, Plotly template
  i18n.py               language switch (thread-local; Chinese is the source language)
  i18n_en.py            English translations (keys are the Chinese source strings)
  models.py             enumerations, data classes, limit and value validation
  planner.py            sampling schedules, bracketing / matrix designs, protocol templates
  analysis.py           regression, shelf life, Q1E poolability test, bootstrap, leave-one-out,
                        outliers, photostability, comparability, biologics assessment, Arrhenius
  db.py                 data access (SQLite / PostgreSQL), full backup and restore
  auth.py               users, passwords, lockout, roles, audit log with hash chain, e-signature records
  importers.py          bulk CSV import (UTF-8 / GBK, required-column checks, skipped-row reasons)
  report.py             Excel (openpyxl) and PDF (reportlab) export
  teaching.py           teaching-guide text and checklists
  fonts.py              matplotlib Chinese font setup
tools/                  demo data, command-line backup
tests/                  test scripts (section 6)
docs/zh, docs/en        documentation
```

Page dispatch: `PAGE_RENDERERS` in `app.py` maps each navigation label to `render(ctx)` in `src/pages/`. `ctx` contains `user`, `role`, `name`, `uname` and `studies`.

## 2. Data model

```
studies ─1:N─ samples ─1:N─ time_points ─1:N─ measurements
                                  ▲
                 measurements.tp_ref points exactly to time_points.tp_id
users                 (accounts, roles, password hashes, lockout counters)
audit_log             (append-only: operator, time (UTC), action, object, IP, session, before/after, note)
```

- `tp_ref` links a result to exactly one time point, so results for the same month under different conditions are not mismatched.
- SQLite uses `?` placeholders and PostgreSQL uses `%s`; `db._sql()` converts between them.
- Writes use portable `INSERT … ON CONFLICT … DO UPDATE` and `DO NOTHING`, valid on both databases.
- SQLite enforces foreign keys with `PRAGMA foreign_keys=ON`; PostgreSQL enforces them natively.

## 3. Authentication, audit and electronic signatures

- Passwords are stored as bcrypt hashes. Only a minimum length of 8 characters is enforced (complexity and expiry are in the gap analysis).
- Five consecutive failed logins lock the account for 30 minutes (`failed_attempts` / `locked_until`).
- Role permission matrix: `ROLE_PERMISSIONS` in `src/auth.py`.
- The audit log is append-only; `verify_audit_integrity()` detects tampering through the hash chain.
- **Electronic signatures** (`reauthenticate` + `e_signature`): the following actions require the login password to be entered again and write an `ESIGN` audit record:
  - deleting a study;
  - generating a full backup (backups contain password hashes);
  - full restore;
  - creating users, and disabling or enabling users.
  Wrong passwords count toward the lockout policy.
- Restoring a backup keeps `audit_log` and `users` and appends a restore record.

## 4. Statistical methods

| Function | Method | Note |
|----------|--------|------|
| Shelf life | Intersection of the one-sided 95% confidence bound of the regression line with the limit (ICH Q1E) | `shelf_life` |
| Batch poolability | ANCOVA step-wise F tests: slopes first, then intercepts; significance level 0.25 | `q1e_poolability` |
| Pooled extrapolation | Pooled regression when batches are poolable; otherwise the minimum single-batch value | `pooled_expiry_extrapolation` |
| Robustness | Leave-one-out (drop one batch at a time) and bootstrap (reproducible with a fixed seed) | `leave_one_out_expiry`, `pooled_bootstrap_ci` |
| Outliers | Modified z-score (MAD, threshold 3.5); flagged only, never removed automatically | `mad_outlier_detection` |
| Light | ICH Q1B thresholds (overall illumination and near-UV energy) | `photostability_exposure_ok` |
| Activation energy | Linear regression of ln k on 1/T (screening indication only) | `arrhenius_extrapolate` |

## 5. Configuration

| Variable | Description |
|----------|-------------|
| `STAB_ADMIN_PASSWORD` | Password used when `admin` is first created; if unset, a one-time random password is printed to the console |
| `STAB_DATA_DIR` | SQLite data directory; the test scripts point it at a temporary directory |
| `DATABASE_URL` | PostgreSQL connection string; when set, SQLite is not used |
| `STAB_TEST_PG_URL` | Only for `tests/test_postgres.py`: a disposable test database |

## 6. Testing

Run all tests:

```bash
python tests/run_all.py                                       # quick local run with a summary
python -X utf8 -m unittest discover -s tests -p "suite_*.py"  # same unittest mode as CI
```

PostgreSQL tests (use a disposable database; the test drops its business tables first):

```bash
STAB_TEST_PG_URL=postgresql://user:pass@127.0.0.1:5432/stability_test python tests/test_postgres.py
```

Without `STAB_TEST_PG_URL` the test prints SKIP and exits with 0. CI does not run a PostgreSQL service.

| Script | Coverage | Checks |
|--------|----------|--------|
| `tests/test_core.py` | Unit tests for core analysis functions | 12 |
| `tests/test_storage.py` | End-to-end storage: save, load, templates, export | 12 |
| `tests/test_ui_logic.py` | Page logic, with and without data | 15 |
| `tests/test_regression.py` | Full-path regression and demo data | 17 |
| `tests/test_security_selfcheck.py` | Security and integrity: cascade delete, backup/restore, authentication, boundary cases, module imports | 18 |
| `tests/test_reauth.py` | Password re-entry for sensitive actions and failure counting | 5 |
| `tests/test_seed.py` | Demo-data tool runs on an empty database | 2 |
| `tests/test_admin_flow.py` | Admin pages render; full delete-study flow requires password re-entry | 9 |
| `tests/test_functional.py` | Numerical checks against independent implementations, all templates, storage and audit, backup/restore, exports, authentication and lockout, roles, CSV import | 38 |
| `tests/test_statistics_benchmark.py` | Statistical benchmarks: shelf life, pooling (slopes and intercepts), leave-one-out, Arrhenius, Q1B, MAD, bootstrap | 16 |
| `tests/test_ui_workflows.py` | UI workflows: login, role navigation, study → sample → data entry, teaching examples, user management, password change, electronic signatures, every page for four roles | 34 |
| `tests/test_i18n.py` | Language switch, placeholder consistency, all pages without exceptions in English, all headers translated | 10 |
| `tests/test_postgres.py` | PostgreSQL backend (requires `STAB_TEST_PG_URL`) | 11 |

## 7. Known limitations

1. **Tests**: most tests are still scripts with their own assertions rather than separate pytest cases. CI does not run PostgreSQL.
2. **Regulatory compliance**: several P0 gaps remain, including the intermediate-condition trigger, dark controls, reason for change, binding of signatures to record content, password complexity and session timeout, OOS/OOT investigations, a protocol approval gate, and computerised-system validation documents. See the [gap analysis](gap_analysis.md).
3. **Interface language**: the interface can be switched to English (section 8). The following remain Chinese: narrative conclusions from the analysis (for example "batches differ significantly" or "non-linear degradation hint"), chart titles and axes, Excel and PDF reports, the planning text on the design-advice page, and user data such as study, sample and attribute names.
4. **Statistical criteria**: the biologic significant-change threshold (potency decrease above 10%) and the extrapolation rules (number of batches, coverage, extrapolation multiple) have not been checked against the official texts. See the gap analysis and the regulatory-basis document.
5. **Legacy administrator password**: databases created by older versions may still use `Admin@2026`. The program does not force a change; it only shows a sidebar reminder.

## 8. Interface language

- The language is chosen from a drop-down at the top of the login page or in the sidebar (中文 / English) and is kept for the session.
- Text is looked up with `i18n.t()`. Missing translations fall back to Chinese, so new interface text cannot break a page.
- When adding interface text, wrap it as `t("中文")` and add the English entry to `src/i18n_en.py`. Keys must match the Chinese source exactly. Placeholders such as `{0}` must be identical in both languages; `tests/test_i18n.py` checks this.

## 9. Runtime environment

- Python 3.9+. Development and test environment: Python 3.9.13, Streamlit 1.50.0, SciPy 1.13.1, NumPy 1.26.4, pandas 2.3.3, plotly 6.9.0.
- PostgreSQL test environment: PostgreSQL 16.2 (via pgserver and psycopg2 2.9).
- Dependencies: see `requirements.txt`.
