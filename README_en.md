# Drug Stability Study Management and Analysis System

**English** | [中文](README.md)

A locally run tool for managing and analysing drug stability studies for chemical drugs (drug substances and drug products) and biological products. It covers study planning, data entry, degradation trend regression, shelf-life estimation, report export, and audit and access control.

> **Disclaimer**: This is a research support tool and has **not been validated as a GxP computerised system**. Before any regulated use, the organisation's quality function must assess and validate it under a GAMP 5 / CSV process, and an authorised person must determine shelf life using all quality attributes, packaging and batch information. Limits and time points in the program are examples or reference values; the current regulatory texts and the product protocol govern.

## Main features

| Module | Description |
|--------|-------------|
| Study management | Create studies (chemical or biological, clinical phase, full / bracketing / matrix designs); generate sampling schedules based on ICH recommended conditions; built-in protocol templates for biologics |
| Data entry | Enter results by sample × condition × time point; CSV batch import; real-time validation |
| Analysis and trend plots | Linear regression (slope, annual degradation rate, R², p-value), interactive trend plots with specification lines |
| Shelf-life estimation | 95% confidence bound per ICH Q1E; model comparison (linear / exponential / logistic) by AIC/BIC; bootstrap confidence intervals; leave-one-out robustness |
| Quality alerts | Outliers (robust MAD method), missing observations, significant-change assessment, data-quality scan |
| Biologics (ICH Q5C) | Drug substance (DS) / drug product (DP) linkage, forced-degradation confirmation, freeze–thaw, in-use stability, transport stress, CQA analysis (potency, aggregates, fragments, charge variants, etc.) |
| Photostability | Light-exposure assessment per ICH Q1B |
| Comparability | Pre/post-change or biosimilar CQA comparison with equivalence-interval assessment |
| Report export | Excel (multi-sheet) and PDF reports, including a cross-study summary |
| Teaching guide | Glossary of regulatory terms, stage compliance checklists, common pitfalls |
| Access and audit | Four roles (admin / manager / analyst / viewer); append-only audit log with hash-chain verification; login lockout; bcrypt password hashing |
| Maintenance | Full JSON backup and restore; compliance self-check (DS–DP links, missing limits, audit coverage) |

## Quick start

Requirements: Python 3.9 or later.

```bash
pip install -r requirements.txt

# Optional: set the initial admin password before first start
# Windows PowerShell:  $env:STAB_ADMIN_PASSWORD = "use a strong password"
# Linux/macOS:          export STAB_ADMIN_PASSWORD="use a strong password"

python tools/seed_example.py     # optional: demo data (for trying the system only)
streamlit run app.py             # open http://localhost:8501
```

The default administrator username is `admin`. Change the password immediately after first login.

Run the tests (each test script uses a temporary database and never touches live data):

```bash
python tests/run_all.py
```

See the [User guide](docs/en/user_guide.md), [Regulatory basis](docs/en/regulatory_basis.md), [Architecture and testing](docs/en/architecture_and_testing.md), and the [Changelog](CHANGELOG.md).

## Project layout

```
.
├── app.py                 # Streamlit entry point (pages, interaction, access control)
├── src/                   # core library
│   ├── models.py          # data model, CQA limit directions, value validation
│   ├── planner.py         # sampling schedules (ICH Q1A / Q1D / Q5C)
│   ├── analysis.py        # regression, shelf life, model selection, outliers, biologics assessment
│   ├── db.py              # database access (SQLite by default, PostgreSQL optional), backup/restore
│   ├── auth.py            # users, roles, passwords, lockout, audit log
│   ├── report.py          # Excel / PDF export
│   ├── teaching.py        # teaching-guide content
│   ├── importers.py       # bulk CSV import (UTF-8 / GBK)
│   ├── ui_theme.py        # interface theme, styles and chart template
│   └── fonts.py           # matplotlib Chinese font setup
├── tools/
│   ├── seed_example.py    # demo data
│   └── backup.py          # command-line backup
├── .streamlit/config.toml # Streamlit theme settings
├── tests/                 # test scripts (python tests/run_all.py; CI runs the unittest suite)
└── docs/
    ├── zh/                # 中文文档
    └── en/               # English documentation
```

## Configuration (environment variables)

| Variable | Purpose | Default |
|----------|---------|---------|
| `STAB_ADMIN_PASSWORD` | Password used when the `admin` account is first created | If unset, a random one-time password is printed to the console |
| `STAB_DATA_DIR` | Directory for the SQLite database | Project root |
| `DATABASE_URL` | `postgresql://...` to use PostgreSQL (needs `psycopg2-binary`) | SQLite |

## Licence and contributing

This project is licensed under the [Apache License 2.0](LICENSE); copyright notice in [NOTICE](NOTICE). See [CONTRIBUTING.md](CONTRIBUTING.md) for contributing and [SECURITY.md](SECURITY.md) for reporting security issues.

> This software is not a validated GxP system and is provided "AS IS", without warranty.
