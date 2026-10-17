# Architecture, Testing and Known Limitations

**English** | [中文](../zh/架构与测试.md)

## 1. Code layout

| File | Responsibility |
|------|----------------|
| `app.py` | Streamlit entry point: login, session, permission checks and all pages (about 2,170 lines; UI and business logic are mixed, and this is the main candidate for splitting) |
| `src/models.py` | Enumerations (conditions, designs, molecule types, CQAs), data classes `TimePoint` / `Measurement` / `Sample` / `StabilityStudy`, limit and value validation |
| `src/planner.py` | Sampling schedules, bracketing and matrix designs, protocol templates, matrix sample-reduction |
| `src/analysis.py` | Regression and shelf life, model selection (linear / exponential / logistic), bootstrap, leave-one-out, outliers (MAD), photostability, comparability, biologics assessment, Arrhenius extrapolation |
| `src/db.py` | Data access: create, read, update and delete for studies, samples, time points and results; full JSON backup and restore |
| `src/auth.py` | Users, bcrypt password hashes, login lockout, role permission matrix, audit log with hash-chain verification, e-signature records |
| `src/report.py` | Excel (openpyxl) and PDF (reportlab) export |
| `src/teaching.py` | Teaching-guide text and checklists |
| `src/fonts.py` | matplotlib Chinese font configuration |
| `src/importers.py` | Bulk CSV import (UTF-8 / GBK reading, required-column checks, skipped-row reasons); independent of the UI |
| `src/ui_theme.py` | Interface theme: colour tokens, CSS, sidebar brand block, login page, Plotly chart template |

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
- Foreign keys are enforced with `PRAGMA foreign_keys=ON`. Deleting a study also deletes child rows explicitly.

## 3. Authentication and audit

- Passwords are stored as bcrypt hashes, never in plain text.
- After repeated failed logins the account is locked for a period (`failed_attempts` / `locked_until`).
- The role permission matrix is `ROLE_PERMISSIONS` in `src/auth.py`.
- The audit log is append-only. `verify_audit_integrity()` checks the hash chain for tampering.
- Restoring a backup keeps `audit_log` and `users`, and appends a restore record.

## 4. Configuration

| Variable | Description |
|----------|-------------|
| `STAB_ADMIN_PASSWORD` | Password used when `admin` is first created; if unset, a one-time random password is printed to the console |
| `STAB_DATA_DIR` | SQLite data directory; the test scripts point this at a temporary directory |
| `DATABASE_URL` | PostgreSQL connection string; when set, SQLite is not used |

## 5. Testing

Run all tests:

```bash
python tests/run_all.py                                  # quick local run with a summary
python -X utf8 -m unittest discover -s tests -p "suite_*.py"  # same unittest mode as CI
```

GitHub Actions (`.github/workflows/test.yml`) runs the second command on Windows with Python 3.9 and 3.11.

| Script | Coverage | Checks |
|--------|----------|--------|
| `tests/test_core.py` | Unit tests for core analysis functions | 12 |
| `tests/test_storage.py` | End-to-end storage: save, load, templates, export | 12 |
| `tests/test_ui_logic.py` | Page logic, with and without data | 15 |
| `tests/test_regression.py` | Full-path regression and demo data | 17 |
| `tests/test_security_selfcheck.py` | Security and data integrity: cascade delete, backup/restore, authentication, boundary cases | 19 |
| `tests/test_reauth.py` | Password re-entry for sensitive actions and failure counting | 5 |
| `tests/test_seed.py` | Demo-data tool runs on an empty database | 2 |
| `tests/test_admin_flow.py` | Admin pages render; full delete-study flow requires password re-entry | 9 |
| `tests/test_functional.py` | Functional tests: numerical cross-checks against independent implementations, all templates, storage and audit, backup/restore, exports, authentication and lockout, roles, CSV import | 38 |
| `tests/test_ui_workflows.py` | UI workflows: login, role navigation, study → sample → data entry, teaching examples, user management, password change, every page rendered for four roles | 28 |

Each script sets `STAB_DATA_DIR` to a temporary directory, so **the live `stability.db` is not modified**. Tests use a fixed test value for `STAB_ADMIN_PASSWORD`.

**Limitations**: the tests are scripts with their own assertions, not a pytest suite. The statistical modules have no independent numerical benchmark checks against external reference values. The PostgreSQL path is not covered by the tests.

## 6. Known limitations and plans

1. **Test system**: wired into CI, but the tests are still scripts with their own assertions rather than separate test cases. Numerical benchmarks for bootstrap and leave-one-out are still to be added.
2. **Part 11 gaps**: deleting a study and restoring a backup now require password re-entry and record a signature. Password change, export and user management are not yet covered by e-signatures. The IP and session fields may be empty in local deployments.
3. **PostgreSQL**: supported in code but not fully tested.
4. **Code structure**: `app.py` is too large and mixes UI with business logic; split it into page modules.
5. **Interface language**: the UI is currently Chinese only. English UI is not yet available (the documentation is bilingual).
6. **Legacy administrator password**: databases created by older versions may still use `Admin@2026`. Administrators see a sidebar reminder after login, but the program does not force a change.

## 7. Runtime environment

- Python 3.9+. Development and test environment: Python 3.9.13, Streamlit 1.50.0, SciPy 1.13.1, NumPy 1.26.4, pandas 2.3.3, plotly 6.9.0.
- Dependencies: see `requirements.txt`.
