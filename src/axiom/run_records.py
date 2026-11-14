"""Bounded local run history; records contain observations, not safety approvals."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile

MAX_RECORD_BYTES = 2 * 1024 * 1024
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('Invalid record identifier')
    return value


def _directory(root, kind):
    root = Path(root).resolve()
    directory = root / 'runs' / kind
    # Disallow redirected record directories, even redirects within the project.
    for path in (root / 'runs', directory):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Record directory escapes its designated root')
    return directory


def _path(directory, identifier):
    path = directory / (_identifier(identifier) + '.json')
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Record path escapes its designated directory')
    return path


def _validate(record, id_key, expected=None):
    if not isinstance(record, dict):
        raise ValueError('Record must be an object')
    identifier = _identifier(record.get(id_key))
    if expected is not None and identifier != expected:
        raise ValueError('Record identifier does not match its filename')
    if id_key == 'run_id' and not isinstance(record.get('answer'), str):
        raise ValueError('Run record requires an answer string')
    for key in ('answer', 'question', 'created_at'):
        if key in record and not isinstance(record[key], str):
            raise ValueError('Malformed record text field: ' + key)
    if id_key == 'comparison_id':
        required = {'comparison_id', 'created_at', 'question', 'baseline', 'ignis', 'controls', 'status', 'errors'}
        if not required <= record.keys():
            raise ValueError('Comparison record is incomplete')
        if (not isinstance(record['created_at'], str) or not isinstance(record['question'], str)
                or record['status'] not in ('complete', 'partial', 'failed')
                or not isinstance(record['controls'], dict) or not isinstance(record['errors'], dict)
                or any(key not in ('baseline', 'ignis', 'storage', 'baseline_save', 'ignis_save', 'comparison_save') or not isinstance(value, str)
                       for key, value in record['errors'].items())
                or any(record[key] is not None and not isinstance(record[key], dict) for key in ('baseline', 'ignis'))):
            raise ValueError('Malformed comparison record')
    return record


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Repeated JSON object key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-finite JSON number')


def _load(root, identifier, kind, id_key):
    path = _path(_directory(root, kind), identifier)
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECORD_BYTES + 1)
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError('Record exceeds the 2 MiB limit')
    try:
        result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('Malformed JSON record') from exc
    return _validate(result, id_key, identifier)


def _save(root, result, kind, id_key):
    _validate(result, id_key)
    try:
        data = (json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError('Record is not JSON serializable') from exc
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError('Record exceeds the 2 MiB limit')
    directory = _directory(root, kind)
    directory.mkdir(parents=True, exist_ok=True)
    destination = _path(directory, result[id_key])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.' + result[id_key] + '-', suffix='.tmp', dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Recheck before replacing; never follow a redirected destination.
        _path(_directory(root, kind), result[id_key])
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def save_run(root, result):
    return _save(root, result, 'history', 'run_id')


def load_run(root, run_id):
    return _load(root, run_id, 'history', 'run_id')


def save_comparison(root, comparison):
    return _save(root, comparison, 'comparisons', 'comparison_id')


def load_comparison(root, comparison_id):
    return _load(root, comparison_id, 'comparisons', 'comparison_id')


def save_scenario(root, assessment):
    """Persist a scenario assessment under the existing bounded record rules."""
    if not isinstance(assessment, dict) or not isinstance(assessment.get('coverage'), dict):
        raise ValueError('Scenario assessment is incomplete')
    return _save(root, assessment, 'scenarios', 'scenario_id')


def load_scenario(root, scenario_id):
    return _load(root, scenario_id, 'scenarios', 'scenario_id')


def list_scenarios(root, limit=20, offset=0, query=''):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError('Use a limit from 1 to 100 and a nonnegative offset')
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Search must be text of at most 500 characters')
    directory = _directory(root, 'scenarios')
    summaries, skipped = [], 0
    for path in sorted(directory.glob('*.json')):
        try:
            record = _load(root, path.stem, 'scenarios', 'scenario_id')
        except (OSError, ValueError, TypeError, RecursionError):
            skipped += 1
            continue
        searchable = [record.get('description'), record.get('interest')]
        labels = [row.get('label') for row in record.get('investigations', [])]
        searchable.extend(labels)
        if query.casefold() not in ' '.join(str(value) for value in searchable if value is not None).casefold():
            continue
        summaries.append({'scenario_id': record['scenario_id'], 'created_at': _string(record, 'created_at', None),
                          'description': _string(record, 'description', ''), 'interest': _string(record, 'interest', None),
                          'fields': sorted((record.get('target') or {}).keys()),
                          'coverage_percent': (record.get('coverage') or {}).get('documented_percent'),
                          'alignment_percent': (record.get('coverage') or {}).get('alignment_percent'),
                          'applicability_counts': record.get('applicability_counts') or {}})
    summaries.sort(key=lambda row: row['scenario_id'])
    summaries.sort(key=lambda row: _date_order(row['created_at']), reverse=True)
    return {'scenarios': summaries[offset:offset + limit], 'total': len(summaries), 'skipped': skipped}


def _string(record, key, default=''):
    return record.get(key) if isinstance(record.get(key), str) else default


def _summary(record, id_key):
    summary = {id_key: record[id_key], 'created_at': _string(record, 'created_at', None),
               'question': _string(record, 'question', 'Saved answer')}
    if id_key == 'run_id':
        info = record.get('model_info')
        info = info if isinstance(info, dict) else {}
        summary.update({key: _string(record, key) for key in ('answer_status', 'mode', 'system')})
        summary.update(provider=_string(info, 'provider', None), model=_string(info, 'model', None),
                       abstained=record.get('abstained') if type(record.get('abstained')) is bool else None,
                       provisional=record.get('provisional') if type(record.get('provisional')) is bool else None)
        summary['model_info'] = {key: _string(info, key, None) for key in ('provider', 'model')}
    else:
        summary['status'] = record['status']
        summary.update(provider=_string(record['controls'], 'provider', None),
                       model=_string(record['controls'], 'model', None))
        for key in ('baseline', 'ignis'):
            summary[key + '_status'] = _string(record[key] or {}, 'answer_status', None)
    return summary


def _list(root, kind, id_key, limit, offset, query):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError('Use a limit from 1 to 100 and a nonnegative offset')
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Search must be text of at most 500 characters')
    directory = _directory(root, kind)
    summaries, skipped = [], 0
    for path in sorted(directory.glob('*.json')):
        try:
            record = _load(root, path.stem, kind, id_key)
            summary = _summary(record, id_key)
        except (OSError, ValueError, TypeError, RecursionError):
            skipped += 1
            continue
        searchable = list(summary.values()) + [_string(record, 'answer')]
        if id_key == 'comparison_id':
            searchable.extend(_string(record[key] or {}, 'answer') for key in ('baseline', 'ignis'))
        if query.casefold() in ' '.join(str(value) for value in searchable if value is not None).casefold():
            summaries.append(summary)
    # Missing dates stay null and sort last; never invent acquisition/run dates.
    summaries.sort(key=lambda row: row[id_key])
    summaries.sort(key=lambda row: _date_order(row['created_at']), reverse=True)
    return {'runs' if id_key == 'run_id' else 'comparisons': summaries[offset:offset + limit],
            'total': len(summaries), 'skipped': skipped}


def _date_order(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.min.replace(tzinfo=timezone.utc)


def list_runs(root, limit=20, offset=0, query=''):
    return _list(root, 'history', 'run_id', limit, offset, query)


def list_comparisons(root, limit=20, offset=0, query=''):
    return _list(root, 'comparisons', 'comparison_id', limit, offset, query)
