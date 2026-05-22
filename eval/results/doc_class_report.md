# Sprint 1 — Doc-Class Classifier Eval Report

**Total docs:** 16
**Overall accuracy:** 100.00% (16/16)
**Real-only accuracy:** 100.00% (5/5)
**Synthetic-only accuracy:** 100.00% (11/11)
**Unknown precision:** 100.00%

## Acceptance gate status

| Gate | Pass | Threshold |
|---|---|---|
| overall | ✅ | 90% |
| real | ✅ | 80% |
| synthetic | ✅ | 100% |
| unknown_precision | ✅ | 100% |

## Per-class breakdown

| Class | Total | Correct | Recall |
|---|---:|---:|---:|
| coordination_study | 4 | 4 | 100% |
| equipment_spec | 3 | 3 | 100% |
| relay_setting_sheet | 1 | 1 | 100% |
| hvac_schedule | 2 | 2 | 100% |
| pid | 2 | 2 | 100% |
| bom | 1 | 1 | 100% |
| civil_drawing | 1 | 1 | 100% |
| unknown | 2 | 2 | 100% |

## Per-doc verdicts

| Path | Source | Expected | Actual | Confidence | Match |
|---|---|---|---|---:|---|
| `fixtures/pdfs/doc_a_60pct.pdf` | real | coordination_study | coordination_study | 0.93 | ✅ |
| `fixtures/pdfs/doc_b_90pct.pdf` | real | coordination_study | coordination_study | 0.93 | ✅ |
| `fixtures/pdfs/doc_a_scanned.pdf` | real | coordination_study | coordination_study | 0.94 | ✅ |
| `fixtures/pdfs/synth_coordination_study_v2.pdf` | synthetic | coordination_study | coordination_study | 0.95 | ✅ |
| `fixtures/pdfs/spec_xfmr_001.pdf` | synthetic | equipment_spec | equipment_spec | 0.97 | ✅ |
| `fixtures/pdfs/synth_equipment_spec_v2.pdf` | synthetic | equipment_spec | equipment_spec | 0.98 | ✅ |
| `fixtures/pdfs/synth_equipment_spec_v3.pdf` | synthetic | equipment_spec | equipment_spec | 0.97 | ✅ |
| `fixtures/pdfs/synth_relay_setting_sheet.pdf` | synthetic | relay_setting_sheet | relay_setting_sheet | 0.98 | ✅ |
| `fixtures/pdfs/synth_hvac_schedule.pdf` | synthetic | hvac_schedule | hvac_schedule | 0.98 | ✅ |
| `fixtures/pdfs/synth_hvac_schedule_v2.pdf` | synthetic | hvac_schedule | hvac_schedule | 0.98 | ✅ |
| `fixtures/pdfs/synth_pid.pdf` | synthetic | pid | pid | 0.97 | ✅ |
| `fixtures/pdfs/synth_pid_v2.pdf` | synthetic | pid | pid | 0.97 | ✅ |
| `fixtures/pdfs/synth_bom.pdf` | synthetic | bom | bom | 0.98 | ✅ |
| `fixtures/pdfs/synth_civil_drawing.pdf` | synthetic | civil_drawing | civil_drawing | 0.97 | ✅ |
| `fixtures/pdfs/real_sel_xfmr_protection.pdf` | real | unknown | unknown | 0.95 | ✅ |
| `fixtures/pdfs/real_ieee_xfmr_spec_guide.pdf` | real | unknown | unknown | 0.90 | ✅ |