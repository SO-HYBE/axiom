# Extraction validation - review sheet

Results commit: 5eb61c811db588fd5ed06ef43e64d645e77768ca  
Run at: 2026-11-13T18:38:06.522484+00:00  
Labels: 57 across 28 labeled chunks (33 sampled), 11 sources.

**Provenance:** Original labels remain agent-drafted. The project owner human-reviewed 18 listed decisions, recorded in `review_decisions.jsonl`; only reviewed expected labels were overlaid during scoring. The review is not independent annotation or scientific validation.

## Fixed rules

Tolerances: oxygen_percent 0.05, pressure_kpa 0.5, flow_cm_s 0.05, temperature_k 0.2. Ranges match when both endpoints agree within tolerance. Identical (field, value) pairs are deduplicated on both sides (a test-matrix table is one value, not one claim per row).

## Measured

| Field | Precision | Recall | F1 | Eligible labels | Not eligible |
| --- | --- | --- | --- | --- | --- |
| oxygen_percent | 0.9 | 0.6 | 0.72 | 15 | 3 |
| pressure_kpa | 1.0 | 0.8 | 0.8889 | 10 | 1 |
| flow_cm_s | 0.7143 | 0.8333 | 0.7692 | 12 | 5 |
| temperature_k | 1.0 | 0.3333 | 0.5 | 3 | 8 |
| all | 0.8485 | 0.7 | 0.7671 | 40 | 17 |

Numeric agreement on matched values: 1.0 (max absolute error 0.0). Exclusion violations: 4.

## Disagreements reviewed by project owner

The decisions below were supplied on 2026-11-13. Accepted missed conditions remain expected labels. Rejected extra predictions remain extractor errors; the accepted 40 cm/s prediction was added as an eligible expected label. Exact decisions and draft eligibility are preserved in `review_decisions.jsonl`.

- missed eligible: ntrs-20130010979-p010-c01-fd0467f8fa oxygen_percent 20.0 - reported as 'O2 20%'
- missed eligible: ntrs-20130010979-p012-c01-8bdec51425 oxygen_percent 21.0 - reported as 'O2 21'
- extra eligible: ntrs-20130010979-p012-c01-8bdec51425 oxygen_percent {'min': 0.0, 'max': 79.0} - scope experiment_range - quote 'O2% N2% Ar% Pressure H-7-62 21 29 50 1 atm H-7-63 21 9 70 1 atm H-7-65 21 9 70 1 atm H-7-66 21 29 50 1 atm H-7'
- missed eligible: ntrs-20150008961-p005-c01-b4f0f6a3aa oxygen_percent 16.1 - reported as '16.1% O2'
- extra eligible: ntrs-20150008962-p007-c01-8ed8d03bb2 flow_cm_s {'min': 1.0, 'max': 5.0} - scope experiment_range - quote 'Quenching flow velocities were found to be between 1 and 5 cm/s with higher velocity at lower oxygen percentag'
- extra eligible: ntrs-20160000593-p013-c01-3cd1a48792 flow_cm_s 2.0 - scope individual_test - quote 'Residence Time Driven Flame Spread Sequence of top views showing radiative quenching when flow velocity goes b'
- extra eligible: ntrs-20160000593-p013-c01-3cd1a48792 flow_cm_s 40.0 - scope individual_test - quote 'Flame nearing blow off extinction as the flow velocity crosses 40 cm/s.'
- missed eligible: ntrs-20160012691-p003-c01-e215cb21dd oxygen_percent 18.0 - reported as '18% oxygen'
- extra eligible: ntrs-20160012691-p003-c01-e215cb21dd flow_cm_s 5.0 - scope individual_test - quote 'Each boundary is approximately linear with flow, with the exception of the 14% oxygen data, where all the data'
- missed eligible: ntrs-20160012691-p005-c01-a31cda8aaf oxygen_percent 14.0 - reported as '14% oxygen'
- missed eligible: ntrs-20170008805-p017-c01-0dc38613a7 flow_cm_s 20.0 - reported as '20 cm/s'
- missed eligible: ntrs-20180005168-p023-c01-40ae747daa flow_cm_s 25.0 - reported as '25 cm/s'
- extra eligible: ntrs-20180005168-p023-c01-40ae747daa flow_cm_s {'min': 20.0, 'max': 25.0} - scope experiment_range - quote 'Ignition power: Saffire 1: 165 W (for 8 s) 4.1 W/cm (per unit fuel width) Saffire 2: 80 W (for 9.2 s) 16 W/cm '
- missed eligible: ntrs-20210022617-p004-c01-c1c1ac1638 oxygen_percent {'min': 13.0, 'max': 30.0} - reported as '13% < O2 < 30%'
- missed eligible: ntrs-20210022617-p013-c01-fa6a6b0e05 pressure_kpa 101.325 - reported as '1 atm'
- missed eligible: ntrs-20210022617-p013-c01-fa6a6b0e05 pressure_kpa 303.975 - reported as '3 atm'
- missed eligible: ntrs-20240008602-p004-c02-0a0d514825 temperature_k 297.15 - reported as '24°C'
- missed eligible: ntrs-20240008602-p008-c01-5b3612cdfb temperature_k 297.25 - reported as '24.1 °C'

## Reviewer sign-off

- Reviewer: project owner (user)
- Date: 2026-11-13
- Human-reviewed decisions recorded: 18
- Remaining labels outside the review log are still agent-drafted and unreviewed.
