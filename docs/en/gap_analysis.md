# Regulatory Compliance Gap Analysis (2026-10)

**English** | [中文](../zh/法规符合性差距分析.md)

This document benchmarks the program's functions against public regulatory requirements. It lists what is implemented, partly implemented and missing, and proposes priorities. It is an internal engineering document and **not** a statement of regulatory compliance.

## 1. Status and priority

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented, with code and tests as evidence |
| ◐ | Partly implemented (calculations or prompts exist, but workflow, criteria detail or records are missing) |
| ✗ | Not implemented |
| ⚠ To verify | The criterion or threshold has not been checked against the official text and must not be quoted as a requirement |

Priority: **P0** = must be done before any regulated use; **P1** = should be done before submission or formal use; **P2** = enhancement.

## 2. ICH Q1A(R2): general stability requirements

| Requirement | Status | Evidence in the program | Gap and recommendation | Priority |
|-------------|--------|-------------------------|------------------------|----------|
| Long-term, intermediate and accelerated conditions and recommended time points | ✅ | `src/planner.py` presets; `TIME_POINT_PRESETS` | None | — |
| At least three batches (pilot or production scale) for formal studies | ◐ | Shelf-life page warns when fewer than 3 batches | Batch count and scale are not enforced at study creation; state them explicitly in the protocol check and report | P1 |
| Intermediate (30 °C/65% RH) study triggered by significant change at accelerated | ✗ | No trigger logic | Add a rule: a significant change at accelerated within 6 months prompts (or requires) intermediate data, and the decision is recorded | P0 |
| Significant-change criteria (e.g. assay decrease above 5%) | ◐ | `significant_change_assessment`, 5% default for assay | Encode criteria for other attributes (degradants, appearance, pH, dissolution); verify against the text ⚠ To verify | P1 |
| Long-term data as the main basis for shelf life | ✅ | Shelf life is based mainly on long-term data | None | — |
| Packaging and container-closure description | ◐ | Packaging is free text | Record the container-closure system in structured form (materials, dimensions, sealing) | P1 |
| Proposed storage statement | ✗ | None | Generate a draft storage statement from the data, for human confirmation | P1 |
| Stability commitment (ongoing studies after approval) | ✗ | Only a text note for the post-market stage | Add commitment planning and tracking (due dates, result filing) | P2 |
| Retest period for drug substances | ◐ | Shelf-life estimation only | Output a retest period (not an expiry) for drug substances and label it correctly | P1 |

## 3. ICH Q1B: photostability

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Overall illumination ≥ 1.2×10⁶ lux·h and near-UV ≥ 200 W·h/m² (options 1 and 2) | ✅ | `photostability_exposure_ok`, boundary tests | None | — |
| Dark control compared with light-exposed samples | ✗ | Only the 0-month sample is the comparator | Add dark-control records and a comparison that separates light effects from temperature effects | P0 |
| Sample presentation (direct exposure or in pack) | ✗ | No fields | Record presentation and pack transmittance | P1 |

## 4. ICH Q1D: bracketing and matrixing

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Bracketing / matrixing design and compliance check | ✅ | `matrix_bracket_compliance`; design advice page | None | — |
| Statistical justification for reduced designs | ◐ | Text prompt | Show the confidence-interval width before and after reduction | P2 |

## 5. ICH Q1E: evaluation of stability data

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Linear regression; shelf life at the intersection of the one-sided 95% confidence bound with the limit | ✅ | `shelf_life`, corrected in 2026-10 to the confidence bound of the regression line; `tests/test_statistics_benchmark.py` (B1, B2, B5) | The correction lengthens shelf lives for existing studies; a statistician must review it | — |
| Batch poolability test (slopes, then intercepts, ANCOVA, significance level 0.25) | ✅ | `q1e_poolability`, replacing earlier heuristic thresholds; benchmarks B3, B4 | p-values are reported; with few batches the test has low power and this should be stated | — |
| Extrapolation rules (number of batches, coverage of the monitoring period, extrapolation multiple) | ◐ ⚠ To verify | Extrapolation factor bands: ≤1×, 1–2×, >2× | Verify band thresholds and wording against Q1E; the interface text "3 batches, 75%, 2× / 1.5×" also needs checking | P0 |
| Outliers removed only after investigation | ◐ | MAD detection flags only | Add deviation / investigation records; any removal must be justified and traceable | P0 |
| Justification for non-linear models | ◐ | AIC/BIC selection with a "needs justification" note | Require a written justification in the report when a non-linear model is chosen | P1 |
| Missing data handling | ◐ | Detection of missing time points | Add a field for the reason a time point was missed | P1 |
| Leave-one-out and bootstrap as robustness checks | ✅ (analytical enhancement) | `leave_one_out_expiry`, `pooled_bootstrap_ci` (B5, B10) | Not required by Q1E; the report should label them as supplementary | — |

## 6. ICH Q5C: biotechnological products

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Potency (biological activity) included in monitoring | ✅ | Potency is in the CQA list | None | — |
| Biologic significant-change criterion (potency decrease above 10%) | ◐ ⚠ To verify | `biologic_significant_change` uses 10% | The threshold has not been checked against the original text; interface and teaching text must be aligned once verified | P0 |
| Drug substance–drug product (DS/DP) linkage | ✅ | Linked studies and prompts | None | — |
| Freeze–thaw, in-use and transport stability | ◐ | Dedicated pages and assessments | Criteria and conditions must be checked against the guidance ⚠ To verify | P1 |
| Container-closure integrity (CCIT) | ◐ | Prompt text only; no data model | Add CCIT records and trend judgement | P1 |
| Comparability studies | ◐ | Equivalence interval (TOST-style 90% CI, 80–125%) | Acceptance range must follow the product and guidance; currently an example | P2 |

## 7. ICH Q2(R2) and Q14: analytical procedures

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Evidence that the method is stability-indicating (resolution, peak purity) | ◐ | Forced-degradation page records Rs and peak purity with thresholds | Link to method validation records (method ID, validation status, version) | P0 |
| Effect of method changes on comparability of stability data | ✗ | None | Record method version and check consistency across batches | P1 |

## 8. Chinese requirements (chemical drugs and biologics)

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Influencing-factor tests (high temperature, humidity, light) | ✅ | Forced-degradation and photostability modules | Check the specific conditions against Pharmacopoeia 9001 ⚠ To verify | P1 |
| Accelerated and long-term conditions and climatic zones | ✅ | Temperature and humidity and climatic-zone table on the design page | Check the scope of application ⚠ To verify | — |
| In-use stability (after reconstitution or opening) | ✅ | In-use module | None | — |
| Representativeness of production scale | ◐ | Scale is free text | Record scale (pilot / commercial) and process parameters in structured form | P1 |

## 9. 21 CFR Part 11 and ALCOA+ (electronic records and signatures)

| Requirement | Status | Evidence | Gap and recommendation | Priority |
|-------------|--------|----------|------------------------|----------|
| Unique user identification | ✅ | Unique username constraint | None | — |
| Password controls (complexity, expiry, history) | ◐ | Minimum 8 characters only | Add complexity rules, expiry and password-history restrictions | P0 |
| Session timeout and automatic log-out | ✗ | None | Add an inactivity timeout and log the event | P0 |
| Lockout after failed logins | ✅ | Locked for 30 minutes after 5 failures | None | — |
| Audit trail: who, when, what, before and after values | ✅ | `audit_log` with before/after JSON | None | — |
| Tamper-evident audit records (hash chain) | ◐ | `verify_audit_integrity` detects broken chains | A database administrator can still rewrite the whole table; anchor the chain head externally (MethodFlow's audit anchor is a model) | P1 |
| Reason for change when data are modified | ✗ | Entry and edits do not require a reason | Require a reason for changing or deleting recorded results and write it to the audit trail | P0 |
| Electronic signature manifestation (name, date and time, meaning) | ✅ | `e_signature` records | None | — |
| Signature linked to record content (content hash) | ✗ | Signature stores only the object ID | Store a content hash at signing so later changes can be detected | P0 |
| Re-authentication for critical actions | ✅ | Deleting a study, backup, restore and user create/enable/disable require the password | Result entry and edits are not yet covered | P1 |
| Second-person verification of results | ✗ | None | Add an independent check for critical results | P1 |
| Computerised-system validation (IQ/OQ/PQ, requirements traceability) | ✗ | Automated tests exist; no validation plan or traceability matrix | Write a validation plan, URS and traceability matrix under GAMP 5; archive test evidence | P0 |
| Backup and restore | ✅ | Full JSON backup; restore keeps audit records and users | Backups are not encrypted; store them encrypted | P1 |
| Human-readable copies of records and audit trail | ✅ | Excel, PDF and JSON exports | None | — |
| UTC timestamps | ✅ | Audit records use UTC | None | — |
| Retention of electronic records | ✗ | No retention policy | Defined in SOPs; the program can provide archive exports | P2 |

## 10. Process gaps in the program

| Process | Status | Note | Priority |
|---------|--------|------|----------|
| OOS (out-of-specification) and OOT (out-of-trend) investigations | ✗ | Alerts only; no investigation, root cause or conclusion records | P0 |
| Deviation and change control | ✗ | None | P1 |
| Protocol authoring, approval and versioning | ✗ | Studies can receive data without an approval gate | P0 |
| Second-person review and release of results | ✗ | None | P1 |
| CTD-formatted output (3.2.P.8 / 3.2.S.7) | ◐ | Excel and PDF only, not in CTD section format | P1 |

## 11. Calculation and program defects corrected in this round

The following defects were found by the new tests and fixed. **Outputs of existing studies may change as a result.**

1. Shelf life used a prediction bound instead of the confidence bound of the regression line (too conservative). Corrected to the Q1E confidence bound.
2. Upper-limit attributes (e.g. related substances) reported a shelf life of 0. Direction handling corrected.
3. Batch poolability used empirical thresholds, not the Q1E significance test. Replaced with the ANCOVA step-wise test.
4. Runtime exceptions on the data entry, shelf-life, analysis and real-time validation pages. Fixed.
5. The demo-data tool failed on an empty database. Fixed.
6. On the study-management page, the delete, import/export and add-sample sections appeared only on the run after the teaching-example button was clicked. Fixed.

## 12. Suggested order of work

1. **P0 batch**: validation plan and traceability; reason for change and content hash on signatures; password complexity, expiry and session timeout; OOS/OOT investigation records; protocol approval gate; intermediate-condition trigger; dark controls; linkage to method validation; check Q1E extrapolation rules and the biologic criteria against the original texts.
2. **P1 batch**: second-person verification; draft storage statements; CTD-formatted output; container-closure and CCIT data model; external anchoring of the audit chain; encrypted backups.
3. **P2 batch**: stability commitment tracking; retest-period output for drug substances; uncertainty comparison for reduced designs.

## 13. Items to verify against the original texts

- Full text of ICH Q1A(R2) on the intermediate-condition trigger and significant-change criteria.
- Wording of ICH Q1E on extrapolation (number of batches, coverage, extrapolation multiple).
- Original text of ICH Q5C on the biologic significant-change criterion (potency 10%).
- The 2025 edition of Chinese Pharmacopoeia General Chapter 9001 and the trial guidance on stability of biological products.
- Final status of the consolidated ICH Q1 draft (whether it replaces Q1A–Q1E).

> This document lists gaps between the program and regulatory requirements. It is not a compliance conclusion. Before any submission, qualified personnel must check each item against the original texts and complete computerised-system validation.
