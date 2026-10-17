# Regulatory Basis and Verification Status

**English** | [中文](../zh/法规依据.md)

This document lists the regulations behind the system's functions and records the **verification status** of each source.

> **Rule of use**: the status column records what was found when this project's sources were searched and compiled (2026-10). Items marked "original not obtained / to verify" **must not** be cited as regulatory requirements for the program's criteria until the official text has been checked clause by clause.

## 1. Sources and verification status

| Source | Summary | Use in the system | Status |
|--------|---------|-------------------|--------|
| ICH Q1A(R2) (2003) | Stability testing of new drug substances and products: long-term (25 °C ± 2 °C / 60% RH ± 5% RH), intermediate (30 °C ± 2 °C / 65% RH ± 5% RH), accelerated (40 °C ± 2 °C / 75% RH ± 5% RH) conditions and time points | Sampling schedules, condition setup, significant-change logic | Original not held locally. No replacement was confirmed in our search; **verify against the ICH website** |
| ICH Q1B | Photostability: overall illumination ≥ 1.2 × 10⁶ lux·h and near-UV energy ≥ 200 W·h/m² | Light-exposure assessment | Original not held locally; **to verify** |
| ICH Q1C | New dosage forms | Descriptive reference | To verify |
| ICH Q1D | Bracketing and matrixing designs | Bracketing / matrix design and sample-reduction calculations | Original not held locally; **to verify** |
| ICH Q1E | Evaluation of stability data: regression, shelf life from the one-sided 95% confidence bound, poolability of batches | Shelf-life estimation, pooled regression, leave-one-out and bootstrap analyses | Original not held locally; **to verify** |
| ICH Q5C (1995) | Stability testing of biotechnological / biological products: biological activity (e.g. potency) should be included; data for drug substance and drug product; real-time data as the main support | Biologics CQA framework, DS/DP linkage, potency significant change | Existence confirmed (EMA lists CPMP/ICH/138/95, legal effective date 1 July 1996). **The specific criteria, e.g. a 10% potency change threshold, have not been checked against the original text** |
| ICH Q1 consolidated draft (Step 2, April 2025) | Proposes to merge the Q1 series and Q5C into one guideline covering chemical drugs and biologics, with reduced designs, statistical modelling and ATMP annexes | Not used (tracked only) | Entered public consultation at Step 2b on 11 April 2025. **Final Step 4 status not confirmed**; sources disagree on which legacy guidelines it replaces. **Check the ICH website** |
| ICH Q2(R2) and ICH Q14 (adopted November 2023) | Validation and development of analytical procedures | Methods used with the system should be developed and validated under these principles (the system does not replace method validation) | CDE Chinese translations are in the method-procedure folder `D:\claude\分析方法开发转移验证\法规文件\` (files 13 and 14) |
| *Guidance for Stability Study of Chemical Drugs (Drug Substances and Preparations)*, NMPA/CDE | China's general guidance on chemical-drug stability; many sources still treat it as current | Chinese chemical-drug conditions, time points and accelerated-test interpretation | Reported as current by third-party sources. No 2024 revision draft was found in our search. **Original not obtained; to verify** |
| *Chinese Pharmacopoeia* (2025 edition), Volume IV, General Chapter 9001 *Stability Testing of Drug Substances and Drug Products* | Forced (stress) degradation, accelerated and long-term testing, in-use stability | Interpretation of chemical-drug forced degradation and stress testing | Third-party websites host the text. **Differences between the 2020 and 2025 versions are not verified; original not obtained.** Do not quote clauses directly |
| *Guidance for Stability Study of Biological Products (trial)*, CDE | Stability requirements for biologics, aligned with ICH Q5C | Freeze–thaw, in-use and transport stability; biologics CQA interpretation | Existence confirmed through third-party reprints. **Original not obtained; to verify.** The project's V2.1 notes gave a 2015 date, which has not been verified |
| USP <1049>, <1207> | Stability and container closure integrity topics | Container closure notes | Cited in the V2.1 notes; **not checked in this round** |
| 21 CFR Part 11 (FDA) | Electronic records and electronic signatures | Design reference for audit log and e-signatures | The system is **not** Part 11 compliant; known gaps are listed in [Architecture and testing](architecture_and_testing.md), section 6 |
| ALCOA+ | Attributable, legible, contemporaneous, original, accurate, plus complete, consistent, enduring, available | Design reference for audit fields | General principle |

## 2. Mapping of program rules to sources

| Program function | Source | Note |
|------------------|--------|------|
| Sampling schedule | ICH Q1A(R2); Q1D (bracketing / matrixing); Q5C (biologics) | Time points are recommendations; the protocol defines the actual schedule |
| Shelf-life estimation | ICH Q1E: regression with the one-sided 95% confidence bound | Default uses the 95% one-sided confidence bound of the regression line (mean response); corrected in 2026-10 from a prediction bound. Model selection, bootstrap and leave-one-out are **analytical enhancements**, not requirements of Q1E |
| Pooled regression | ICH Q1E poolability test | Test batch slope and intercept differences before pooling |
| Photostability judgement | ICH Q1B | Two thresholds: overall illumination and near-UV energy |
| Biologics significant change (potency > 10%) | Project rule, informed by ICH Q5C discussion | **To be checked against the Q5C text.** Until then the protocol definition governs |
| Freeze–thaw / in-use / transport stability | Q5C and CDE's biologics stability guidance | Conditions and criteria are defined in the protocol and the original text |
| Forced-degradation confirmation | Chinese Pharmacopoeia 9001 (chemical drugs); Q5C (biologics) | Checks for stability-indicating capability; criteria are internal program rules |
| Data integrity and e-signatures | 21 CFR Part 11; ALCOA+ | Design references only; not validated |

## 3. Notes for users

1. Limits, time points and thresholds in the program are **examples or reference values**. Use the applicable regulatory text and product specification.
2. Shelf-life conclusions must be determined by an authorised person. System output is advisory.
3. Do not cite sources marked "original not obtained" as regulatory requirements in filings or submissions.
4. Regulations change. Confirm the version and effective date before citing.
