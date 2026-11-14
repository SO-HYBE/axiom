# AXIOM finite-run properties

AXIOM is a deterministic prototype monitor over structured execution traces. It evaluates process properties; it does **not** judge whether a real source semantically supports a claim. A mis-linked claim can pass if its identifiers are internally consistent. A PASS is therefore a process verdict, not scientific validation.

## Verdict semantics

The monitor evaluates finite terminated runs and returns `PASS`, `FAIL`, or `UNKNOWN` for each property. A trusted, observed violation gives FAIL. PASS requires the observations needed by the property to be trusted and the run-end manifest to be complete. A missing observation in an incomplete run is UNKNOWN, because loss cannot be distinguished from non-occurrence. The aggregate is FAIL if a mandatory property fails; otherwise UNKNOWN if any mandatory property is unknown; otherwise PASS. This is not a claim about monitorability of infinite traces.

The output policy is fixed: PASS permits “published as verified”; UNKNOWN permits publication only with an explicit “unverified” label; FAIL withholds the claim. The language model never produces or changes monitor verdicts.

## Registry

| Property | Meaning on one finite run | Trusted violation | PASS requires | UNKNOWN includes |
|---|---|---|---|---|
| P1 Evidence provenance | Evidence referenced by a claim resolves to a retrieval event in this run. | A trusted reference has no trusted retrieval record. | Complete trusted retrieval and claim-link observations. | Retrieval/link observations are missing or untrusted. |
| P2 Verification prerequisites | Supported verification follows metadata validation and the required applicability check. | A trusted verification precedes or lacks a required check. | Complete ordered prerequisites for the claim. | Ordering, prerequisites, or run completeness is uncertain. |
| P3 Same presented version | Verification and publication use the same claim, evidence set, scenario version and metadata version. | A trusted publication changes one of those identities. | Verification and publication identities agree through termination. | Verification or publication evidence is missing/untrusted. |
| P4 No scope claim against contradiction | A scope verification is not paired with a contradictory applicability result. | Trusted scope claim conflicts with a trusted mismatch/conflict for the scenario. | Complete trusted applicability and verification events. | Relevant checks are absent or untrusted. |
| P5 Uncertainty is not success | “Verified” publication requires matching supported verification; withheld claims are not published. | Trusted verified label has no matching support, or a withheld claim is published. | Complete trusted verification and publication events. | The relevant verification or publication is uncertain. |
| P6 Citation resolution | Every published citation ID resolves to a retrieval record in this run. | A trusted citation refers to an unretreived identifier. | Complete trusted retrieval and publication records. | Retrieval or publication observations are uncertain. |
| P7 Duplicate event IDs | Identical duplicate is idempotently discarded and noted; conflicting duplicate makes the event untrusted. | A conflicting duplicate is treated as trusted by the integrity layer. | Integrity classification is available. | Conflicting duplicate makes required observations untrusted. |
| P8 Publication ordering | Publication does not precede verification when ordering is reliable. | Trusted reliable order puts publication before required verification. | Trusted sequence/delivery order and complete run. | Ordering is unreliable or required events are missing. |

P7 and P8 are enforced by the integrity layer before P1–P6 run. An identical duplicate is discarded with a note; it is not counted twice. Conflicting duplicate IDs are not repaired. P8 cannot assert chronology from timestamps; sequence numbers are authoritative. Timestamp intervals are not implemented.

## Integrity boundary

Each event has a canonical-content SHA-256 hash. The run-end manifest records event count and last sequence. The monitor reports sequence gaps, duplicate IDs, hash mismatches, malformed events, delivery ordering, and run completeness before property evaluation. Hashes detect accidental corruption only; they are not signatures or authentication. A mutator that recomputes hashes is an explicitly out-of-scope adversary and is reported separately from channel damage.

Implementation: [monitor.py](../src/axiom/monitor.py), [trace.py](../src/axiom/trace.py). Tests exercise all properties and three-valued cases in `tests/test_trace_monitor.py`.
