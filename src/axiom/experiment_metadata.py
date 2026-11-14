"""Deterministic experimental-metadata extraction with quotation provenance.

Only the ingested corpus is read. Every record carries a chunk identifier and an
exact quotation. A condition that is not explicit in the text is not created.
Reported observations, planned test matrices and background remarks stay
distinct, and none of them is treated as a human scientific review.

The rules below are conservative pattern matches. They are auditable and
reproducible, but a pattern match does not establish that the quoted text means
what the extractor inferred. Records therefore carry ``review_status`` and the
consumer must surface it.
"""
from __future__ import annotations

import hashlib
import re

FIELDS = ("gravity", "fuel", "geometry", "apparatus", "oxygen_percent",
          "pressure_kpa", "flow_cm_s", "temperature_k", "ignition", "suppression")
NUMERIC_FIELDS = {"oxygen_percent": "%", "pressure_kpa": "kPa", "flow_cm_s": "cm/s",
                  "temperature_k": "K"}
TEXT_FIELDS = tuple(field for field in FIELDS if field not in NUMERIC_FIELDS)

MAX_QUOTE = 400
_NUM = r"\d+(?:\.\d+)?|\.\d+"
_RANGE = rf"(?P<a>{_NUM})(?:\s*(?:to|through|and|–|—|-)\s*(?P<b>{_NUM}))?"
_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9(\[\u201c\u2022\-–—])|\n+')

_ATMOSPHERE_KPA = 101.325
PRESSURE_UNITS = {"atm": _ATMOSPHERE_KPA, "kpa": 1.0, "pa": 0.001, "bar": 100.0,
                  "torr": 0.133322, "mmhg": 0.133322, "psi": 6.89476}
FLOW_UNITS = {"cm/s": 1.0, "mm/s": 0.1, "m/s": 100.0}
# Fahrenheit and Celsius are affine; the offsets are applied after scaling.
TEMPERATURE_UNITS = {"k": 1.0, "°c": 1.0, "c": 1.0, "°f": 5 / 9, "f": 5 / 9}
TEMPERATURE_OFFSETS = {"k": 0.0, "°c": 273.15, "c": 273.15,
                       "°f": 273.15 - 32 * 5 / 9, "f": 273.15 - 32 * 5 / 9}

_PRESSURE_RE = re.compile(rf"(?P<start>(?<![\w.\-−]))(?P<a>{_NUM})(?:\s*(?:to|through|–|—)\s*(?P<b>{_NUM}))?\s*(?P<u>atm|kPa|Pa|bar|torr|mmHg|psi)\b", re.I)
_FLOW_RE = re.compile(rf"(?P<start>(?<![\w.\-−]))(?P<a>{_NUM})(?:\s*(?:to|through|and|–|—|-)\s*(?P<b>{_NUM}))?\s*(?P<u>cm/s|mm/s|m/s)\b", re.I)
_PERCENT_RE = re.compile(rf"(?<![\w.])(?P<n>{_NUM})\s*(?:%|percent\b)", re.I)
_FRACTION_RE = re.compile(rf"(?P<a>{_NUM})\s*(?:to|through|–|—|-)\s*(?P<b>{_NUM})", re.I)
# Explicit ranges that repeat the unit, e.g. "40 cm/s down to 1 cm/s". Without
# this, each endpoint would look like a separately reported test value.
_PRESSURE_RANGE_RE = re.compile(rf"(?P<a>{_NUM})\s*(?P<ua>atm|kPa|Pa|bar|torr|mmHg|psi)\s*(?:down\s+|up\s+)?(?:to|through|–|—|-)\s*(?P<b>{_NUM})\s*(?P<ub>atm|kPa|Pa|bar|torr|mmHg|psi)\b", re.I)
_FLOW_RANGE_RE = re.compile(rf"(?P<a>{_NUM})\s*(?P<ua>cm/s|mm/s|m/s)\s*(?:down\s+|up\s+)?(?:to|through|–|—|-)\s*(?P<b>{_NUM})\s*(?P<ub>cm/s|mm/s|m/s)\b", re.I)
_OXYGEN_RANGE_RE = re.compile(rf"(?P<a>{_NUM})\s*(?:%|percent\b)\s*(?:down\s+|up\s+)?(?:to|through|–|—|-)\s*(?P<b>{_NUM})\s*(?:%|percent\b)", re.I)
# Kelvin, Celsius and Fahrenheit only. A bare K/C/F needs a temperature word in
# the same sentence; the affine offset is applied by _temperature.
_TEMPERATURE_RE = re.compile(rf"(?P<start>(?<![\w.\-−]))(?P<a>{_NUM})(?:\s*(?:to|through|–|—)\s*(?P<b>{_NUM}))?\s*(?P<u>°C|°F|K|C|F)\b")
_TEMP_CONTEXT = re.compile(r"\b(temperature|temperatures|preheat\w*|pre-heat\w*)\b", re.I)
# Flame, exhaust, wall and outlet readings are measurements or outcomes, not the
# imposed test temperature, so they are not eligible as setup conditions.
_TEMP_EXCLUDE = re.compile(
    r"\b(flame|adiabatic|exhaust|outlet|burning|fire|wall|surface|peak|maximum|max\.?|"
    r"does not exceed|not exceed|up to|limit\w*|estimated|predicted|model\w*|"
    r"measured|measurement\w*|rise|distribution|difference\w*|sensitivity|negligible|"
    r"thermocouple\w*|uncertaint\w*|compared to)\b", re.I)

_OXYGEN_LABEL = re.compile(r"\s*(O2|O₂|O 2|oxygen)\b", re.I)
_OTHER_LABEL = re.compile(r"\s*(CO2|CO₂|N2|N₂|Ar|He|helium|nitrogen|suppressant)\b", re.I)
_GRAVITY_CONTEXT = re.compile(r"\b(test|tests|tested|experiment\w*|burn\w*|combust\w*|ignit\w*|flame\w*|aboard|ISS|spacecraft|environment|configuration|facility)\b", re.I)
_MOLE_FRACTION = re.compile(r"\bmole\s*fraction\b", re.I)

_FLOW_CONTEXT = re.compile(r"\b(flow|airflow|air flow|velocity|wind|duct|concurrent|opposed)\b", re.I)
_FLOW_EXCLUDE = re.compile(r"\b(spread rate|spreading rate|flame speed|burn(?:ing)? rate|regression|recession|flame spread rate)\b", re.I)

_GRAVITY = (
    (re.compile(r"\b(microgravity|micro-gravity|micro gravity|reduced gravity|zero[- ]g|µg|\bμg\b)\b", re.I), "microgravity", "microgravity"),
    (re.compile(r"\b(normal gravity|terrestrial|earth gravity|1[- ]g\b|one[- ]g\b)\b", re.I), "terrestrial", "terrestrial / normal gravity"),
    (re.compile(r"\b(lunar|moon) gravity\b", re.I), "lunar", "partial gravity (lunar)"),
    (re.compile(r"\b(martian|mars) gravity\b", re.I), "martian", "partial gravity (Martian)"),
    (re.compile(r"\bpartial gravity\b", re.I), "partial", "partial gravity"),
)

_FUELS = (
    (re.compile(r"\b(polymethyl methacrylate|poly\(methyl methacrylate\)|PMMA|cast PMMA)\b", re.I), "pmma", "PMMA"),
    (re.compile(r"\bmethanol\b", re.I), "methanol", "methanol"),
    (re.compile(r"\bn[- ]?heptane\b|\bheptane\b", re.I), "heptane", "heptane"),
    (re.compile(r"\bethanol\b", re.I), "ethanol", "ethanol"),
    (re.compile(r"\bn[- ]?dodecane\b|\bdodecane\b", re.I), "dodecane", "n-dodecane"),
    (re.compile(r"\bSIBAL\b|\bcotton[- ]fiberglass\b", re.I), "sibal_fabric", "cotton–fiberglass (SIBAL) fabric"),
    (re.compile(r"\bcotton\b", re.I), "cotton", "cotton"),
    (re.compile(r"\bcellulose\b", re.I), "cellulose", "cellulose"),
    (re.compile(r"\bNomex\b", re.I), "nomex", "Nomex"),
    (re.compile(r"\bpolyethylene\b", re.I), "polyethylene", "polyethylene"),
    (re.compile(r"\bpolypropylene\b", re.I), "polypropylene", "polypropylene"),
    (re.compile(r"\bthermoplastic\b", re.I), "thermoplastic", "thermoplastic"),
    (re.compile(r"\bwood\b", re.I), "wood", "wood"),
)

_GEOMETRY = (
    (re.compile(r"\brods?\b", re.I), "rod", "rod"),
    (re.compile(r"\bcylinders?\b", re.I), "cylinder", "cylinder"),
    (re.compile(r"\bslabs?\b", re.I), "slab", "slab"),
    (re.compile(r"\bspherical section\b", re.I), "spherical_section", "spherical section"),
    (re.compile(r"\bfilms?\b", re.I), "film", "film"),
    (re.compile(r"\bfabric sheets?\b|\bfabric samples?\b", re.I), "fabric_sheet", "fabric sheet"),
    (re.compile(r"\b(thick|thermally thick)\s+(samples?|fuels?)\b", re.I), "thick_sample", "thermally thick sample"),
    (re.compile(r"\bflat samples?\b", re.I), "flat_sample", "flat sample"),
    (re.compile(r"\bdroplets?\b", re.I), "droplet", "droplet"),
)

_APPARATUS = (
    (re.compile(r"\bMicrogravity Science Glovebox\b|\bMSG\b", re.I), "msg", "Microgravity Science Glovebox"),
    (re.compile(r"\bCombustion Integrated Rack\b|\bCIR\b", re.I), "cir", "Combustion Integrated Rack"),
    (re.compile(r"\bMDCA\b|\bMulti-User Droplet Combustion Apparatus\b", re.I), "mdca", "Multi-User Droplet Combustion Apparatus"),
    (re.compile(r"\bwind tunnel\b", re.I), "wind_tunnel", "wind tunnel"),
    (re.compile(r"\bflow duct\b", re.I), "flow_duct", "flow duct"),
    (re.compile(r"\bSaffire Flow Unit\b|\bSFU\b", re.I), "sfu", "Saffire Flow Unit"),
    (re.compile(r"\bCygnus\b", re.I), "cygnus", "Cygnus spacecraft"),
    (re.compile(r"\bZGRF\b|\bZero Gravity Research Facility\b", re.I), "zgrf", "Zero Gravity Research Facility"),
)

_IGNITION = (
    (re.compile(r"\bhot[- ]wire\b", re.I), "hot_wire", "hot wire"),
    (re.compile(r"\bignition coil\b|\bglow coil\b", re.I), "ignition_coil", "ignition coil"),
    (re.compile(r"\bspark\b", re.I), "spark", "spark"),
    (re.compile(r"\bpilot flame\b", re.I), "pilot_flame", "pilot flame"),
    (re.compile(r"\bradiative ignition\b|\bthermal radiation\b", re.I), "radiative", "radiative ignition"),
    (re.compile(r"\blaser\b", re.I), "laser", "laser"),
)

_SUPPRESSION = (
    (re.compile(r"\bCO2\b(?=[^.]{0,80}\b(suppress|extinguish|extinction|inert))", re.I), "co2", "carbon dioxide"),
    (re.compile(r"\bwater mist\b|\bwater spray\b", re.I), "water_mist", "water mist"),
    (re.compile(r"\bdepressuri[sz]", re.I), "depressurization", "depressurization"),
    (re.compile(r"\b(vacuum|reduced pressure)\b(?=[^.]{0,80}\b(extinguish|suppress|extinction))", re.I), "vacuum", "vacuum / reduced pressure"),
)

_PROPOSED = re.compile(r"\b(will|would|plan|planned|propos\w*|aims?|objectives?|intend\w*|designed to|is required|are required|shall)\b", re.I)
_BACKGROUND = re.compile(r"\b(previous\w*|earlier (?:stud|work|test)|literature|introduction|review|in general|is known|have been (?:studied|reported)|ground[- ]based|compared with|in contrast|unlike|relative to|nasa[- ]std|test method|standard test|fire standards|use of terrestrial|have been performed|has been performed|correlation)\b", re.I)
_CAPABILITY = re.compile(r"\b(up to|maximum|max\.?|could impose|can impose|capability|capacity|rated|system pressure|limited)\b", re.I)
_DERIVED = re.compile(r"\b(estimate[sd]?|equivalent|effective|in good agreement|approximately equal|predicted|model(?:ed|led)?|extrapolat\w*)\b", re.I)
_OUTCOME = re.compile(r"\b(limiting oxygen|LOI\b|minimum (?:oxygen|concentration)|needed|extinction limit|flammability boundary|blowoff|blow[- ]off|quench\w*|not observed below|unable to)\b", re.I)
_INSTRUMENT = re.compile(r"\b(resolution|accuracy|precision|uncertain|detection limit|sensitivity|calibrat\w*)\b", re.I)


def normalized(text):
    return " ".join(text.split())


def _quote(sentence):
    text = normalized(sentence)
    if len(text) <= MAX_QUOTE:
        return text
    cut = text.rfind(" ", 0, MAX_QUOTE)
    return text[:cut if cut > 0 else MAX_QUOTE]


def _status(sentence):
    if _PROPOSED.search(sentence):
        return "proposed"
    if _BACKGROUND.search(sentence) or _DERIVED.search(sentence):
        return "background"
    return "reported"


def _record(source_id, chunk_id, sentence, field, value, unit, scope, status, rule, note=""):
    quote = _quote(sentence)
    digest = hashlib.sha256(f"{chunk_id}|{field}|{value!r}|{quote}".encode()).hexdigest()[:12]
    return {
        "record_id": "meta-" + digest,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "quote": quote,
        "field": field,
        "value": value,
        "unit": unit,
        "scope": scope,
        "evidence_status": status,
        "rule": rule,
        "notes": note,
        "extraction": "deterministic_pattern_v1",
        "review_status": "machine_extracted_not_human_reviewed",
        "matching_eligible": status == "reported" and scope not in (
            "apparatus_capability", "reported_limit", "instrument_metadata"),
    }


def _numeric(value, unit, table):
    return round(value * table[unit.lower()], 6)


def _range_or_single(match, table):
    unit = match.group("u").lower()
    low = _numeric(float(match.group("a")), unit, table)
    high = _numeric(float(match.group("b")), unit, table) if match.group("b") else None
    if high is None:
        return low, False
    if high < low:
        low, high = high, low
    return {"min": low, "max": high}, True


def _sentences(text):
    for part in _SPLIT.split(text):
        part = part.strip(" \t")
        if len(part) >= 8:
            yield part


def _pressure(sentence):
    hits = []
    spans = []
    for match in _PRESSURE_RANGE_RE.finditer(sentence):
        low = _numeric(float(match.group("a")), match.group("ua"), PRESSURE_UNITS)
        high = _numeric(float(match.group("b")), match.group("ub"), PRESSURE_UNITS)
        if low > high:
            low, high = high, low
        if low <= 0 or high > 100 * _ATMOSPHERE_KPA:
            continue
        hits.append(({"min": low, "max": high}, "kPa", "experiment_range",
                     "pressure.unit_convert", f"Reported as {match.group(0)}"))
        spans.append((match.start(), match.end()))
    for match in _PRESSURE_RE.finditer(sentence):
        if any(start <= match.start() < end for start, end in spans):
            continue
        unit = match.group("u").lower()
        if unit in ("kpa", "pa") and not re.search(r"\b(pressure|chamber|atmosphere|atm)\b", sentence[:match.start()] + " " + sentence[match.end():], re.I):
            continue
        value, span = _range_or_single(match, PRESSURE_UNITS)
        numbers = [value["min"], value["max"]] if isinstance(value, dict) else [value]
        if any(number <= 0 or number > 100 * _ATMOSPHERE_KPA for number in numbers):
            continue
        if match.group("b"):
            scope = "experiment_range"
        elif _CAPABILITY.search(sentence):
            scope = "apparatus_capability"
        elif re.search(r"\b(up to|range|could be varied|can be varied|varied from)\b", sentence, re.I):
            scope = "experiment_range"
        else:
            scope = "individual_test"
        hits.append((value, "kPa", scope, "pressure.unit_convert", f"Reported as {match.group(0)}"))
    return hits


def _flow(sentence):
    hits = []
    spans = []
    for match in _FLOW_RANGE_RE.finditer(sentence):
        before = sentence[max(0, match.start() - 45):match.start()]
        after = sentence[match.end():match.end() + 25]
        if not _FLOW_CONTEXT.search(before + " " + after) or _FLOW_EXCLUDE.search(before):
            continue
        low = _numeric(float(match.group("a")), match.group("ua"), FLOW_UNITS)
        high = _numeric(float(match.group("b")), match.group("ub"), FLOW_UNITS)
        if low > high:
            low, high = high, low
        if low < 0 or high > 2000:
            continue
        hits.append(({"min": low, "max": high}, "cm/s", "experiment_range",
                     "flow.unit_convert", f"Reported as {match.group(0)}"))
        spans.append((match.start(), match.end()))
    for match in _FLOW_RE.finditer(sentence):
        if any(start <= match.start() < end for start, end in spans):
            continue
        before = sentence[max(0, match.start() - 45):match.start()]
        after = sentence[match.end():match.end() + 25]
        if not _FLOW_CONTEXT.search(before + " " + after):
            continue
        if _FLOW_EXCLUDE.search(before):
            continue
        if match.group("u").lower() in ("mm/s", "m/s"):
            # Flame spread and burning rates are outcomes, not imposed airflow.
            # A small converted value must sit beside an explicit flow phrase.
            if not _FLOW_CONTEXT.search(sentence[max(0, match.start() - 18):match.start()]):
                continue
        value, span = _range_or_single(match, FLOW_UNITS)
        numbers = [value["min"], value["max"]] if isinstance(value, dict) else [value]
        if any(number < 0 or number > 2000 for number in numbers):
            continue
        scope = "experiment_range" if span else (
            "apparatus_capability" if _CAPABILITY.search(sentence)
            else "experiment_range" if re.search(r"\b(up to|range|could be varied|can be varied|varied from)\b", sentence, re.I)
            else "individual_test")
        hits.append((value, "cm/s", scope, "flow.unit_convert", f"Reported as {match.group(0)}"))
    return hits


def _oxygen(sentence):
    hits = []
    spans = []
    for match in _OXYGEN_RANGE_RE.finditer(sentence):
        low, high = float(match.group("a")), float(match.group("b"))
        if not (0 <= low <= 100 and 0 <= high <= 100):
            continue
        if low > high:
            low, high = high, low
        if _INSTRUMENT.search(sentence):
            scope = "instrument_metadata"
        elif _OUTCOME.search(sentence):
            scope = "reported_limit"
        else:
            scope = "experiment_range"
        hits.append(({"min": round(low, 6), "max": round(high, 6)}, "%", scope,
                     "oxygen.percent_range", f"Reported as {match.group(0)}"))
        spans.append((match.start(), match.end()))
    # Composition labels such as 21% O2. A percentage attached to another gas
    # species is not oxygen and is never inferred as such.
    for match in _PERCENT_RE.finditer(sentence):
        if any(start <= match.start() < end for start, end in spans):
            continue
        tail = sentence[match.end():match.end() + 14]
        if _OTHER_LABEL.match(tail):
            continue
        labelled = bool(_OXYGEN_LABEL.match(tail))
        if not labelled and not (re.search(r"\boxygen\b", sentence, re.I) and not _OTHER_LABEL.match(tail)):
            continue
        value = round(float(match.group("n")), 6)
        if not 0 <= value <= 100:
            continue
        if _INSTRUMENT.search(sentence):
            scope = "instrument_metadata"
        elif _OUTCOME.search(sentence):
            scope = "reported_limit"
        elif labelled or len(_PERCENT_RE.findall(sentence)) == 1:
            scope = "individual_test"
        else:
            scope = "experiment_range"
        hits.append((value, "%", scope, "oxygen.percent", f"Reported as {match.group(0)}"))
    # Mole/volume fractions stated as 0.10 to 0.50 belong to oxygen only when
    # oxygen and the fraction wording are both explicit in the same sentence.
    if re.search(r"\boxygen\b", sentence, re.I) and _MOLE_FRACTION.search(sentence):
        for match in _FRACTION_RE.finditer(sentence):
            low, high = float(match.group("a")), float(match.group("b"))
            if not (0 <= low <= 1 and 0 <= high <= 1 and high >= low):
                continue
            hits.append(({"min": round(low * 100, 6), "max": round(high * 100, 6)}, "%",
                         "experiment_range", "oxygen.mole_fraction_x100",
                         f"Reported as mole fraction {match.group(1)}–{match.group(2)}"))
    return hits


def _text_hits(sentence, table, context=None):
    hits = []
    if context is not None and not context(sentence):
        return hits
    for pattern, value, label in table:
        if not pattern.search(sentence):
            continue
        hits.append((value, label))
    return hits


def _temperature(sentence):
    """Extract an imposed test temperature, never a flame or exhaust reading.

    This rule is deliberately narrow: the corpus rarely states a controlled test
    temperature, and a missing record is left missing. Celsius and Fahrenheit
    values are converted to kelvin with their affine offset.
    """
    if not _TEMP_CONTEXT.search(sentence) or _TEMP_EXCLUDE.search(sentence):
        return []
    hits = []
    for match in _TEMPERATURE_RE.finditer(sentence):
        unit = match.group("u").lower()
        offset = TEMPERATURE_OFFSETS[unit]
        scale = TEMPERATURE_UNITS[unit]
        low = round(float(match.group("a")) * scale + offset, 6)
        high = (round(float(match.group("b")) * scale + offset, 6)
                if match.group("b") else None)
        if high is not None and high < low:
            low, high = high, low
        numbers = [low] if high is None else [low, high]
        if any(number <= 0 or number > 4000 for number in numbers):
            continue
        if high is None:
            value = low
            scope = "apparatus_capability" if _CAPABILITY.search(sentence) else "individual_test"
        else:
            value = {"min": low, "max": high}
            scope = "experiment_range"
        hits.append((value, "K", scope, "temperature.affine_convert",
                     f"Reported as {match.group(0)}"))
    return hits


def _fuel_context(sentence):
    return re.search(r"\b(fuel|material|sample|fabric|rod|slab|cylinder|droplet|burn\w*|combust\w*|ignit\w*|flammab\w*|test\w*|experiment\w*)\b", sentence, re.I)


def _gravity_context(sentence):
    return bool(_GRAVITY_CONTEXT.search(sentence))


def extract_chunk(chunk):
    """Return deterministic condition records for one corpus passage."""
    records = []
    for sentence in _sentences(chunk["text"]):
        status = _status(sentence)
        for field, extractor in (("pressure_kpa", _pressure), ("flow_cm_s", _flow),
                                 ("oxygen_percent", _oxygen), ("temperature_k", _temperature)):
            for value, unit, scope, rule, note in extractor(sentence):
                records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, field,
                                       value, unit, scope, status, rule, note))
        for value, label in _text_hits(sentence, _GRAVITY, _gravity_context):
            records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, "gravity",
                                   value, None, "setup", status, "gravity.keyword", "Reported as: " + label))
        for value, label in _text_hits(sentence, _FUELS, _fuel_context):
            records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, "fuel",
                                   value, None, "setup", status, "fuel.lexicon", "Reported as: " + label))
        for value, label in _text_hits(sentence, _GEOMETRY):
            records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, "geometry",
                                   value, None, "setup", status, "geometry.lexicon", "Reported as: " + label))
        for value, label in _text_hits(sentence, _APPARATUS):
            records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, "apparatus",
                                   value, None, "setup", status, "apparatus.lexicon", "Reported as: " + label))
        for value, label in _text_hits(sentence, _IGNITION):
            records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, "ignition",
                                   value, None, "setup", status, "ignition.lexicon", "Reported as: " + label))
        for value, label in _text_hits(sentence, _SUPPRESSION):
            records.append(_record(chunk["source_id"], chunk["chunk_id"], sentence, "suppression",
                                   value, None, "setup", status, "suppression.lexicon", "Reported as: " + label))
    for record in records:
        record["locator"] = chunk.get("locator")
    return records


def _deduplicate(records, text_by_chunk):
    """Keep one record per source, field and canonical value.

    Later duplicates do not overwrite the first quotation. Every kept record is
    checked against its chunk before it can influence a comparison.
    """
    kept, seen = [], set()
    for record in records:
        text = text_by_chunk.get(record["chunk_id"], "")
        if not text or normalized(record["quote"]) not in normalized(text):
            continue
        key = (record["source_id"], record["field"], repr(record["value"]), record["evidence_status"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(record)
    return kept


# --- investigation grouping ------------------------------------------------

# Curated, documented grouping. It reflects the programme names used by the
# ingested NASA documents; it is not an inferred measurement.
_GROUPS = {
    "FLEX": ("FLEX", "FLEX droplet combustion", "droplet_combustion",
             ("ignition", "extinction", "burning_rate")),
    "BASS-II": ("BASS-II", "BASS-II solid-fuel flame spread", "solid_fuel_flame_spread",
                ("ignition", "flame_spread", "extinction", "flame_growth")),
    "BASS": ("BASS-II", "BASS-II solid-fuel flame spread", "solid_fuel_flame_spread",
             ("ignition", "flame_spread", "extinction", "flame_growth")),
    "BASS/BASS-II": ("BASS-II", "BASS-II solid-fuel flame spread", "solid_fuel_flame_spread",
                     ("ignition", "flame_spread", "extinction", "flame_growth")),
    "BASS-II / ground comparison": ("BASS-GC", "BASS-II ground comparison", "solid_fuel_flame_spread",
                                    ("ignition", "flame_spread", "extinction", "flame_growth")),
    "SAFFIRE": ("SAFFIRE", "SAFFIRE large-scale flammability", "large_scale_solid_flammability",
                ("flame_spread", "fire_growth", "material_flammability")),
    "SAFFIRE-V": ("SAFFIRE-V", "SAFFIRE-V large-scale flammability", "large_scale_solid_flammability",
                  ("flame_spread", "fire_growth", "material_flammability")),
    "SAFFIRE-VI": ("SAFFIRE-VI", "SAFFIRE-VI large-scale flammability", "large_scale_solid_flammability",
                   ("flame_spread", "fire_growth", "material_flammability")),
    "SAFFIRE-IV/V": ("SAFFIRE-IV/V", "SAFFIRE IV/V large-scale flammability", "large_scale_solid_flammability",
                     ("flame_spread", "fire_growth", "material_flammability")),
}

BEHAVIORS = {
    "ignition": "ignition",
    "flame_spread": "flame spread",
    "extinction": "extinction",
    "flame_growth": "flame growth",
    "fire_growth": "fire growth",
    "burning_rate": "burning rate",
    "material_flammability": "material flammability",
}


def investigation_key(experiment):
    return _GROUPS.get(experiment, (experiment, experiment, "unclassified", ()))[0]


def investigations(chunks):
    """Group provenance-valid records by NASA investigation.

    Sources without any extracted condition remain absent rather than being
    represented by invented metadata.
    """
    text_by_chunk = {chunk["chunk_id"]: chunk["text"] for chunk in chunks}
    records = _deduplicate([record for chunk in chunks for record in extract_chunk(chunk)], text_by_chunk)
    by_investigation = {}
    for record in records:
        experiment = next((chunk.get("experiment", "") for chunk in chunks
                           if chunk["chunk_id"] == record["chunk_id"]), "")
        meta = _GROUPS.get(experiment, (experiment, experiment, "unclassified", ()))
        key, label, domain, behaviors = meta
        group = by_investigation.setdefault(key, {
            "investigation_id": key, "label": label, "experiment_names": set(),
            "domain": domain, "behaviors": list(behaviors),
            "source_ids": set(), "records": [], "documents": {},
        })
        group["experiment_names"].add(experiment)
        group["source_ids"].add(record["source_id"])
        group["records"].append(record)
        group["documents"][record["source_id"]] = experiment
    result = []
    for key in sorted(by_investigation):
        group = by_investigation[key]
        result.append({
            **group,
            "experiment_names": sorted(group["experiment_names"]),
            "source_ids": sorted(group["source_ids"]),
            "records": sorted(group["records"], key=lambda row: (row["source_id"], row["chunk_id"], row["field"], repr(row["value"]))),
        })
    return result
