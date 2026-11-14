"""Mission-scenario assessment and next-experiment planning.

The scenario is compared with deterministic condition metadata extracted from the
ingested corpus. No language model participates in classification, coverage
arithmetic, gap identification, proposal generation or the critic pass.

An assessment is an evidence-applicability report. It is not a fire-risk
prediction and it is not a safety certification.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .applicability import summarize as summarize_applicability
from .experiment_metadata import investigations
from .research import load_chunks
from .run_records import save_scenario
from .transferability import (
    FIELDS, FIELD_LABELS, INTERESTS, NUMERIC_FIELDS, UNITS,
    assess as compare_all, audit, identify_gaps, normalize_scenario, propose, validate_interest,
)

MAX_DESCRIPTION = 2000
REQUEST_KEYS = {"scenario", "description", "interest", "save"}
SCHEMA_VERSION = "scenario-assessment-v2"

PRESETS = [
    {
        "preset_id": "cabin-fabric",
        "label": "Crew cabin · fabric sample",
        "synthetic": True,
        "basis": "Values appear in the ingested corpus. The combination is a synthetic demonstration scenario, not a mission specification.",
        "scenario": {"gravity": "microgravity", "fuel": "sibal fabric", "geometry": "fabric sheet",
                     "oxygen_percent": {"value": 21, "unit": "%"},
                     "pressure_kpa": {"value": 101.325, "unit": "kPa"},
                     "flow_cm_s": {"value": 20, "unit": "cm/s"}},
        "interest": "flame_spread",
        "description": "A fabric sheet in a crew cabin atmosphere with a low forced airflow.",
    },
    {
        "preset_id": "low-pressure-thermoplastic",
        "label": "Low-pressure thermoplastic",
        "synthetic": True,
        "basis": "Oxygen and airflow values appear in the ingested corpus. Pressure is left unknown on purpose; the combination is synthetic.",
        "scenario": {"gravity": "microgravity", "fuel": "thermoplastic", "geometry": "thick sample",
                     "oxygen_percent": {"value": 29, "unit": "%"},
                     "flow_cm_s": {"value": 20, "unit": "cm/s"}},
        "interest": "fire_growth",
        "description": "A thick thermoplastic sample in an oxygen-enriched atmosphere; pressure is not specified.",
    },
    {
        "preset_id": "ground-pmma-rod",
        "label": "Ground comparison · PMMA rod",
        "synthetic": True,
        "basis": "Values appear in the ingested ground-comparison paper. The combination is synthetic.",
        "scenario": {"gravity": "terrestrial", "fuel": "PMMA", "geometry": "rod",
                     "oxygen_percent": {"value": 18, "unit": "%"},
                     "pressure_kpa": {"value": 101.325, "unit": "kPa"},
                     "flow_cm_s": {"value": 5, "unit": "cm/s"}},
        "interest": "flame_spread",
        "description": "A PMMA rod burning in normal gravity at a reduced oxygen concentration.",
    },
]


def _validated(request):
    if not isinstance(request, dict):
        raise ValueError("Expected a JSON object")
    unknown = set(request) - REQUEST_KEYS
    if unknown:
        raise ValueError("Unsupported request field: " + ", ".join(sorted(unknown)))
    description = request.get("description", "")
    if not isinstance(description, str):
        raise ValueError("description must be text")
    description = " ".join(description.split())
    if len(description) > MAX_DESCRIPTION:
        raise ValueError(f"description exceeds {MAX_DESCRIPTION} characters")
    if type(request.get("save", True)) is not bool:
        raise ValueError("save must be boolean")
    target, original = normalize_scenario(request.get("scenario", {}))
    interest = validate_interest(request.get("interest"))
    return target, original, description, interest, request.get("save", True)


def _catalog(chunks, groups):
    documented = {}
    for group in groups:
        for record in group["records"]:
            if not record["matching_eligible"]:
                continue
            documented.setdefault(record["field"], {})[(repr(record["value"]), record["unit"])] = {
                "value": record["value"], "unit": record["unit"],
                "investigation": group["investigation_id"], "source_id": record["source_id"],
            }
    values = {field: sorted(rows.values(), key=lambda row: (str(row["value"]), row["investigation"]))[:40]
              for field, rows in documented.items()}
    return {
        "fields": [{"field": field, "label": FIELD_LABELS[field],
                    "type": "numeric" if field in NUMERIC_FIELDS else "text",
                    "units": sorted(UNITS[field]) if field in NUMERIC_FIELDS else [],
                    "canonical_unit": NUMERIC_FIELDS.get(field),
                    "documented_values": values.get(field, [])} for field in FIELDS],
        "interests": [{"value": key, "label": label} for key, label in INTERESTS.items()],
        "presets": PRESETS,
        "corpus": {
            "documents": len({chunk["source_id"] for chunk in chunks}),
            "passages": len(chunks),
            "investigations": [{"investigation_id": group["investigation_id"], "label": group["label"],
                                "domain": group["domain"],
                                "behaviors": group["behaviors"]} for group in groups],
            "condition_records": sum(len(group["records"]) for group in groups),
            "extraction": "deterministic_pattern_v1",
            "review_status": "machine_extracted_not_human_reviewed",
        },
        "notices": [
            "Documented values are suggestions from the available corpus, not required inputs.",
            "Blank fields remain unknown. Unknown is never treated as a match.",
            "The scenario is compared with an available corpus, not with all NASA research.",
        ],
    }


def catalog(root):
    chunks = load_chunks(root)
    return _catalog(chunks, investigations(chunks))


def assess(root, request, save_root=None):
    target, original, description, interest, should_save = _validated(request)
    chunks = load_chunks(root)
    groups = investigations(chunks)
    if not groups:
        raise ValueError("No corpus condition records are available. Run python -m axiom ingest first.")
    result = compare_all(target, groups, interest)
    engine = summarize_applicability({**result, "target": target})
    gaps = identify_gaps(target, result["investigations"])
    proposals = propose(gaps, target, interest, result["investigations"])
    critic = audit({**result, "target": target, "gaps": gaps, "proposals": proposals})
    scenario_id = uuid4().hex
    assessment = {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": scenario_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "interest": interest,
        "interest_label": INTERESTS.get(interest),
        "target": target,
        "scenario_input": original,
        "assessment_scope": ("Evidence applicability against documented experimental conditions. "
                             "Not a fire-risk prediction, safety certification or operational recommendation."),
        "comparison_method": (
            "Deterministic unit conversion, explicit alias table for categorical terms, and four fixed "
            "classifications. Exact equality after conversion is an exact match; containment in a reported "
            "test range is a partial match; different qualified values are a mismatch; an absent or "
            "unqualified value is unknown. No similarity score, tolerance or model judgement is used."),
        "matching_policy": (
            "Only reported test-condition records are eligible. Planned matrices, background remarks, "
            "apparatus capabilities and limit outcomes remain visible but cannot produce a match. "
            "A range's endpoints are not treated as tested values unless separately reported."),
        "retrieval": {
            "mode": "corpus_condition_census",
            "description": ("Every ingested investigation with extracted conditions is compared. This is not a "
                            "relevance-ranked retrieval step, so no lexical relevance is implied."),
            "investigations_compared": len(groups),
            "investigations_without_metadata": [],
            "documents": sorted({chunk["source_id"] for chunk in chunks}),
            "passages": len(chunks),
        },
        "corpus_scope": {
            "documents": len({chunk["source_id"] for chunk in chunks}),
            "passages": len(chunks),
            "condition_records": sum(len(group["records"]) for group in groups),
            "extraction": "deterministic_pattern_v1",
            "review_status": "machine_extracted_not_human_reviewed",
            "notice": ("The corpus contains 12 ingested NASA documents. A condition absent here may exist in "
                       "another NASA publication, report or data archive. Absence is not a negative result."),
        },
        **result,
        "applicability_engine": engine,
        "gaps": gaps,
        "proposals": proposals,
        "safety_critic": critic,
        "steps": [
            {"label": "Parse the scenario", "detail": f"{len(target)} specified parameter(s); "
                                                     f"{len(FIELDS) - len(target)} left unknown."},
            {"label": "Compare documented conditions",
             "detail": f"{len(result['investigations'])} investigation(s) compared on "
                       f"{result['coverage']['denominator']} parameter cells."},
            {"label": "Identify evidence gaps",
             "detail": f"{len(gaps)} parameter gap(s) classified by documentation status."},
            {"label": "Evaluate documented-scope applicability",
             "detail": f"AXIOM engine: {engine['overall']} over "
                       f"{len(engine.get('specified_fields', []))} specified field(s)."},
            {"label": "Audit generated statements",
             "detail": f"Safety Critic: {critic['summary']['withheld']} withheld, "
                       f"{critic['summary']['qualified']} qualified, {critic['summary']['supported']} supported."},
            {"label": "Plan next experiments",
             "detail": f"{len(proposals)} proposed research concept(s); none has been executed."},
        ],
        "notices": [
            "Every displayed value links to a passage, chunk and source identifier.",
            "Proposed experiments are AXIOM research concepts and require qualified scientific and facility-safety review.",
            "No aggregate confidence or fire-risk score is produced.",
        ],
    }
    assessment["saved_locally"] = True
    if should_save:
        try:
            save_scenario(save_root if save_root is not None else root, assessment)
        except (OSError, ValueError) as exc:
            assessment["saved_locally"] = False
            assessment["save_error"] = str(exc)
    else:
        assessment["saved_locally"] = False
    return assessment


def plan(root, request, record_root=None):
    """Return proposals from a stored assessment, optionally filtered by gap."""
    if not isinstance(request, dict) or set(request) - {"scenario_id", "gap_ids"}:
        raise ValueError("Expected scenario_id and optional gap_ids")
    from .run_records import load_scenario
    identifier = request.get("scenario_id")
    if not isinstance(identifier, str):
        raise ValueError("scenario_id is required")
    assessment = load_scenario(record_root if record_root is not None else root, identifier)
    gap_ids = request.get("gap_ids")
    if gap_ids is not None:
        if not isinstance(gap_ids, list) or any(not isinstance(value, str) for value in gap_ids):
            raise ValueError("gap_ids must be a list of strings")
        proposals = [row for row in assessment.get("proposals", []) if row.get("gap_id") in gap_ids]
        gaps = [row for row in assessment.get("gaps", []) if row.get("gap_id") in gap_ids]
    else:
        proposals, gaps = assessment.get("proposals", []), assessment.get("gaps", [])
    return {
        "schema_version": SCHEMA_VERSION,
        "scenario_id": identifier,
        "reused_assessment": True,
        "target": assessment.get("target"),
        "interest": assessment.get("interest"),
        "gaps": gaps,
        "proposals": proposals,
        "label": "AXIOM PROPOSED RESEARCH CONCEPTS — NOT EXECUTED OR VALIDATED",
        "notice": ("Reused from the saved assessment without a new retrieval or generation step. "
                   "Proposals require qualified scientific and facility-safety review."),
    }
