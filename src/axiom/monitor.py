"""Independent three-valued runtime monitor over AXIOM execution traces.

The monitor is deterministic code. A language model never decides a verdict. It
consumes the trust classification from ``trace.integrity`` and evaluates the
versioned property registry below over a finite, terminated run.

Verdict rules
-------------
``FAIL``    A violating observation is itself trusted. A complete run is required
           for an *absence* violation; if the run is incomplete, a missing
           required event can be a lost observation, so the verdict is UNKNOWN.
``PASS``    Every required event is present, trusted and the run is complete.
``UNKNOWN``Anything else: untrusted observation, incomplete run, unusable
           sequence numbers or missing prerequisite events.

Aggregate: FAIL if any mandatory property fails, else UNKNOWN if any is unknown,
else PASS. The output policy is fixed and documented: PASS -> published as
verified, UNKNOWN -> published with an explicit unverified label, FAIL ->
withheld.
"""
from __future__ import annotations

from .trace import EVENT_TYPES, integrity

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
_RANK = {PASS: 0, UNKNOWN: 1, FAIL: 2}
MANDATORY = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8")

# Versioned registry. ``kind`` distinguishes safety-style properties that can
# fail early from properties that need the run-end manifest.
PROPERTY_REGISTRY = (
    {
        "id": "P1", "version": 1, "name": "Evidence provenance", "kind": "safety",
        "required_events": ["EVIDENCE_RETRIEVED", "CLAIM_LINKED_TO_EVIDENCE", "CLAIM_PUBLISHED"],
        "definition": ("Every evidence identifier referenced by a trusted claim link, verification "
                       "or publication resolves to an EVIDENCE_RETRIEVED event in the same run."),
        "pass_condition": "No referenced identifier is missing from the trusted retrieval set.",
        "fail_condition": "A trusted event references an identifier that no retrieval event contains.",
        "unknown_condition": "No retrieval event is trusted, so the reference set cannot be checked.",
    },
    {
        "id": "P2", "version": 1, "name": "Verification after required checks", "kind": "safety",
        "required_events": ["METADATA_VALIDATED", "APPLICABILITY_CHECKED", "CLAIM_VERIFIED"],
        "definition": ("A claim is verified as supported only after a trusted metadata validation and "
                       "an applicability check for that claim that returned WITHIN_DOCUMENTED_SCOPE."),
        "pass_condition": "Every supported verification has both prerequisites, earlier in the run.",
        "fail_condition": "A supported verification has no applicability check, no metadata validation, or both exist after it.",
        "unknown_condition": "Sequence numbers are unusable or the run is incomplete, so a missing prerequisite may be a lost observation.",
    },
    {
        "id": "P3", "version": 1, "name": "Verification covers the presented version", "kind": "end_of_run",
        "required_events": ["CLAIM_VERIFIED", "CLAIM_PUBLISHED"],
        "definition": ("A publication refers to the same claim, evidence set, scenario version and "
                       "metadata version that the verification used. A later change invalidates the "
                       "verification rather than silently reusing it."),
        "pass_condition": "Every published claim with a verification agrees on all four identifiers.",
        "fail_condition": "A published claim carries a scenario version, metadata version or evidence set that the verification did not cover.",
        "unknown_condition": "A verification event is untrusted or ordering cannot be reconstructed.",
    },
    {
        "id": "P4", "version": 1, "name": "No scope claim against a contradiction", "kind": "end_of_run",
        "required_events": ["APPLICABILITY_CHECKED", "CLAIM_VERIFIED"],
        "definition": ("For one scenario version, no claim is verified as WITHIN_DOCUMENTED_SCOPE while a "
                       "trusted applicability check reports CONDITION_MISMATCH or CONFLICTING_EVIDENCE."),
        "pass_condition": "Either no scope claim exists or no contradicting check exists for that scenario version.",
        "fail_condition": "A scope claim and a contradicting check share a scenario version.",
        "unknown_condition": "The relevant checks are untrusted or the run is incomplete.",
    },
    {
        "id": "P5", "version": 1, "name": "Uncertainty never read as success", "kind": "end_of_run",
        "required_events": ["CLAIM_VERIFIED", "CLAIM_WITHHELD", "CLAIM_PUBLISHED"],
        "definition": ("A publication labelled verified requires a trusted verification marked supported "
                       "over the same evidence set. An unverified, withheld or absent verification must "
                       "never yield a verified label, and a withheld claim is never published."),
        "pass_condition": "Every verified publication has a matching supported verification and no withheld claim is published.",
        "fail_condition": "A verified label rests on an unverified, withheld or absent verification, an evidence set differs, or a withheld claim was published.",
        "unknown_condition": "The verification event is untrusted or the run is incomplete.",
    },
    {
        "id": "P6", "version": 1, "name": "Citations resolve to retrieved records", "kind": "end_of_run",
        "required_events": ["EVIDENCE_RETRIEVED", "CLAIM_LINKED_TO_EVIDENCE", "CLAIM_PUBLISHED"],
        "definition": ("Every citation presented with a published claim resolves to a source record "
                       "retrieved in the same run."),
        "pass_condition": "All cited identifiers are in the trusted retrieval set.",
        "fail_condition": "A published claim cites an identifier that was never retrieved.",
        "unknown_condition": "The retrieval event is untrusted or the run is incomplete.",
    },
    {
        "id": "P7", "version": 1, "name": "Duplicate events are classified", "kind": "safety",
        "required_events": ["EVIDENCE_RETRIEVED"],
        "definition": ("An identical duplicate event is idempotently discarded and noted. A conflicting "
                       "duplicate, where one event identifier maps to different content, makes the event "
                       "untrusted. A hash mismatch means content cannot be trusted."),
        "pass_condition": "No duplicate event identifier carries conflicting content and every hash matches.",
        "fail_condition": "A duplicate event identifier carries conflicting content.",
        "unknown_condition": "A content hash does not match, so trust in observed content cannot be established.",
    },
    {
        "id": "P8", "version": 1, "name": "Publication does not precede verification", "kind": "end_of_run",
        "required_events": ["CLAIM_VERIFIED", "CLAIM_PUBLISHED"],
        "definition": ("When sequence numbers are usable, a publication for a claim occurs after the "
                       "verification it relies on. Delivery order alone is not trusted; the sequence "
                       "number is authoritative."),
        "pass_condition": "Every publication follows its verification in sequence order.",
        "fail_condition": "A publication precedes the verification it relies on.",
        "unknown_condition": "Sequence numbers are missing or duplicated, so order cannot be reconstructed.",
    },
)

OUTPUT_POLICY = {
    "PASS": "published as verified",
    "UNKNOWN": "published with an explicit unverified label",
    "FAIL": "withheld",
    "note": ("The policy is fixed before measurement and applied unchanged. It does not make a "
             "published claim true; it records what the monitor could establish about the process."),
}


def _worst(verdicts):
    return max(verdicts, key=lambda verdict: _RANK[verdict], default=PASS)


def _result(property_id, verdict, reason, claim_id=None, event_ids=(), missing=(),
            counterexamples=(), explanation=None):
    return {
        "property": property_id,
        "scope": claim_id or "run",
        "claim_id": claim_id,
        "verdict": verdict,
        "reason": reason,
        "event_ids": list(event_ids),
        "missing_observations": list(missing),
        "counterexamples": list(counterexamples),
        "explanation": explanation or reason,
    }


def _registry_entry(property_id):
    return next(row for row in PROPERTY_REGISTRY if row["id"] == property_id)


def _claim_ids(events):
    ids = []
    for event in events:
        claim_id = event.get("claim_id")
        if claim_id and claim_id not in ids:
            ids.append(claim_id)
    return ids


class _Context:
    def __init__(self, trace, integrity_layer=True):
        self.trace = trace
        self.integrity_layer = integrity_layer
        if integrity_layer:
            self.integrity = integrity(trace)
            self.events = self.integrity["trusted"]
            self.flags = self.integrity["flags"]
        else:
            # Ablation: trust the channel completely and use delivery order as if it
            # were the sequence. This is what a monitor without an integrity layer
            # sees; it is never the production path.
            events = []
            for index, event in enumerate(trace.get("events") or []):
                if not isinstance(event, dict) or event.get("type") not in EVENT_TYPES:
                    continue
                row = {key: value for key, value in event.items() if key != "content_hash"}
                row["seq"] = index + 1
                events.append(row)
            self.events = events
            self.flags = {
                "gap_detected": False, "duplicate_identical": [],
                "duplicate_conflicting": [], "hash_mismatch": [], "malformed": [],
                "delivery_order_reliable": True, "seq_usable": True, "seq_unique": True,
                "ordering_unreliable": False, "ordering_recoverable": True,
                "run_incomplete": False,
            }
            self.integrity = {"schema_version": "axiom-integrity-v1",
                              "events_observed": len(events), "events_trusted": len(events),
                              "trusted": events, "discarded_duplicates": [],
                              "flags": self.flags, "manifest": trace.get("manifest"),
                              "notices": ["Integrity layer disabled for ablation."]}
        self.complete = not self.flags["run_incomplete"]
        self.order_ok = self.flags["ordering_recoverable"]
        self.by_type = {}
        for event in self.events:
            self.by_type.setdefault(event["type"], []).append(event)
        self.claims = _claim_ids(self.events)
        self.untrusted_types = {
            row.get("type") for row in
            (self.flags["hash_mismatch"] + self.flags["malformed"]
             + self.flags["duplicate_conflicting"])
            if row.get("type")
        }

    def typed(self, event_type):
        return self.by_type.get(event_type, [])

    def for_claim(self, event_type, claim_id):
        return [event for event in self.typed(event_type) if event.get("claim_id") == claim_id]

    def retrieved(self):
        return {identifier for event in self.typed("EVIDENCE_RETRIEVED")
                for identifier in event.get("evidence_ids") or []}

    def complete_or_unknown(self, verdict_on_absence):
        """Absence is a FAIL only in a complete run, otherwise UNKNOWN."""
        return verdict_on_absence if self.complete else UNKNOWN


def _p1(ctx):
    retrievals = ctx.typed("EVIDENCE_RETRIEVED")
    references = {}
    for event_type in ("CLAIM_LINKED_TO_EVIDENCE", "CLAIM_VERIFIED", "CLAIM_PUBLISHED"):
        for event in ctx.typed(event_type):
            for identifier in event.get("evidence_ids") or []:
                references.setdefault(identifier, []).append(event["event_id"])
    if not retrievals:
        return [_result("P1", UNKNOWN,
                        "No EVIDENCE_RETRIEVED event is trusted, so provenance cannot be checked.",
                        missing=["EVIDENCE_RETRIEVED"],
                        explanation="The retrieval record is missing or untrusted; provenance is unknown, not satisfied.")]
    retrieved = ctx.retrieved()
    dangling = {identifier: ids for identifier, ids in references.items()
                if identifier not in retrieved}
    if dangling:
        return [_result("P1", FAIL,
                        f"{len(dangling)} referenced evidence identifier(s) never appear in the retrieval event.",
                        event_ids=[event_id for ids in dangling.values() for event_id in ids],
                        counterexamples=sorted(dangling),
                        explanation="A trusted event cites evidence that this run never retrieved.")]
    return [_result("P1", PASS, "Every referenced evidence identifier resolves to the retrieval event.")]


def _p2(ctx):
    results = []
    for claim_id in ctx.claims:
        verifications = [event for event in ctx.for_claim("CLAIM_VERIFIED", claim_id)
                         if event.get("verdict") == "supported"]
        if not verifications:
            continue
        checks = ctx.for_claim("APPLICABILITY_CHECKED", claim_id)
        scoped = [event for event in checks
                  if event.get("outcome") == "WITHIN_DOCUMENTED_SCOPE"]
        validations = ctx.typed("METADATA_VALIDATED")
        missing = []
        counterexamples = []
        verdict = PASS
        for verification in verifications:
            required = verification.get("required_checks") or [
                "METADATA_VALIDATED", "APPLICABILITY_CHECKED"]
            if "APPLICABILITY_CHECKED" in required:
                if not scoped:
                    missing.append("APPLICABILITY_CHECKED[WITHIN_DOCUMENTED_SCOPE]")
                    verdict = _worst([verdict, ctx.complete_or_unknown(FAIL)])
                elif ctx.order_ok and min(event["seq"] for event in scoped) > verification["seq"]:
                    verdict = _worst([verdict, FAIL])
                    counterexamples.append(verification["event_id"])
            if "METADATA_VALIDATED" in required:
                if not validations:
                    missing.append("METADATA_VALIDATED")
                    verdict = _worst([verdict, ctx.complete_or_unknown(FAIL)])
                elif ctx.order_ok and min(event["seq"] for event in validations) > verification["seq"]:
                    verdict = _worst([verdict, FAIL])
                    counterexamples.append(verification["event_id"])
            if not ctx.order_ok:
                verdict = _worst([verdict, UNKNOWN])
        reason = ("Supported verification has its metadata validation and a within-scope applicability "
                  "check before it." if verdict == PASS
                  else "A supported verification is missing a required earlier check.")
        results.append(_result("P2", verdict, reason, claim_id=claim_id,
                               event_ids=[event["event_id"] for event in verifications],
                               missing=missing, counterexamples=sorted(set(counterexamples)),
                               explanation=("Absence of a required check is a violation in a complete run; "
                                            "in an incomplete run it is a lost observation and the verdict is unknown."
                                            if verdict != PASS else None)))
    return results


def _p3(ctx):
    results = []
    for claim_id in ctx.claims:
        publications = ctx.for_claim("CLAIM_PUBLISHED", claim_id)
        verifications = ctx.for_claim("CLAIM_VERIFIED", claim_id)
        if not publications:
            continue
        if not verifications:
            results.append(_result("P3", UNKNOWN,
                                   "No trusted verification exists to compare with the publication.",
                                   claim_id=claim_id,
                                   missing=["CLAIM_VERIFIED"],
                                   explanation="Version coverage cannot be established without a verification."))
            continue
        latest = max(verifications, key=lambda event: event.get("seq", 0))
        verdict, counterexamples = PASS, []
        for publication in publications:
            for key in ("scenario_version", "metadata_version"):
                if publication.get(key) != latest.get(key):
                    verdict = FAIL
                    counterexamples.append({
                        "event_id": publication["event_id"],
                        "field": key,
                        "published": publication.get(key),
                        "verified": latest.get(key)})
            if set(publication.get("evidence_ids") or []) != set(latest.get("evidence_ids") or []):
                verdict = FAIL
                counterexamples.append({
                    "event_id": publication["event_id"], "field": "evidence_ids",
                    "published": sorted(publication.get("evidence_ids") or []),
                    "verified": sorted(latest.get("evidence_ids") or [])})
        if not ctx.order_ok and verdict == FAIL:
            verdict = UNKNOWN
        results.append(_result("P3", verdict,
                               ("Publication matches the verified scenario, metadata and evidence set."
                                if verdict == PASS else
                                "The publication presents a version that the verification did not cover."),
                               claim_id=claim_id,
                               event_ids=[event["event_id"] for event in publications],
                               counterexamples=counterexamples,
                               explanation=("A change after verification invalidates the verification instead "
                                            "of being reused silently." if verdict == FAIL else None)))
    return results


def _p4(ctx):
    verifications = [event for event in ctx.typed("CLAIM_VERIFIED")
                     if event.get("applicability_outcome") == "WITHIN_DOCUMENTED_SCOPE"]
    contradictions = [event for event in ctx.typed("APPLICABILITY_CHECKED")
                      if event.get("outcome") in ("CONDITION_MISMATCH", "CONFLICTING_EVIDENCE")]
    if not verifications:
        return [_result("P4", PASS, "No claim was verified as within documented scope.")]
    if not contradictions:
        return [_result("P4", PASS, "No trusted applicability check contradicts a scope claim.")]
    results = []
    for verification in verifications:
        same_version = [event for event in contradictions
                        if event.get("scenario_version") == verification.get("scenario_version")
                        and event.get("claim_id") == verification.get("claim_id")]
        if same_version:
            results.append(_result("P4", FAIL,
                                   "A scope claim shares a scenario version with a contradicting check.",
                                   claim_id=verification.get("claim_id"),
                                   event_ids=[verification["event_id"]] +
                                             [event["event_id"] for event in same_version],
                                   counterexamples=[event["event_id"] for event in same_version],
                                   explanation="The same scenario version cannot be both within scope and contradicted."))
        else:
            results.append(_result("P4", PASS,
                                   "Contradicting checks belong to a different claim or scenario version.",
                                   claim_id=verification.get("claim_id")))
    return results


def _p5(ctx):
    results = []
    for claim_id in ctx.claims:
        publications = ctx.for_claim("CLAIM_PUBLISHED", claim_id)
        verifications = ctx.for_claim("CLAIM_VERIFIED", claim_id)
        withheld = ctx.for_claim("CLAIM_WITHHELD", claim_id)
        if not publications and not withheld:
            continue
        if withheld and publications:
            results.append(_result("P5", FAIL,
                                   "A claim recorded as withheld was also published.",
                                   claim_id=claim_id,
                                   event_ids=[event["event_id"] for event in withheld + publications],
                                   counterexamples=[event["event_id"] for event in publications],
                                   explanation="Withholding must remove the claim from the published set."))
            continue
        verified_publications = [event for event in publications
                                 if event.get("label") == "verified"]
        if not verified_publications:
            results.append(_result("P5", PASS,
                                   "No publication claims a verified label.",
                                   claim_id=claim_id))
            continue
        verdict, missing, counterexamples = PASS, [], []
        for publication in verified_publications:
            matching = [event for event in verifications
                        if event.get("verdict") == "supported"
                        and set(event.get("evidence_ids") or []) == set(publication.get("evidence_ids") or [])]
            if matching:
                continue
            if not verifications:
                missing.append("CLAIM_VERIFIED[supported]")
                verdict = _worst([verdict, ctx.complete_or_unknown(FAIL)])
                counterexamples.append(publication["event_id"])
            else:
                verdict = FAIL
                counterexamples.append(publication["event_id"])
        reason = ("Every verified publication rests on a matching supported verification."
                  if verdict == PASS else
                  "A verified label rests on a verification that is absent, unsupported or covers another evidence set.")
        results.append(_result("P5", verdict, reason, claim_id=claim_id,
                               event_ids=[event["event_id"] for event in verified_publications],
                               missing=missing, counterexamples=sorted(set(counterexamples))))
    return results


def _p6(ctx):
    results = []
    for claim_id in ctx.claims:
        publications = ctx.for_claim("CLAIM_PUBLISHED", claim_id)
        if not publications:
            continue
        cited = set()
        for event in ctx.for_claim("CLAIM_LINKED_TO_EVIDENCE", claim_id):
            cited.update(event.get("evidence_ids") or [])
            for citation in event.get("citations") or []:
                if citation.get("chunk_id"):
                    cited.add(citation["chunk_id"])
        for event in publications:
            cited.update(event.get("evidence_ids") or [])
        if not ctx.typed("EVIDENCE_RETRIEVED"):
            results.append(_result("P6", UNKNOWN,
                                   "No trusted retrieval event exists, so citations cannot be resolved.",
                                   claim_id=claim_id, missing=["EVIDENCE_RETRIEVED"]))
            continue
        dangling = sorted(cited - ctx.retrieved())
        if dangling:
            results.append(_result("P6", FAIL,
                                   "A published claim cites records that were not retrieved in this run.",
                                   claim_id=claim_id,
                                   event_ids=[event["event_id"] for event in publications],
                                   counterexamples=dangling))
        else:
            results.append(_result("P6", PASS,
                                   "Every presented citation resolves to a retrieved record.",
                                   claim_id=claim_id))
    return results


def _p7(ctx):
    flags = ctx.flags
    if flags["duplicate_conflicting"]:
        return [_result("P7", FAIL,
                        "Duplicate event identifiers carry conflicting content.",
                        event_ids=sorted({row["event_id"] for row in flags["duplicate_conflicting"]}),
                        counterexamples=flags["duplicate_conflicting"],
                        explanation="One event identifier maps to two different payloads, so neither copy is trusted.")]
    if flags["hash_mismatch"]:
        return [_result("P7", UNKNOWN,
                        "A content hash does not match its payload, so content trust cannot be established.",
                        event_ids=[row["event_id"] for row in flags["hash_mismatch"]],
                        counterexamples=flags["hash_mismatch"],
                        explanation="Accidental corruption is indistinguishable from an untrusted observation.")]
    if flags["malformed"]:
        return [_result("P7", UNKNOWN,
                        "A malformed or hash-less event cannot be verified.",
                        counterexamples=flags["malformed"])]
    if flags["duplicate_identical"]:
        return [_result("P7", PASS,
                        "Identical duplicates were discarded idempotently and noted.",
                        counterexamples=flags["duplicate_identical"],
                        explanation="An exact duplicate adds no new information and does not change the verdict.")]
    return [_result("P7", PASS, "No duplicate event identifier and no hash mismatch.")]


def _p8(ctx):
    results = []
    for claim_id in ctx.claims:
        publications = ctx.for_claim("CLAIM_PUBLISHED", claim_id)
        verifications = ctx.for_claim("CLAIM_VERIFIED", claim_id)
        if not publications or not verifications:
            continue
        if not ctx.order_ok:
            results.append(_result("P8", UNKNOWN,
                                   "Sequence numbers are missing or duplicated, so publication order cannot be reconstructed.",
                                   claim_id=claim_id, missing=["usable seq"]))
            continue
        first_verification = min(event["seq"] for event in verifications)
        early = [event for event in publications if event["seq"] < first_verification]
        if early:
            results.append(_result("P8", FAIL,
                                   "A publication precedes the verification it relies on.",
                                   claim_id=claim_id,
                                   event_ids=[event["event_id"] for event in early],
                                   counterexamples=[event["event_id"] for event in early],
                                   explanation="Sequence numbers, not delivery order, show publication before verification."))
        else:
            results.append(_result("P8", PASS,
                                   "Publication follows verification in sequence order.",
                                   claim_id=claim_id))
    return results


_EVALUATORS = {"P1": _p1, "P2": _p2, "P3": _p3, "P4": _p4, "P5": _p5, "P6": _p6,
               "P7": _p7, "P8": _p8}


def evaluate(trace, integrity_layer=True):
    """Return per-property, per-claim and aggregate verdicts plus the output policy."""
    ctx = _Context(trace, integrity_layer=integrity_layer)
    claim_results, run_results, property_results = {}, [], {}
    for property_id in MANDATORY:
        rows = _EVALUATORS[property_id](ctx)
        if not rows:
            rows = [_result(property_id, PASS, "No observation is in scope for this property.")]
        required = set(_registry_entry(property_id)["required_events"])
        guarded = []
        for row in rows:
            blocked = sorted(required & ctx.untrusted_types)
            if row["verdict"] == PASS and blocked:
                row = {**row, "verdict": UNKNOWN,
                       "reason": ("A required observation type has an untrusted instance, so a pass "
                                  "cannot be established: " + ", ".join(blocked) + "."),
                       "missing_observations": list(row["missing_observations"]) + blocked,
                       "explanation": ("Pass requires every required observation to be present and trusted. "
                                       "The channel delivered an untrusted instance, so the verdict is unknown.")}
            guarded.append(row)
        rows = guarded
        for row in rows:
            if row["claim_id"]:
                claim_results.setdefault(row["claim_id"], []).append(row)
            else:
                run_results.append(row)
        property_results[property_id] = {
            "registry": _registry_entry(property_id),
            "verdict": _worst([row["verdict"] for row in rows]),
            "results": rows,
        }

    claims = {}
    for claim_id in ctx.claims:
        rows = list(claim_results.get(claim_id, []))
        rows += [row for row in run_results if row["property"] in ("P1", "P7")]
        if not rows:
            rows = [_result("P1", PASS, "No observation is in scope for this claim.")]
        overall = _worst([row["verdict"] for row in rows])
        claims[claim_id] = {
            "verdict": overall,
            "policy": OUTPUT_POLICY[overall],
            "properties": rows,
            "failed_properties": sorted({row["property"] for row in rows if row["verdict"] == FAIL}),
            "unknown_properties": sorted({row["property"] for row in rows if row["verdict"] == UNKNOWN}),
        }

    overall = _worst([row["verdict"] for row in property_results.values()])
    explanation = []
    for property_id in MANDATORY:
        row = property_results[property_id]
        if row["verdict"] == PASS:
            continue
        entry = row["registry"]
        explanation.append(
            f"{property_id} {entry['name']} is {row['verdict']}: " +
            "; ".join(result["reason"] for result in row["results"]
                      if result["verdict"] == row["verdict"])[:400])
    return {
        "schema_version": "axiom-monitor-v1",
        "run_id": trace.get("run_id"),
        "integrity_layer": integrity_layer,
        "trust": {key: value for key, value in ctx.integrity.items()
                  if key not in ("trusted",)},
        "trusted_event_count": len(ctx.events),
        "properties": [property_results[property_id] for property_id in MANDATORY],
        "claims": claims,
        "overall": overall,
        "output_policy": OUTPUT_POLICY,
        "explanation": explanation,
        "scope": ("Process properties over a finite terminated run. The monitor does not judge whether a "
                  "source semantically supports a claim, so a mis-linked claim can pass."),
    }
