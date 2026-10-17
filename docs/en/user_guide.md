# User Guide

**English** | [中文](../zh/使用手册.md)

> This guide describes day-to-day operation. Limits, time points and thresholds in the program are example values; follow the protocol and current regulations (see [Regulatory basis](regulatory_basis.md)).

## 1. Install and start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open `http://localhost:8501` in a browser. On first start the system creates the administrator `admin`:

- If the environment variable `STAB_ADMIN_PASSWORD` is set, that value is the password;
- Otherwise a one-time random password is printed to the console. Record it and log in.

> **Note**: versions up to V2.3 used the fixed default password `Admin@2026`. If your database was created by an older version, log in with that password **immediately** and change it.

## 2. Roles and permissions

| Role | Permitted actions |
|------|-------------------|
| Administrator (admin) | All functions, including user management, audit log and system maintenance (backup/restore) |
| Study manager (manager) | Create and delete studies, enter data, analyse, export, view the audit log |
| Analyst (analyst) | Create studies, enter data, analyse, export |
| Read-only (viewer) | View data, run analyses, export reports |

All write actions (create, update, delete, import, restore, login, password change) are recorded in the audit log. The audit log is append-only.

**Sensitive actions need your password again**: deleting a study and restoring a backup ask you to re-enter your login password as an electronic signature. Wrong passwords count toward the login-failure limit and can lock the account temporarily.

## 3. Recommended workflow

1. **Study management**: create a study, choose chemical or biological product and design type (full / bracketing / matrix). Protocol templates can be used.
2. **Add samples**: enter batch, packaging and conditions. The system generates a sampling schedule based on ICH recommended conditions.
3. **Data entry**: enter results by sample × condition × time point, or import CSV. Range and format checks apply at entry.
4. **Analysis and trend plots**: review regression slopes, annual degradation rates, R² and trend plots against limits.
5. **Shelf life**: estimate shelf life from the 95% confidence bound; view model comparison, bootstrap intervals and leave-one-out results.
6. **Quality alerts**: review outliers, missing observations and significant-change flags, and confirm each cause.
7. **Export report**: export Excel or PDF containing the study overview, schedule, data, analysis and alerts.

## 4. Pages

| Page | Purpose |
|------|---------|
| Dashboard | Overview of the database and entry points |
| Study management | Create and edit studies and samples; delete studies |
| Data entry | Enter results manually or import CSV |
| Analysis and trend plots | Regression analysis and interactive trend plots |
| Shelf life | Shelf-life estimation, extrapolation factors, model comparison |
| Cross-comparison | Compare batches and studies |
| Quality alerts | Results of the data-quality scan |
| Biologics CQA | Biologics-specific views: DS/DP linkage, forced degradation, freeze–thaw, in-use, transport, CQA radar |
| Photostability | Light exposure and ICH Q1B assessment |
| Statistics summary | Cross-study statistics and robustness tables |
| Export report | Excel / PDF reports |
| Design advice | Bracketing and matrix sample-reduction calculations; temperature conversion and Arrhenius notes |
| Comparability | Pre/post-change or biosimilar CQA comparison and equivalence intervals |
| Audit log | Query and export audit records; verify the hash chain |
| User management | Administrators create users, assign roles, enable or disable accounts |
| System maintenance | Full JSON backup and restore; compliance self-check |
| Teaching guide | Regulatory terms, stage checklists, common pitfalls |

## 5. Backup and restore

- **In the app**: System maintenance → export backup (JSON; includes password hashes and the audit log). Restore keeps the audit log and user table.
- **Command line**: `python tools/backup.py backups/stability_YYYYMMDD.json`

Backup files contain password hashes and audit records. Keep them secure and **do not** commit them to a public repository.

## 6. Database

- By default the SQLite file `stability.db` is in the project root. Set `STAB_DATA_DIR` to use another directory.
- Set `DATABASE_URL=postgresql://...` to use PostgreSQL (requires `psycopg2-binary`). **The PostgreSQL path has not yet been fully tested.**

## 7. Demo data

```bash
python tools/seed_example.py
```

Creates one chemical tablet example and one biologic monoclonal-antibody example (including non-linear degradation). For trying the system only; **do not run it against a production database.** To isolate, set `STAB_DATA_DIR` first.

## 8. Troubleshooting

- **Forgotten administrator password**: there is no graphical reset yet. Stop the service and restore a backup, or have a qualified person replace the password hash for `admin` in the `users` table, recording the change.
- **Shelf life shows "within observed period" or is empty**: usually there are too few time points for regression, or the starting value is already out of limit. Read the message on the analysis page.
- **Garbled Chinese text in charts**: `src/fonts.py` tries to configure a Chinese font; install one and restart if none is available.
