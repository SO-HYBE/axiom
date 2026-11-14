"""Deterministic checks; semantic judgment is deliberately a separate signal."""
import math
import re
from decimal import Decimal, InvalidOperation

CONDITIONS = ("gravity", "fuel", "oxygen_percent", "pressure_kpa", "flow_cm_s")

NUMBER = r"[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?"
QUANTITY = re.compile(
    rf"(?<![\w.+\-−–‑])(?P<number>{NUMBER})\s*(?P<unit>%|[A-Za-zµμ°][A-Za-z0-9µμ°²³^*/·⁻_-]*)?"
)
PERCENT_LABEL = re.compile(
    rf"(?<![\w.])(?P<number>{NUMBER})\s*(?:%|percent\b)\s*(?P<label>[A-Za-z][A-Za-z0-9-]*)",
    re.IGNORECASE,
)
# Compare literal units only. Case distinguishes mW from MW. Other units or
# alternative spellings need review, even if a conversion might be legitimate.
KNOWN_UNITS = frozenset(
    "% Pa kPa MPa atm mmHg bar m cm mm µm μm s ms min K °C W mW kW MW "
    "m/s cm/s mm/s m² cm² mm² µg μg mg g kg".split()
)
PROSPECTIVE = re.compile(
    r"\b(will|would|aims?|objectives?|plans?|planned|proposed|designed to|intends? to)\b", re.I
)
COMPLETED = re.compile(
    r"\b(found|demonstrated|showed|confirmed|(?:was|were) (?:observed|measured|recorded))\b", re.I
)


def _quantities(text):
    for match in QUANTITY.finditer(text):
        unit = match.group("unit")
        yield Decimal(match.group("number").replace("−", "-")), "%" if unit == "percent" else unit


def _composition_pairs(quote):
    """Only parse explicit adjacent percentage/label lists in the cited span."""
    matches = list(PERCENT_LABEL.finditer(quote))
    pairs = set()
    for left, right in zip(matches, matches[1:]):
        if re.fullmatch(r"\s*(?:[,;/]|,?\s*and)\s*", quote[left.end():right.start()], re.I):
            for match in (left, right):
                pairs.add((Decimal(match["number"].replace("−", "-")), match["label"].casefold()))
    return pairs


def _numeric_issues(text, quotes):
    quantities = list(_quantities(text))
    if not quantities:
        return set()
    cited_quantities = {quantity for quote in quotes for quantity in _quantities(quote)}
    issues = set()
    for quantity in quantities:
        _, unit = quantity
        if unit not in KNOWN_UNITS:
            issues.add("numeric_unit_unresolved")
        elif quantity not in cited_quantities:
            issues.add("numeric_literal_not_cited")

    cited_pairs = {pair for quote in quotes for pair in _composition_pairs(quote)}
    if not cited_pairs:
        # Multiple percentages in prose or tables need a verified assignment
        # to variables. Literal values alone cannot settle the association.
        if (any(unit == "%" for _, unit in quantities)
                and len({value for value, unit in cited_quantities if unit == "%"}) > 1):
            issues.add("numeric_association_unresolved")
        return issues
    labels = {label for _, label in cited_pairs}
    declared_pairs = {
        (Decimal(m["number"].replace("−", "-")), m["label"].casefold())
        for m in PERCENT_LABEL.finditer(text)
    }
    for pair in declared_pairs:
        if pair[1] in labels and pair not in cited_pairs:
            issues.add("numeric_association_mismatch")
    # With an explicit composition in evidence, a percentage detached from
    # its component needs review. Do not guess reversed phrasing or synonyms.
    paired_values = {value for value, label in declared_pairs if label in labels}
    for value, unit in quantities:
        if unit == "%" and any(v == value for v, _ in cited_pairs) and value not in paired_values:
            issues.add("numeric_association_unresolved")
    return issues


def normalized(text):
    # Case matters in scientific units: mW and MW are not interchangeable.
    return " ".join(text.split())


def validate_conditions(conditions):
    if not isinstance(conditions, dict) or set(conditions) - set(CONDITIONS):
        raise ValueError("Unknown or invalid condition fields")
    for key, value in conditions.items():
        if value is None:
            continue
        if key in ("gravity", "fuel"):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a nonempty string")
        elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        elif value < 0 or (key == "oxygen_percent" and value > 100) or (key == "pressure_kpa" and value == 0):
            raise ValueError(f"{key} outside physical input bounds")


def needs_applicability(question):
    # This is a conservative routing heuristic, not a general intent classifier.
    return bool(re.search(r"\b(safe|safety limit|recommend|certif\w*|should|can (?:we|i)|our (?:cabin|spacecraft)|mars|lunar|moon|guarantee|extinguish)\b", question, re.I))


def check_claim(claim, chunks, target=None, applicability=False, semantic=None):
    """A verified source/quote alone never establishes a paraphrase's truth."""
    target = target or {}
    validate_conditions(target)
    issues, citations, cited = [], [], []
    text = claim.get("text", "")
    if not isinstance(text, str) or not text.strip():
        issues.append("empty_claim")
        text = ""
    for ref in claim.get("citations", []):
        chunk = chunks.get(ref.get("chunk_id"))
        quote = ref.get("quote", "")
        valid = bool(chunk and chunk["source_id"] == ref.get("source_id")
                     and isinstance(quote, str) and len(quote.strip()) >= 15
                     and normalized(quote) in normalized(chunk["text"]))
        citations.append({**ref, "valid": valid,
                          "url": chunk["url"] if chunk else None,
                          "locator": chunk["locator"] if chunk else None,
                          "document_url": chunk.get("document_url") if chunk else None})
        if valid:
            cited.append(chunk)
        else:
            issues.append("invalid_citation_or_quote")
    if not citations:
        issues.append("missing_citation")
    exact = bool(citations and all(c["valid"] for c in citations)
                 and any(normalized(text) == normalized(c["quote"]) for c in citations))
    grounding = "verbatim_excerpt" if exact else "unverified_paraphrase"
    # A model signal is recorded, never silently elevated to human validation.
    if semantic:
        grounding = "model_" + semantic.get("verdict", "uncertain")
    if grounding in ("unverified_paraphrase", "model_uncertain"):
        issues.append("semantic_support_unresolved")
    if grounding == "model_unsupported":
        issues.append("semantic_support_rejected")
    if grounding == "model_contradicted":
        issues.append("counterevidence_found")
    checks = semantic.get('evidence_checks', []) if semantic else []
    if grounding == 'model_supported' and any(check.get('relation') in ('contradicts','limits') for check in checks):
        issues.append('conflicting_or_limiting_evidence')
    absolute_safety = re.search(r'\b(?:all|every|any)\s+(?:spacecraft\s+)?materials?\s+(?:are|is|will be)\s+(?:completely\s+)?(?:safe|fireproof|nonflammable)\b', text, re.I)
    if absolute_safety and not re.search(r'\b(?:not|cannot|does not|no evidence)\b', text[:absolute_safety.start()], re.I):
        issues.append('universal_safety_claim_unresolved')
    if not exact:
        try:
            issues.extend(_numeric_issues(text, [ref["quote"] for ref in citations if ref["valid"]]))
        except InvalidOperation:
            issues.append("numeric_literal_unresolved")
        for ref in citations:
            if not ref["valid"] or chunks[ref["chunk_id"]].get("source_kind") != "experiment_overview":
                continue
            quote = ref["quote"]
            if (PROSPECTIVE.search(quote) and not PROSPECTIVE.search(text)
                    or COMPLETED.search(text) and not COMPLETED.search(quote)):
                issues.append("overview_scope_unresolved")
    applicability_status = "not_assessed"
    if applicability:
        applicability_status = "conditions_match_only"
        required = set(CONDITIONS)
        if any(target.get(k) is None for k in required):
            issues.append("target_conditions_incomplete")
        for chunk in cited:
            observed = chunk.get("conditions", {})
            for key in CONDITIONS:
                a, b = target.get(key), observed.get(key)
                if a is None or b is None:
                    issues.append("condition_unknown:" + key)
                elif isinstance(a, str) and normalized(a) != normalized(str(b)):
                    issues.append("condition_mismatch:" + key)
                elif not isinstance(a, str) and a != b:
                    issues.append("condition_mismatch:" + key)
        # Even five matching fields cannot establish mission-level safety.
        issues.append("operational_inference_requires_expert_review")
        applicability_status = "not_established"
    hard = any(i in ("empty_claim", "missing_citation", "invalid_citation_or_quote",
                     "semantic_support_rejected", "numeric_association_mismatch", "counterevidence_found") for i in issues)
    verdict = "blocked" if hard else "needs_review" if issues or not exact else "quoted_evidence"
    if grounding == "model_supported" and not issues:
        verdict = "model_supported_needs_review"
    if 'counterevidence_found' in issues or 'numeric_association_mismatch' in issues:
        evidence_status = 'contradicted'
    elif hard:
        evidence_status = 'unsupported'
    elif issues and any(check.get('relation') == 'supports' for check in checks):
        evidence_status = 'partial'
    elif issues or not semantic:
        evidence_status = 'unassessable'
    else:
        evidence_status = 'supported'
    next_evidence = []
    if any(issue.startswith('condition_') for issue in issues):
        next_evidence.append('Find test-level records for the missing or mismatched environmental conditions.')
    if 'counterevidence_found' in issues or 'conflicting_or_limiting_evidence' in issues:
        next_evidence.append('Compare the cited supporting and conflicting passages, including their test conditions.')
    if any(issue in issues for issue in ('missing_citation','invalid_citation_or_quote')):
        next_evidence.append('Provide a verifiable quotation and page reference for this claim.')
    if any(issue.startswith('numeric_') for issue in issues):
        next_evidence.append('Check the original numeric values, units and their assignment to materials or test conditions.')
    if 'semantic_support_unresolved' in issues or 'overview_scope_unresolved' in issues:
        next_evidence.append('Find a source passage that directly supports this interpretation and preserves its scope.')
    if 'universal_safety_claim_unresolved' in issues:
        next_evidence.append('Replace the universal safety conclusion with the specific tested scope and limitations.')
    return {"evidence_status":evidence_status, "next_evidence":next_evidence, "text": text, "citations": citations, "verdict": verdict,
            "grounding": grounding, "applicability": applicability_status,
            "issues": sorted(set(issues)), "semantic_review": semantic,
            "uncertainty": "Source excerpts can omit qualifications. No operational safety conclusion is established."}
