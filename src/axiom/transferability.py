"""Deterministic scenario applicability comparison.

This module turns a user scenario and documented experimental metadata into an
explicit comparison. It contains no model call and no similarity score. The
four classifications are deliberately narrow:

* ``exact_match``   - a reported value equals the scenario value after unit
                      normalisation, or a canonical categorical value is the same.
* ``partial_match`` - the scenario value lies inside a reported test range. Range
                      membership is not experimental equivalence.
* ``mismatch``      - reported values differ materially from the scenario value.
* ``unknown``       - no qualified reported value exists in the available corpus.

``unknown`` is never rewritten as a match. An unreported condition is also not
proof that an experiment was never conducted; it means this corpus does not
document it.

Coverage percentages count documentation cells only. They are not confidence,
probability of ignition, or a safety measure.
"""
from __future__ import annotations

import re

FIELDS = ("gravity", "fuel", "geometry", "apparatus", "oxygen_percent",
          "pressure_kpa", "flow_cm_s", "temperature_k", "ignition", "suppression")
NUMERIC_FIELDS = {"oxygen_percent": "%", "pressure_kpa": "kPa", "flow_cm_s": "cm/s",
                  "temperature_k": "K"}
TEXT_FIELDS = tuple(field for field in FIELDS if field not in NUMERIC_FIELDS)
UNITS = {
    "oxygen_percent": {"%": 1.0, "percent": 1.0},
    "pressure_kpa": {"kPa": 1.0, "Pa": 0.001, "atm": 101.325, "bar": 100.0,
                     "psi": 6.89476, "torr": 0.133322, "mmHg": 0.133322},
    "flow_cm_s": {"cm/s": 1.0, "mm/s": 0.1, "m/s": 100.0},
    # Temperature is the one affine conversion: value * scale + offset.
    "temperature_k": {"K": 1.0, "°C": 1.0, "C": 1.0, "°F": 5 / 9, "F": 5 / 9},
}
UNIT_OFFSETS = {
    "temperature_k": {"K": 0.0, "°C": 273.15, "C": 273.15,
                      "°F": 273.15 - 32 * 5 / 9, "F": 273.15 - 32 * 5 / 9},
}
FIELD_LABELS = {
    "gravity": "gravity regime",
    "fuel": "fuel or material",
    "geometry": "fuel geometry",
    "apparatus": "apparatus",
    "oxygen_percent": "oxygen concentration",
    "pressure_kpa": "pressure",
    "flow_cm_s": "airflow speed",
    "temperature_k": "temperature",
    "ignition": "ignition method",
    "suppression": "suppression method",
}
INTERESTS = {
    "ignition": "ignition",
    "flame_spread": "flame spread",
    "extinction": "extinction",
    "flame_growth": "flame growth",
    "fire_growth": "fire growth",
    "burning_rate": "burning rate",
    "material_flammability": "material flammability",
}
BEHAVIOR_LABELS = {
    "ignition": "ignition",
    "flame_spread": "flame spread",
    "extinction": "extinction",
    "flame_growth": "flame growth",
    "fire_growth": "fire growth",
    "burning_rate": "burning rate",
    "material_flammability": "material flammability",
}
DEPENDENT_VARIABLES = {
    "ignition": ["ignition occurrence", "ignition delay", "ignition location"],
    "flame_spread": ["flame spread rate", "flame length", "spread direction"],
    "extinction": ["extinction limit", "extinction time", "limiting oxygen condition"],
    "flame_growth": ["flame size over time", "flame growth rate"],
    "fire_growth": ["flame size over time", "heat release indicators where measurable",
                    "temperature and species measurements"],
    "burning_rate": ["burning rate", "mass-loss rate"],
    "material_flammability": ["flammability boundary", "ignition and spread behavior"],
}

# Canonicalisation is an explicit alias table, not a similarity judgement. A term
# that is absent from the table stays as user text and can only match an
# identical documented term.
ALIASES = {
    "gravity": {
        "microgravity": "microgravity", "micro-gravity": "microgravity",
        "micro gravity": "microgravity", "micro-g": "microgravity",
        "reduced gravity": "microgravity", "zero-g": "microgravity",
        "zero g": "microgravity", "µg": "microgravity", "ug": "microgravity",
        "terrestrial": "terrestrial", "normal gravity": "terrestrial",
        "earth gravity": "terrestrial", "1-g": "terrestrial", "1 g": "terrestrial",
        "one-g": "terrestrial", "lunar": "lunar", "moon": "lunar",
        "lunar gravity": "lunar", "martian": "martian", "mars": "martian",
        "mars gravity": "martian", "partial gravity": "partial", "partial": "partial",
    },
    "fuel": {
        "pmma": "pmma", "polymethyl methacrylate": "pmma",
        "poly(methyl methacrylate)": "pmma", "cast pmma": "pmma",
        "plexiglas": "pmma", "acrylic": "pmma",
        "methanol": "methanol", "methanol droplet": "methanol",
        "heptane": "heptane", "n-heptane": "heptane",
        "ethanol": "ethanol", "n-dodecane": "dodecane", "dodecane": "dodecane",
        "decane": "decane", "n-decane": "decane",
        "sibal fabric": "sibal_fabric", "sibal cloth": "sibal_fabric",
        "cotton-fiberglass": "sibal_fabric", "cotton fiberglass": "sibal_fabric",
        "cotton": "cotton", "cellulose": "cellulose", "nomex": "nomex",
        "polyethylene": "polyethylene", "hdpe": "polyethylene",
        "polypropylene": "polypropylene", "thermoplastic": "thermoplastic",
        "wood": "wood", "silicone": "silicone",
    },
    "geometry": {
        "rod": "rod", "cylinder": "cylinder", "cylindrical": "cylinder",
        "slab": "slab", "flat sample": "flat_sample", "spherical section": "spherical_section",
        "sphere": "spherical_section", "film": "film", "fabric sheet": "fabric_sheet",
        "fabric": "fabric_sheet", "thick sample": "thick_sample",
        "thermally thick sample": "thick_sample", "droplet": "droplet",
    },
    "apparatus": {
        "msg": "msg", "microgravity science glovebox": "msg",
        "cir": "cir", "combustion integrated rack": "cir",
        "mdca": "mdca", "multi-user droplet combustion apparatus": "mdca",
        "wind tunnel": "wind_tunnel", "flow duct": "flow_duct",
        "saffire flow unit": "sfu", "sfu": "sfu", "cygnus": "cygnus",
        "zgrf": "zgrf", "zero gravity research facility": "zgrf",
    },
    "ignition": {
        "hot wire": "hot_wire", "hotwire": "hot_wire", "ignition coil": "ignition_coil",
        "glow coil": "ignition_coil", "spark": "spark", "pilot flame": "pilot_flame",
        "radiative": "radiative", "radiative ignition": "radiative",
        "laser": "laser", "laser ignition": "laser",
    },
    "suppression": {
        "co2": "co2", "carbon dioxide": "co2", "water mist": "water_mist",
        "water spray": "water_mist", "depressurization": "depressurization",
        "depressurisation": "depressurization", "vacuum": "vacuum",
        "reduced pressure": "vacuum", "inert gas": "inert_gas",
    },
}

MAX_TEXT = 300


def _text(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text or unknown")
    value = " ".join(value.split())
    if not value:
        return None
    if len(value) > MAX_TEXT:
        raise ValueError(f"{field} exceeds {MAX_TEXT} characters")
    canonical = ALIASES.get(field, {}).get(value.casefold())
    return canonical if canonical else "custom:" + value.casefold()


def _numeric(value, field):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"value", "unit"}:
        raise ValueError(f"{field} needs a value and a unit")
    number, unit = value["value"], value["unit"]
    if isinstance(number, bool) or not isinstance(number, (int, float)) or number != number:
        raise ValueError(f"{field} value must be a finite number")
    if not isinstance(unit, str) or unit not in UNITS[field]:
        raise ValueError(f"Unsupported unit for {field}")
    offset = UNIT_OFFSETS.get(field, {}).get(unit, 0.0)
    converted = round(number * UNITS[field][unit] + offset, 6)
    if converted < 0 or (field == "oxygen_percent" and converted > 100) or (field == "pressure_kpa" and converted == 0):
        raise ValueError(f"{field} is outside physical bounds")
    if field == "temperature_k" and converted <= 0:
        raise ValueError(f"{field} is outside physical bounds")
    return converted


def normalize_scenario(scenario):
    """Return canonical values while preserving the user's original input."""
    if not isinstance(scenario, dict):
        raise ValueError("Scenario must be an object")
    unknown_fields = set(scenario) - set(FIELDS)
    if unknown_fields:
        raise ValueError("Unsupported scenario parameter: " + ", ".join(sorted(unknown_fields)))
    canonical, original = {}, {}
    for field in FIELDS:
        raw = scenario.get(field)
        if raw is None:
            continue
        value = _numeric(raw, field) if field in NUMERIC_FIELDS else _text(raw, field)
        if value is None:
            continue
        canonical[field] = value
        original[field] = raw
    return canonical, original


def validate_interest(interest):
    if interest in (None, ""):
        return None
    if not isinstance(interest, str):
        raise ValueError("interest must be text")
    canonical = interest.strip().casefold().replace("-", "_").replace(" ", "_")
    if canonical not in INTERESTS:
        raise ValueError("Unsupported fire behaviour of interest: " + interest)
    return canonical


def _fmt(value, unit=None):
    if isinstance(value, dict):
        text = f"{value['min']:g}–{value['max']:g}"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{value:g}"
    else:
        # Canonical categorical tokens are machine values; prose uses spaces.
        text = str(value)
        if text.startswith("custom:"):
            text = text[len("custom:"):]
        text = text.replace("_", " ")
    return f"{text} {unit}".strip() if unit else text


def _numeric_values(records):
    values = [record["value"] for record in records]
    singles = [value for value in values if not isinstance(value, dict)]
    ranges = [value for value in values if isinstance(value, dict)]
    return singles, ranges


def _classify_numeric(target, records):
    singles, ranges = _numeric_values(records)
    unit = records[0]["unit"] if records else None
    exact = [value for value in singles if abs(value - target) <= 1e-9]
    if exact:
        detail = f"Scenario {_fmt(target, unit)} equals a reported test value."
        others = sorted({round(value, 6) for value in singles})
        if len(others) > 1:
            detail += " Other reported values in this investigation: " + ", ".join(
                _fmt(value, unit) for value in others if abs(value - target) > 1e-9)[:300] + "."
        return "exact_match", detail
    containing = [value for value in ranges if value["min"] <= target <= value["max"]]
    if containing:
        spans = "; ".join(_fmt(value, unit) for value in containing[:3])
        return "partial_match", (
            f"Scenario {_fmt(target, unit)} lies inside the reported test range {spans}. "
            "Range membership is not experimental equivalence.")
    documented = sorted({round(value, 6) for value in singles})
    spans = [_fmt(value, unit) for value in sorted(ranges, key=lambda row: row["min"])]
    if documented or spans:
        nearest = min(
            documented + [value["min"] for value in ranges] + [value["max"] for value in ranges],
            key=lambda candidate: abs(candidate - target))
        return "mismatch", (
            f"Documented test values are {', '.join(([_fmt(v, unit) for v in documented] + spans)[:4])}; "
            f"the scenario value {_fmt(target, unit)} differs. Nearest documented value: {_fmt(nearest, unit)}.")
    return "unknown", "No reported numeric value in the available corpus."


def _classify_text(target, records):
    values = sorted({record["value"] for record in records})
    if target in values:
        detail = "A reported value matches the scenario term."
        others = [value for value in values if value != target]
        if others:
            detail += " The investigation also documents: " + ", ".join(others) + "."
        return "exact_match", detail
    return "mismatch", "Documented values are " + ", ".join(values) + "; the scenario term differs."


def _unqualified_reason(records):
    statuses = sorted({(record["evidence_status"], record["scope"]) for record in records})
    parts = ", ".join(f"{status} ({scope.replace('_', ' ')})" for status, scope in statuses)
    return ("A condition mention exists but is not a qualified reported test condition: " + parts +
            ". It is not used as a match.")


def compare_investigation(target, investigation):
    """Compare every specified scenario field with one investigation."""
    parameters = []
    for field in FIELDS:
        if field not in target:
            continue
        all_records = [record for record in investigation["records"] if record["field"] == field]
        eligible = [record for record in all_records if record["matching_eligible"]]
        target_value = target[field]
        if eligible:
            status, reason = (_classify_numeric(target_value, eligible) if field in NUMERIC_FIELDS
                              else _classify_text(target_value, eligible))
            basis = "reported_test_condition"
            records = eligible
        elif all_records:
            status, reason = "unknown", _unqualified_reason(all_records)
            basis = "no_qualified_condition"
            records = []
        else:
            status = "unknown"
            reason = ("The available corpus has no extracted condition record for this field in this "
                      "investigation. This is not evidence that the condition was never tested.")
            basis = "not_documented_in_available_corpus"
            records = []
        parameters.append({
            "field": field,
            "label": FIELD_LABELS[field],
            "scenario_value": target_value,
            "unit": NUMERIC_FIELDS.get(field),
            "classification": status,
            "reason": reason,
            "basis": basis,
            "records": [{
                "source_id": record["source_id"], "chunk_id": record["chunk_id"],
                "locator": record.get("locator"),
                "quote": record["quote"], "value": record["value"], "unit": record["unit"],
                "scope": record["scope"], "evidence_status": record["evidence_status"],
            } for record in records],
            "unqualified_records": [{
                "source_id": record["source_id"], "chunk_id": record["chunk_id"],
                "locator": record.get("locator"),
                "quote": record["quote"], "value": record["value"], "unit": record["unit"],
                "scope": record["scope"], "evidence_status": record["evidence_status"],
            } for record in all_records if not record["matching_eligible"]],
        })
    counts = {status: sum(row["classification"] == status for row in parameters)
              for status in ("exact_match", "partial_match", "mismatch", "unknown")}
    specified = len(parameters)
    if not specified:
        applicability = "not_assessed"
    elif counts["mismatch"]:
        applicability = "outside_documented_conditions"
    elif counts["exact_match"] + counts["partial_match"] and counts["unknown"]:
        applicability = "partially_documented"
    elif counts["exact_match"] + counts["partial_match"]:
        applicability = "documented_alignment"
    else:
        applicability = "no_documented_conditions"
    return {
        "investigation_id": investigation["investigation_id"],
        "label": investigation["label"],
        "domain": investigation["domain"],
        "behaviors": list(investigation["behaviors"]),
        "source_ids": list(investigation["source_ids"]),
        "parameters": parameters,
        "counts": counts,
        "applicability": applicability,
        "records_considered": len([row for row in parameters for _ in row["records"]]),
    }


def relevance(comparison, interest):
    """Separate direct experimental evidence from contextual research.

    The behaviour list is a curated statement of what each investigation was
    designed to study, not a measurement. A condition match in a different
    combustion regime stays visible but cannot become direct evidence.
    """
    if not interest:
        return {"evidence_type": "unclassified", "reason": "No fire behaviour of interest was specified."}
    if interest in comparison["behaviors"]:
        return {"evidence_type": "direct",
                "reason": f"The investigation lists {BEHAVIOR_LABELS[interest]} among its study objectives."}
    return {"evidence_type": "contextual",
            "reason": (f"The investigation studies {', '.join(BEHAVIOR_LABELS[b] for b in comparison['behaviors'])}; "
                       f"it does not directly address {BEHAVIOR_LABELS[interest]}. Condition matches remain contextual.")}


def assess(target, investigations, interest=None):
    """Build the deterministic comparison, coverage and applicability summary."""
    comparisons = [compare_investigation(target, investigation) for investigation in investigations]
    for comparison in comparisons:
        comparison["relevance"] = relevance(comparison, interest)
    specified = [field for field in FIELDS if field in target]
    cells = [(row, param) for row in comparisons for param in row["parameters"]]
    status_counts = {status: sum(param["classification"] == status for _, param in cells)
                     for status in ("exact_match", "partial_match", "mismatch", "unknown")}
    denominator = len(cells)
    documented = denominator - status_counts["unknown"]
    per_field = {}
    for field in specified:
        field_cells = [param for _, param in cells if param["field"] == field]
        per_field[field] = {
            "label": FIELD_LABELS[field],
            "scenario_value": target[field],
            "investigations_compared": len(field_cells),
            **{status: sum(param["classification"] == status for param in field_cells)
               for status in ("exact_match", "partial_match", "mismatch", "unknown")},
        }
    coverage = {
        "unit": "scenario-parameter × investigation cells",
        "definition": ("Share of specified scenario parameters for which the retrieved investigations "
                       "document any qualified condition value. Documented means exact, partial or "
                       "mismatched values are present; it does not mean the scenario is supported."),
        "numerator": documented,
        "denominator": denominator,
        "documented_percent": round(100 * documented / denominator, 1) if denominator else None,
        "alignment_numerator": status_counts["exact_match"] + status_counts["partial_match"],
        "alignment_percent": (round(100 * (status_counts["exact_match"] + status_counts["partial_match"]) / denominator, 1)
                              if denominator else None),
        "status_counts": status_counts,
        "per_field": per_field,
        "excluded": [],
        "limitations": ("The denominator is the specified scenario parameters times the investigations "
                        "present in this corpus. It is not a probability, confidence score or safety measure. "
                        "A high value only means more cells contain documented values."),
    }
    counts = {}
    for comparison in comparisons:
        counts[comparison["applicability"]] = counts.get(comparison["applicability"], 0) + 1
    return {
        "scenario_fields": specified,
        "investigations": comparisons,
        "coverage": coverage,
        "applicability_counts": counts,
        "limitations": [
            "This is an evidence-applicability assessment, not a fire-risk prediction or safety certification.",
            "No experimental tolerances are invented. Numeric agreement is exact value equality; a value "
            "inside a reported range is only a partial match.",
            "Unknown means the available corpus does not document the condition. It does not prove that NASA "
            "never conducted the experiment.",
            "Condition comparison is necessary but not sufficient for transferability. Apparatus, scale, "
            "ignition protocol and measurement definitions can still differ.",
        ],
    }


# --- evidence gaps ---------------------------------------------------------

GAP_ORDER = {
    "no_documented_condition_in_corpus": 0,
    "combination_not_jointly_documented": 1,
    "contextual_evidence_only": 2,
    "documented_outside_scenario_condition": 3,
    "partial_documentation_only": 4,
    "documented_only_as_plan_or_background": 5,
    "documented_but_not_qualified": 6,
}
GAP_LABELS = {
    "no_documented_condition_in_corpus": "No documented condition in the available corpus",
    "combination_not_jointly_documented": "No single investigation documents the full combination",
    "contextual_evidence_only": "Only contextual evidence from another regime",
    "documented_outside_scenario_condition": "Documented, but outside the scenario condition",
    "partial_documentation_only": "Only a reported range contains the value",
    "documented_only_as_plan_or_background": "Mentioned only as a plan or background",
    "documented_but_not_qualified": "Mentioned without a qualified reported value",
}
GAP_PRIORITY_NOTE = (
    "Lexicographic ordering: absence of a documented condition, absence of a joint record for the "
    "full combination, another combustion regime, a documented mismatch, range-only coverage, "
    "planned-only mentions, then unqualified mentions. This is a documentation-coverage ordering, "
    "not a scientific importance score.")


def identify_gaps(target, comparisons):
    """Classify what is missing per specified scenario parameter.

    A field is not a gap when a *direct* investigation reports an exact value.
    A value merely inside a range, or documented only by a different combustion
    regime, remains a gap with a narrower kind. No kind asserts that an
    experiment was never conducted.
    """
    gaps = []
    for field in FIELDS:
        if field not in target:
            continue
        rows = [(row, next(param for param in row["parameters"] if param["field"] == field))
                for row in comparisons]
        direct = lambda row: row["relevance"]["evidence_type"] in ("direct", "unclassified")
        direct_exact = [row for row, param in rows
                        if param["classification"] == "exact_match" and direct(row)]
        direct_matches = [row for row, param in rows
                          if param["classification"] in ("exact_match", "partial_match") and direct(row)]
        any_matches = [row for row, param in rows
                       if param["classification"] in ("exact_match", "partial_match")]
        if direct_exact:
            continue
        if direct_matches:
            kind = "partial_documentation_only"
        elif any_matches:
            kind = "contextual_evidence_only"
        elif any(param["classification"] == "mismatch" for _, param in rows):
            kind = "documented_outside_scenario_condition"
        elif any(param["basis"] == "no_qualified_condition" for _, param in rows):
            kinds = {record["evidence_status"] for _, param in rows for record in param["unqualified_records"]}
            kind = ("documented_only_as_plan_or_background" if kinds <= {"proposed", "background"} and kinds
                    else "documented_but_not_qualified")
        else:
            kind = "no_documented_condition_in_corpus"
        documented = [record for _, param in rows for record in param["records"]]
        unqualified = [record for _, param in rows for record in param["unqualified_records"]]
        documented_rows = [row for row, param in rows if param["records"]]
        unknown_labels = [row["label"] for row, param in rows if param["classification"] == "unknown"]
        mismatch_labels = [row["label"] for row, param in rows if param["classification"] == "mismatch"]
        matched_labels = [row["label"] for row, param in rows
                          if param["classification"] in ("exact_match", "partial_match")]
        gaps.append({
            "gap_id": "gap-" + field,
            "field": field,
            "label": GAP_LABELS[kind],
            "kind": kind,
            "scenario_value": target[field],
            "unit": NUMERIC_FIELDS.get(field),
            "what_is_missing": _what_is_missing(field, kind, target[field], documented, unqualified),
            "why_relevant": _why_relevant(field, unknown_labels, mismatch_labels, matched_labels),
            "what_cannot_be_established": (
                "The available corpus cannot establish how this scenario parameter affects the selected "
                "fire behaviour at the specified value."),
            "documentation_status": {
                "no_documented_condition_in_corpus": "absent_from_available_corpus",
                "contextual_evidence_only": "documented_only_in_other_regimes",
                "documented_outside_scenario_condition": "documented_at_other_values",
                "partial_documentation_only": "range_coverage_only",
                "documented_only_as_plan_or_background": "planned_or_background_only",
                "documented_but_not_qualified": "unqualified_extraction_only",
            }[kind],
            "possible_explanations": [
                "No such experiment was conducted.",
                "An experiment exists but is not among the ingested NASA documents.",
                "The condition is reported in prose or a table that the deterministic extractor did not capture.",
                "The condition was not reported with a comparable unit or definition.",
            ],
            "corpus_scope_note": ("Absence from this corpus is not proof that NASA never conducted the "
                                  "experiment. The corpus is 12 ingested documents, not a complete archive."),
            "documented_records": documented,
            "unqualified_records": unqualified,
            "investigations": {
                "documented": [row["investigation_id"] for row in documented_rows],
                "unknown": [row["investigation_id"] for row, param in rows if param["classification"] == "unknown"],
                "mismatch": [row["investigation_id"] for row, param in rows if param["classification"] == "mismatch"],
                "matched": [row["investigation_id"] for row in any_matches],
                "direct_exact": [row["investigation_id"] for row in direct_exact],
            },
        })
    specified = [field for field in FIELDS if field in target]
    direct_rows = [row for row in comparisons
                   if row["relevance"]["evidence_type"] in ("direct", "unclassified")]
    full_exact = [row for row in direct_rows
                  if row["parameters"] and all(param["classification"] == "exact_match"
                                               for param in row["parameters"])]
    if specified and not full_exact:
        ranked = sorted(direct_rows, key=lambda row: (
            -row["counts"]["exact_match"], -row["counts"]["partial_match"], row["investigation_id"]))
        summary = []
        for row in ranked:
            exact = [param["field"] for param in row["parameters"] if param["classification"] == "exact_match"]
            missing = [param["field"] for param in row["parameters"]
                       if param["classification"] != "exact_match"]
            summary.append({"investigation_id": row["investigation_id"], "label": row["label"],
                            "exact_fields": exact, "not_exact_fields": missing,
                            "cases": row["counts"]})
        documented = [record for row in ranked[:2] for param in row["parameters"] for record in param["records"]][:6]
        gaps.append({
            "gap_id": "gap-combination",
            "field": None,
            "label": "No single investigation documents the full combination",
            "kind": "combination_not_jointly_documented",
            "scenario_value": dict(target),
            "unit": None,
            "what_is_missing": (
                f"No single direct investigation reports exact values for all {len(specified)} specified "
                "dimensions at once. The corpus documents parts of the combination, but the joint behaviour "
                "of these dimensions at the stated values is not established."),
            "why_relevant": (
                "Individual condition matches do not compose into joint evidence when they come from "
                "different apparatus, scales or test matrices."),
            "what_cannot_be_established": (
                "The available corpus cannot establish how this combination of conditions affects the "
                "selected fire behaviour."),
            "documentation_status": "combination_not_documented_together",
            "possible_explanations": [
                "No single experiment used this combination.",
                "The combination was tested but is not among the ingested documents.",
                "Different investigations covered different parts of the combination.",
            ],
            "corpus_scope_note": ("Absence of a joint record is not proof that the combination was never "
                                  "tested. The corpus is not a complete NASA archive."),
            "documented_records": documented,
            "unqualified_records": [],
            "investigations": {
                "coverage": summary,
                "documented": [row["investigation_id"] for row in ranked],
                "unknown": [], "mismatch": [], "matched": [row["investigation_id"] for row in ranked],
                "direct_exact": [],
            },
        })
    return gaps


def _what_is_missing(field, kind, value, documented, unqualified):
    unit = NUMERIC_FIELDS.get(field)
    label = FIELD_LABELS[field]
    shown = _fmt(value, unit)
    if kind == "no_documented_condition_in_corpus":
        return (f"No ingested document reports a {label} of {shown} for any retrieved investigation. "
                "Whether an experiment at this condition exists outside the corpus is unknown.")
    if kind == "contextual_evidence_only":
        return (f"{label.capitalize()} is documented, but only by investigations in a different combustion "
                f"regime or behaviour. Those records do not directly address the selected behaviour at {shown}.")
    if kind == "documented_outside_scenario_condition":
        return (f"{label.capitalize()} is documented, but not at {shown}. The reported values do not cover "
                "the scenario value.")
    if kind == "partial_documentation_only":
        return (f"The scenario value {shown} lies inside a reported test range, but no individually reported "
                "test point at that value was found.")
    if kind == "documented_only_as_plan_or_background":
        return (f"{label.capitalize()} appears only in planned-work or background wording. No qualified "
                f"reported test at {shown} is available for comparison.")
    return (f"A {label} mention exists in the corpus, but it is not a qualified reported test condition "
            f"for {shown}.")


def _why_relevant(field, unknown, mismatch, matched):
    label = FIELD_LABELS[field]
    parts = []
    if unknown:
        parts.append("unreported by " + ", ".join(unknown))
    if mismatch:
        parts.append("documented differently by " + ", ".join(mismatch))
    if matched:
        parts.append("matching documentation exists for " + ", ".join(matched))
    return (f"The scenario specifies {label}. The corpus comparison found: " + "; ".join(parts) +
            ". A conclusion about the scenario would need to cross this documentation boundary.")


# --- experiment proposals --------------------------------------------------

_PROHIBITED_CLAIM = re.compile(
    r"\b(?:is|are|was|were)\s+(?:proven|established|confirmed|demonstrated)\b"
    r"|\b(?:guarantees?|guaranteed|flight[- ]ready|approved for flight)\b"
    r"|\b(?:is|are)\s+(?:completely\s+)?safe\b",
    re.I)


def _citation(record):
    return {key: record.get(key) for key in ("source_id", "chunk_id", "locator", "quote",
                                             "value", "unit", "evidence_status", "scope")}


def _proposal_label():
    return "AXIOM PROPOSED — NOT EXECUTED OR VALIDATED NASA EXPERIMENT"


def _priority(rank, gap, evidence):
    return {
        "rank": rank,
        "method": GAP_PRIORITY_NOTE,
        "criteria": [
            {"criterion": "gap kind", "value": gap["kind"],
             "explanation": ("Absence of documentation ranks ahead of another combustion regime, "
                             "a documented mismatch, range-only coverage, planned-only mentions and "
                             "unqualified mentions.")},
            {"criterion": "scenario relevance", "value": "specified by the user",
             "explanation": "Only gaps for scenario parameters the user supplied are considered."},
            {"criterion": "evidence traceability", "value": f"{len(evidence)} cited record(s)",
             "explanation": "Each proposal links to actual corpus records where available."},
        ],
    }


def _combination_proposal(gap, target, interest, rank):
    """Build the joint-condition proposal without inventing any values."""
    behaviour = BEHAVIOR_LABELS.get(interest, "the selected fire behaviour")
    specified = [FIELD_LABELS[name] for name in FIELDS if name in target]
    shown = ", ".join(f"{FIELD_LABELS[name]} = {_fmt(target[name], NUMERIC_FIELDS.get(name))}"
                      for name in FIELDS if name in target)
    evidence = gap["documented_records"]
    coverage = gap["investigations"]["coverage"]
    question = (f"Do the investigations that each document only part of this scenario jointly support "
                f"an expectation for {behaviour} at {shown}?")
    design = (
        "A qualified team could design a joint test matrix that varies the specified dimensions "
        "together instead of combining results from separate investigations. The comparison would "
        "hold apparatus, scale, ignition protocol and measurement definitions constant across cells. "
        "Partial coverage came from: "
        + "; ".join(f"{row['investigation_id']} exact for {', '.join(FIELD_LABELS[name] for name in row['exact_fields']) or 'no field'}"
                    for row in coverage[:3])
        + ". Exact values, replication, apparatus limits and safety controls require expert and facility "
          "review; no outcome is assumed here.")
    hypothesis = (f"Hypothesis (proposed, not observed): {behaviour} may differ when the specified "
                  "dimensions are tested jointly relative to what is implied by separate investigations. "
                  "The direction and magnitude are unknown until the experiment is performed.")
    return {
        "proposal_id": "proposal-combination",
        "label": _proposal_label(),
        "gap_id": gap["gap_id"],
        "gap_kind": gap["kind"],
        "research_question": question,
        "scientific_motivation": {
            "summary": gap["what_is_missing"] + " " + gap["why_relevant"],
            "basis": "documented_conditions_in_available_corpus",
            "evidence": [_citation(record) for record in evidence[:4]],
        },
        "hypothesis": hypothesis,
        "independent_variables": specified,
        "controlled_variables": ["apparatus", "scale", "ignition protocol", "measurement definitions"],
        "dependent_variables": DEPENDENT_VARIABLES.get(interest, ["fire behaviour appropriate to the research question"]),
        "experimental_design": design,
        "expected_contribution": (
            "Could establish whether the combination behaves as the separate partial investigations "
            "suggest. It would not by itself establish spacecraft fire safety or certify a material."),
        "evidence_source_ids": sorted({record["source_id"] for record in evidence}),
        "unresolved_limitations": [
            "The proposal is a high-level concept and has not been reviewed by combustion scientists.",
            "No parameter range, sample size, expected measurement or result is asserted.",
            "Facility capability, diagnostics and safety review are outside this workspace.",
        ],
        "proposed_values": [
            {"field": name, "value": _fmt(target[name], NUMERIC_FIELDS.get(name)),
             "status": "user_scenario_value_not_measured"}
            for name in FIELDS if name in target
        ],
        "priority": _priority(rank, gap, evidence),
    }


def propose(gaps, target, interest, comparisons, limit=3):
    """Create at most three deterministic, traceable research concepts.

    No numerical ranges are invented. Scenario values are user inputs and are
    labelled as hypothetical; documented values come only from cited records.
    """
    def order(gap):
        position = FIELDS.index(gap["field"]) if gap.get("field") in FIELDS else -1
        return (GAP_ORDER.get(gap["kind"], 9), position, gap["gap_id"])

    ordered = sorted(gaps, key=order)
    proposals = []
    for gap in ordered[:limit]:
        field = gap["field"]
        if field is None:
            proposals.append(_combination_proposal(gap, target, interest, len(proposals) + 1))
            continue
        label = FIELD_LABELS[field]
        unit = gap["unit"]
        scenario_text = _fmt(gap["scenario_value"], unit)
        behaviour = BEHAVIOR_LABELS.get(interest, "the selected fire behaviour")
        evidence = gap["documented_records"] or gap["unqualified_records"]
        if not evidence:
            evidence = [record for row in comparisons for param in row["parameters"]
                        if param["field"] == field for record in param["records"]][:3]
        if gap["kind"] == "no_documented_condition_in_corpus":
            question = (f"How does {label} at the proposed value ({scenario_text}) affect {behaviour} "
                        "under otherwise controlled and documented conditions?")
        elif gap["kind"] == "documented_outside_scenario_condition":
            documented = ", ".join(sorted({_fmt(record["value"], record["unit"])
                                           for record in gap["documented_records"]}))[:240]
            question = (f"Do findings reported at {documented} extend to the proposed {label} of "
                        f"{scenario_text} for {behaviour}?")
        elif gap["kind"] == "partial_documentation_only":
            question = (f"Is {behaviour} individually documented at {label} = {scenario_text}, or is the "
                        "value known only as a point inside a reported range?")
        elif gap["kind"] == "contextual_evidence_only":
            question = (f"Does {behaviour} at {label} = {scenario_text} differ from the related combustion "
                        "regime that documents the condition?")
        else:
            question = (f"What does a qualified test at {label} = {scenario_text} show for {behaviour}, "
                        "given that the corpus mentions the condition only indirectly?")
        controlled = [FIELD_LABELS[name] for name in FIELDS if name in target and name != field]
        if controlled:
            controlled_text = "Hold the other specified scenario dimensions constant: " + ", ".join(controlled) + "."
        else:
            controlled_text = "Hold apparatus, scale, ignition protocol and atmosphere constant across comparisons."
        design = (
            "A qualified team could compare the proposed value with the documented conditions cited above "
            "using the same apparatus and measurement definitions within each comparison. "
            + controlled_text +
            " Exact values, replication, apparatus limits and safety controls require expert and facility review; "
            "no outcome is assumed here.")
        hypothesis = (f"Hypothesis (proposed, not observed): {behaviour} "
                      f"may differ at {label} = {scenario_text} relative to the cited documented conditions. "
                      "The direction and magnitude are unknown until the experiment is performed.")
        proposal = {
            "proposal_id": "proposal-" + field,
            "label": _proposal_label(),
            "gap_id": gap["gap_id"],
            "gap_kind": gap["kind"],
            "research_question": question,
            "scientific_motivation": {
                "summary": gap["what_is_missing"] + " " + gap["why_relevant"],
                "basis": "documented_conditions_in_available_corpus",
                "evidence": [_citation(record) for record in evidence[:4]],
            },
            "hypothesis": hypothesis,
            "independent_variables": [label],
            "controlled_variables": controlled,
            "dependent_variables": DEPENDENT_VARIABLES.get(interest, ["fire behaviour appropriate to the research question"]),
            "experimental_design": design,
            "expected_contribution": (
                "Could reduce the documentation gap for this scenario dimension. It would not by itself "
                "establish spacecraft fire safety or certify a material."),
            "evidence_source_ids": sorted({record["source_id"] for record in evidence}),
            "unresolved_limitations": [
                "The proposal is a high-level concept and has not been reviewed by combustion scientists.",
                "No parameter range, sample size, expected measurement or result is asserted.",
                "Facility capability, diagnostics and safety review are outside this workspace.",
            ],
            "proposed_values": [{"field": field, "value": scenario_text,
                                 "status": "user_scenario_value_not_measured"}],
            "priority": _priority(len(proposals) + 1, gap, evidence),
        }
        proposals.append(proposal)
    return proposals


def numeric_literals(text):
    return [float(value) for value in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)", text)]


def audit(assessment):
    """Deterministic Safety Critic pass over generated scenario statements.

    Claims that assert safety, treat missing documentation as a negative result,
    or introduce unsupported numbers are withheld. The audit does not replace
    scientific review.
    """
    checks = []

    def add(subject, verdict, reason, issues=(), sources=()):
        checks.append({"subject": subject, "verdict": verdict, "reason": reason,
                       "issues": list(issues), "sources": list(sources)})

    for gap in assessment["gaps"]:
        text = " ".join([gap["what_is_missing"], gap["why_relevant"], gap["what_cannot_be_established"]])
        if re.search(r"\b(did not|never|no experiment|was not (?:tested|conducted))\b", text, re.I):
            add(gap["gap_id"], "withheld", "The gap statement asserts a negative experimental result.",
                ["absence_treated_as_negative_result"])
        elif _PROHIBITED_CLAIM.search(text):
            add(gap["gap_id"], "withheld", "The gap statement contains an unsupported safety or proof claim.",
                ["unsupported_strong_claim"])
        else:
            add(gap["gap_id"], "supported",
                "The gap describes documentation coverage only and states the corpus boundary.",
                sources=[record["source_id"] for record in gap["documented_records"][:3]])

    valid_quotes = {(record["chunk_id"], record["quote"]) for row in assessment["investigations"]
                    for param in row["parameters"] for record in param["records"] + param["unqualified_records"]}
    for proposal in assessment["proposals"]:
        issues = []
        if ("PROPOSED" not in proposal["label"]
                or "hypothesis (proposed, not observed)" not in proposal["hypothesis"].lower()):
            issues.append("proposal_not_clearly_labelled")
        if _PROHIBITED_CLAIM.search(proposal["hypothesis"] + " " + proposal["expected_contribution"]):
            issues.append("unsupported_strong_claim")
        if not proposal["scientific_motivation"]["evidence"]:
            issues.append("motivation_has_no_documented_condition")
        for citation in proposal["scientific_motivation"]["evidence"]:
            if (citation["chunk_id"], citation["quote"]) not in valid_quotes:
                issues.append("invalid_citation")
        gap = next((row for row in assessment["gaps"] if row["gap_id"] == proposal["gap_id"]), None)
        if gap and gap["kind"] not in GAP_ORDER:
            issues.append("unidentified_gap")
        if gap and gap["investigations"]["direct_exact"]:
            issues.append("duplicates_documented_evidence")
        allowed = set()
        for field, value in assessment["target"].items():
            if isinstance(value, (int, float)):
                allowed.add(float(value))
        for record in (gap["documented_records"] if gap else []):
            if isinstance(record["value"], dict):
                allowed.update({float(record["value"]["min"]), float(record["value"]["max"])})
            elif isinstance(record["value"], (int, float)):
                allowed.add(float(record["value"]))
        # Statements format numbers with :g, which can round a documented value.
        # Accept exactly those rendered forms as well, never a new magnitude.
        allowed.update(float(f"{value:g}") for value in list(allowed))
        for literal in numeric_literals(proposal["experimental_design"] + " " + proposal["hypothesis"] +
                                        " " + proposal["research_question"]):
            if literal not in allowed:
                issues.append("unsupported_numeric_value")
                break
        blocking = [issue for issue in issues if issue != "motivation_has_no_documented_condition"]
        add(proposal["proposal_id"], "withheld" if blocking else "qualified" if issues else "supported",
            "Proposal traceability and labelling checks failed." if blocking else
            "The proposal is labelled as proposed, introduces no unverified range and is linked to an "
            "identified gap; its motivation has no quoted condition and remains qualified." if issues else
            "The proposal is labelled as proposed, cites available records and introduces no unverified range.",
            issues, proposal["evidence_source_ids"])

    for row in assessment["investigations"]:
        sources = [record["source_id"] for param in row["parameters"] for record in param["records"]]
        if row["applicability"] == "documented_alignment" and row["relevance"]["evidence_type"] == "contextual":
            add(row["investigation_id"], "qualified",
                "Conditions align but the investigation does not directly study the selected behaviour.",
                ["contextual_domain_only"], sources[:3])
        elif row["applicability"] == "outside_documented_conditions":
            add(row["investigation_id"], "qualified",
                "At least one specified condition differs from documented values; the investigation cannot "
                "be used as direct support for the scenario.", ["documented_condition_mismatch"], sources[:3])
        elif row["applicability"] == "no_documented_conditions":
            add(row["investigation_id"], "qualified",
                "No qualified condition is documented for this investigation; no support or contradiction "
                "is established.", ["unknown_condition"], [])
        else:
            add(row["investigation_id"], "supported",
                "The comparison reports documented condition relationships without asserting safety.",
                sources=sources[:3])

    withheld = [check for check in checks if check["verdict"] == "withheld"]
    qualified = [check for check in checks if check["verdict"] == "qualified"]
    return {
        "checks": checks,
        "summary": {
            "total": len(checks), "supported": len(checks) - len(withheld) - len(qualified),
            "qualified": len(qualified), "withheld": len(withheld),
            "verdict": "withheld" if withheld else "qualified" if qualified else "supported",
        },
        "scope": ("Rule-based audit of generated statements. It verifies citation presence, labels and "
                  "arithmetic-derived statements. It is not a semantic review by a combustion scientist."),
        "prohibited_conclusion": ("No output establishes spacecraft fire safety, material approval or an "
                                  "operational firefighting decision."),
    }
