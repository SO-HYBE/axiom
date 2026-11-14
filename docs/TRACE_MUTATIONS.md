# AXIOM trace mutation lab

The lab measures whether deterministic monitor verdicts remain trustworthy when the observed event channel is damaged. It is an application prototype, not a reproduction of any cited algorithm or theoretical result.

## Operators and protocol

Channel operators are loss, reordering, identical duplication, payload corruption, evidence-reference corruption, sequence corruption, timestamp corruption, and delay. Operators can be seeded and composed. The original trace is preserved; each output is a separate trace. The mutator never recomputes content hashes. Three explicitly adversarial operators recompute hashes and are reported separately; resistance to that attacker is not claimed.

The experiment evaluates the original trace to obtain a reference verdict, mutates it, and compares every property/case under integrity ON and OFF. A case is classified as correct-conclusive, false-conclusive, or UNKNOWN relative to the reference. Rates retain explicit numerators and denominators. A monitor that always returns UNKNOWN would have zero coverage and cannot score as a successful conclusive monitor.

## Current measurement

The recorded result is at `runs/axiom/trace_lab/results.json`. It records commit, UTC timestamp, trace dataset size, seed range, per-property/operator results and integrity ablation. The historical measurement at commit `9c0f933` used 108 projected traces and 12,918 channel cases (seeds 0–1). Integrity ON had 10,676 correct conclusive, zero false-conclusive and 2,242 UNKNOWN cases (coverage 0.8264). Integrity OFF had 12,774 correct, 68 false-conclusive and 76 UNKNOWN (coverage 0.9941; trustworthy-conclusive rate 0.9947; false-conclusive rate 0.0053). These results show a measured soundness/coverage trade-off on this generated sample; they do not establish immunity to arbitrary mutations or generalize to other systems.

The ten seeded pipeline faults are independently labelled by construction, including publish-before-verify, stale verification, dangling citation, scope expansion against a mismatch, and missing checks. All ten were detected in the recorded run. A dangling citation also violates P6 where applicable. The labels are automatic construction labels, not human adjudications.

The UI's one-click examples use a saved benchmark trace and run a deterministic mutation in memory. They do not overwrite the measured aggregate. The measured heatmap is read from the results file; if it is absent, the UI says “not run.” The hash-integrity caveat and finite-run semantics are described in [FORMAL_PROPERTIES.md](FORMAL_PROPERTIES.md).
