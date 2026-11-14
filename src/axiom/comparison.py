"""Run and preserve a controlled baseline/AXIOM pair without choosing a winner."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from .critic import validate_conditions
from .providers import make_model
from .research import load_chunks, load_condition_records, run
from .run_records import save_comparison, save_run


def validate_request(payload):
    """Validate shared ask/compare inputs and copy mutable values."""
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError("Question must be 1–4000 characters")
    target = payload.get("target", {})
    try:
        validate_conditions(target)
    except OverflowError:
        raise ValueError("Target condition numbers exceed supported bounds") from None
    result = {"question": question, "target": deepcopy(target)}
    for field, default, choices in (
        ("provider", "extractive", ("groq", "openrouter", "ollama", "extractive")),
        ("system", "ignis", ("ignis", "baseline", "rag_only")),
        ("intent", "research", ("research", "applicability")),
    ):
        value = payload.get(field, default)
        if not isinstance(value, str) or value not in choices:
            raise ValueError(f"Invalid {field}")
        result[field] = value
    model = payload.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 100):
        raise ValueError("Model must be a nonempty ID of at most 100 characters")
    result["model"] = model.strip() if model is not None else None
    for field in ("experiments", "source_ids"):
        value = payload.get(field)
        if value is not None and (
            not isinstance(value, list) or len(value) > 30
            or any(not isinstance(item, str) or not item.strip() or len(item) > 150 for item in value)
        ):
            raise ValueError(f"{field} must be a list of at most 30 nonempty strings of at most 150 characters")
        result[field] = list(value) if value is not None else None
    for field in ("include_overviews", "fresh"):
        value = payload.get(field, False)
        if type(value) is not bool:
            raise ValueError(f"{field} must be boolean")
        result[field] = value
    return result


def _failed_run(request, system, model, error, elapsed_ms):
    return {
        "run_id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
        "question": request["question"], "system": system, "mode": "model",
        "answer": "", "answer_status": "execution_error", "abstained": True,
        "claims": [], "draft_checks": [], "evidence": [], "source_cautions": [],
        "raw_draft": None, "steps": [], "target": deepcopy(request["target"]),
        "model_info": {"provider": request["provider"], "model": model.name},
        "model_calls": list(getattr(model, "calls", [])),
        "latency_ms": elapsed_ms, "error": error,
    }


def compare(root, payload, record_root=None):
    """Use one explicit resolved model, frozen inputs and separately saved outcomes."""
    request = validate_request(payload)
    if request["provider"] == "extractive":
        raise ValueError("Comparison requires Groq, OpenRouter, or a local Ollama model")
    root = Path(root)
    record_root = Path(record_root) if record_root is not None else root
    try:
        baseline_model = make_model(root, request["provider"], request["model"], use_cache=not request["fresh"])
        name = baseline_model.name
        if not isinstance(name, str) or not name.strip():
            raise ValueError("The provider did not resolve a fixed model ID")
        ignis_model = make_model(root, request["provider"], name, use_cache=not request["fresh"])
        if ignis_model.name != name:
            raise ValueError("The comparison models resolved to different IDs")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to prepare comparison models ({type(exc).__name__})") from None
    chunks = deepcopy(load_chunks(root))
    records = deepcopy(load_condition_records(root))
    controls = {key: deepcopy(request[key]) for key in (
        "provider", "fresh", "question", "target", "intent", "experiments", "source_ids", "include_overviews"
    )}
    controls["model"] = name
    pair = {
        "comparison_id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
        "question": request["question"], "baseline": None, "ignis": None, "controls": controls,
        "status": "complete", "errors": {}, "saved_locally": False,
        "explanation": "Both sides use the same resolved base model and question settings. "
                       "The baseline receives no NASA source corpus. AXIOM uses retrieval and claim checks. "
                       "This comparison does not assign a quality winner.",
    }
    execution_failures = 0
    for system, model in (("baseline", baseline_model), ("ignis", ignis_model)):
        started = perf_counter()
        try:
            result = run(
                request["question"], chunks if system == "ignis" else [], model=model, system=system,
                target=deepcopy(request["target"]), intent=request["intent"],
                experiments=deepcopy(request["experiments"]) if system == "ignis" else None,
                source_ids=deepcopy(request["source_ids"]) if system == "ignis" else None,
                include_overviews=request["include_overviews"] if system == "ignis" else False,
                condition_records=records if system == "ignis" else [],
            )
            if not isinstance(result, dict):
                raise TypeError("Run did not return a result object")
        except Exception as exc:
            message = f"{system} execution failed ({type(exc).__name__})."
            result = _failed_run(request, system, model, message, round((perf_counter() - started) * 1000, 2))
        if result.get("error"):
            execution_failures += 1
            pair["errors"][system] = result["error"]
        result["saved_locally"] = True
        try:
            save_run(record_root, result)
        except Exception as exc:
            result["saved_locally"] = False
            message = f"Could not save the {system} run locally ({type(exc).__name__})."
            result["save_error"] = message
            pair["errors"][system + "_save"] = message
        pair[system] = result
    pair["status"] = "failed" if execution_failures == 2 else "partial" if pair["errors"] else "complete"
    pair["saved_locally"] = all(pair[system]["saved_locally"] for system in ("baseline", "ignis"))
    try:
        save_comparison(record_root, pair)
    except Exception as exc:
        pair["saved_locally"] = False
        pair["errors"]["comparison_save"] = f"Could not save the comparison locally ({type(exc).__name__})."
        if pair["status"] == "complete":
            pair["status"] = "partial"
    return pair
