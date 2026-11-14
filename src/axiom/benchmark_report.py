"""Offline benchmark progress and independently annotated quality, never a judge."""
from copy import deepcopy
import math
import re

from .evaluate import SYSTEMS, evaluate


def _index(rows, label):
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"Each {label} row must be an object")
        qid, system = row.get("question_id"), row.get("system")
        if not isinstance(qid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", qid):
            raise ValueError("Invalid question_id")
        if not isinstance(system, str) or system not in SYSTEMS:
            raise ValueError("Invalid system")
        key = (qid, system)
        if key in result:
            raise ValueError(f"Duplicate {label} row: {key}")
        result[key] = row
    return result


def _failure(row):
    for field in ("execution_error", "error"):
        value = row.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{field} must be a nonempty string or null")
        if value:
            return value
    return None


def _number(value, field):
    if value is None:
        return None
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{field} must be finite and nonnegative or null")
    return value


def _rate(n, d):
    return {"value": n / d if d else None, "numerator": n, "denominator": d}


def _progress(keys, predictions, failed, grades, jobs):
    completed = [key for key in keys if key in predictions and key not in failed]
    failures = [key for key in keys if key in failed]
    pending = [key for key in keys if key not in predictions]
    blocked = [key for key in pending if jobs[key].get("block_reason")]
    answered = sum(not predictions[key]["abstained"] for key in completed)
    graded = sum(key in grades for key in completed)
    result = {"scheduled": len(keys), "completed": len(completed), "failed": len(failures),
              "pending": len(pending), "attempted": len(completed) + len(failures),
              "blocked_scope": sum(jobs[key].get("block_reason") == "named_scope_unavailable" for key in blocked),
              "pending_blocked": [{"question_id": q, "system": s, "block_reason": jobs[q, s]["block_reason"]}
                                  for q, s in sorted(blocked)],
              "graded": graded, "ungraded": len(completed) - graded,
              "question_ids": sorted({key[0] for key in keys}),
              "answer_coverage": _rate(answered, len(completed)),
              "scheduled_answer_coverage": _rate(answered, len(keys))}
    for name, subset in (("completed", completed), ("failed", failures), ("pending", pending)):
        result[name + "_jobs"] = [{"question_id": q, "system": s} for q, s in sorted(subset)]
    return result


def _performance(rows):
    latencies = []
    cache_hits = cache_known = calls_total = cache_unknown_predictions = 0
    values = {field: [] for field in ("input_tokens", "output_tokens", "cost_usd")}
    for row in rows:
        latency = _number(row.get("latency_ms"), "latency_ms")
        if latency is not None:
            latencies.append(latency)
        calls = row.get("model_calls")
        if calls is not None and (not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls)):
            raise ValueError("model_calls must be a list of objects or null")
        if calls is None:
            cache_unknown_predictions += 1
        else:
            calls_total += len(calls)
            for call in calls:
                hit = call.get("cache_hit")
                if hit is not None and type(hit) is not bool:
                    raise ValueError("cache_hit must be boolean or null")
                if hit is None and call.get("status") == "cache_hit":
                    hit = True
                if hit is not None:
                    cache_known += 1
                    cache_hits += hit
        for field in values:
            value = _number(row.get(field), field)
            # Provider audit usage is newly incurred usage; cached_usage is not added.
            if value is None and field != "cost_usd" and calls:
                alias = "prompt_tokens" if field == "input_tokens" else "completion_tokens"
                observed = [_number(c.get("usage", {}).get(alias), alias)
                            if isinstance(c.get("usage"), dict) else None for c in calls]
                if all(v is not None for v in observed):
                    value = sum(observed)
            values[field].append(value)
    result = {"predictions_observed": len(rows), "mean_latency_ms": sum(latencies) / len(latencies) if latencies else None,
              "latency_observations": len(latencies), "cache_hit_calls": cache_hits,
              "model_calls_observed": calls_total, "cache_status_known_calls": cache_known,
              "cache_status_unknown_calls": calls_total - cache_known,
              "cache_status_unknown_predictions": cache_unknown_predictions,
              "latency_policy": "Observed wall time includes failed attempts and cache hits; cache can confound comparisons."}
    for field, observations in values.items():
        known = [v for v in observations if v is not None]
        result[field] = {"total": sum(known) if observations and len(known) == len(observations) else None,
                         "known_subtotal": sum(known) if known else None,
                         "observations": len(known), "unknown_predictions": len(observations) - len(known)}
    return result


def summarize_benchmark(manifest, predictions, annotations=None):
    """Report jobs from manifest.jobs; grades must be independent annotation rows.

    Error rows are progress observations, not answers or correct abstentions.
    Missing numeric usage stays unknown. This function performs no model calls.
    """
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be an object")
    jobs = _index(manifest.get("jobs"), "job")
    for job in jobs.values():
        if job.get("split") not in ("dev", "test"):
            raise ValueError("Job split must be dev or test")
        reason = job.get("block_reason")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError("Job block_reason must be a nonempty string or null")
    pmap = _index(predictions, "prediction")
    amap = _index([] if annotations is None else annotations, "annotation")
    if pmap.keys() - jobs.keys():
        raise ValueError("Prediction has no scheduled job")
    if amap.keys() - pmap.keys():
        raise ValueError("Annotation has no prediction")
    failed = {key: _failure(row) for key, row in pmap.items() if _failure(row)}
    successful = []
    for key, row in pmap.items():
        if key not in failed:
            # Existing evaluator treats omitted optional measurements as unknown.
            copied = deepcopy(row)
            for field in ("latency_ms", "input_tokens", "output_tokens", "cost_usd"):
                if copied.get(field) is None:
                    copied.pop(field, None)
            successful.append(copied)
    grades = [row for key, row in amap.items() if key not in failed]
    quality = evaluate(successful, grades)
    systems = sorted({key[1] for key in jobs})
    splits = sorted({job["split"] for job in jobs.values()})
    group = lambda keys: _progress(list(keys), pmap, failed, amap, jobs)
    progress = {"overall": group(jobs),
                "by_system": {s: group(k for k in jobs if k[1] == s) for s in systems},
                "by_split": {t: group(k for k in jobs if jobs[k]["split"] == t) for t in splits},
                "by_system_split": {s: {t: group(k for k in jobs if k[1] == s and jobs[k]["split"] == t)
                                         for t in splits} for s in systems}}
    quality_by_split = {}
    for split in splits:
        selected = {key for key, job in jobs.items() if job["split"] == split}
        quality_by_split[split] = evaluate([p for p in successful if (p["question_id"], p["system"]) in selected],
                                          [a for a in grades if (a["question_id"], a["system"]) in selected])
    return {"schema_version": "1.0", "evaluation_kind": manifest.get("evaluation_kind", "exploratory_generation"),
            "annotation_status": manifest.get("annotation_status", "unreviewed"),
            "manifest_status": manifest.get("status"), "is_scientific_validation": False,
            "source_readiness": deepcopy(manifest.get("source_readiness")),
            "ablation": manifest.get("ablation"),
            "measurement_scopes": {s: sorted({p.get('measurement_scope', 'unspecified') for p in predictions if p['system'] == s}) for s in systems},
            "progress": progress, "quality": quality, "quality_by_split": quality_by_split,
            "excluded_execution_failures": [{"question_id": q, "system": s, "error": error}
                                             for (q, s), error in sorted(failed.items())],
            "excluded_failure_annotations": sum(key in failed for key in amap),
            "performance": {"overall": _performance(predictions),
                            "by_system": {s: _performance([p for p in predictions if p["system"] == s]) for s in systems}},
            "coverage_policy": {"answer_coverage": "Non-abstaining completed answers / completed successful predictions; failures excluded.",
                                "scheduled_answer_coverage": "Non-abstaining completed answers / all scheduled jobs; failed and pending jobs remain in denominator.",
                                "completed": "Successful executions, including evidence abstentions; does not imply scientific correctness."},
            "limitations": ["Quality uses only supplied independent annotations, whose independence is not verified here.",
                            "Critic verdicts and AI draft expected answers never become grading labels.",
                            "Quality is null without eligible grades; failed executions are excluded from quality and shown separately.",
                            "Overall quality pools splits; consult quality_by_split before interpreting development or test results.",
                            "Latency includes cache effects; unknown usage and cost are null, not zero.",
                            "AXIOM shared-draft ablation measurements cover the incremental critic; add the referenced RAG job for whole-workflow compute.",
                            "No model winner, statistical significance, or safety certification is asserted."]}
