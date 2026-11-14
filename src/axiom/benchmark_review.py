"""Import declared human review without changing frozen answers or inventing grades.

Reviewer credentials, independence and authorship are self-reported. Hash checks
establish local consistency, not a digital signature or scientific correctness.
Each import is a separate scored subset; reviewers are never silently merged.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .benchmark_report import summarize_benchmark
from .benchmark_run import MAX_BYTES, _directory, _hash, _records, _write
from .evaluate import _validate_grade
from .review import review_write_lock

ITEM_FIELDS = {'item_id', 'question', 'source_scope', 'answer', 'abstained', 'claims', 'grading'}
GRADE_FIELDS = {'supported', 'citation_valid', 'unsafe_extrapolation'}
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')


def _read_json(path):
    path = Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file():
        raise ValueError('Review input must be an unredirected regular file')
    with path.open('rb') as stream:
        blob = stream.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError('Review input exceeds the size limit')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('Duplicate review JSON key')
            result[key] = value
        return result
    def invalid(_):
        raise ValueError('Nonfinite review value')
    value = json.loads(blob.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('Review JSON must be an object')
    return value, hashlib.sha256(blob).hexdigest()


def _index(rows, label):
    if not isinstance(rows, list) or len(rows) > 1000:
        raise ValueError(label + ' must be a bounded list')
    result = {}
    for row in rows:
        identifier = row.get('item_id') if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in result:
            raise ValueError('Invalid or duplicate ' + label + ' item ID')
        result[identifier] = row
    return result


def _reviewer(submission):
    fields = ('reviewer', 'qualification', 'reviewed_at', 'independence_declaration')
    record = {}
    for field in fields:
        value = submission.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise ValueError('Review requires nonempty ' + field)
        record[field] = value.strip()
    try:
        datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('reviewed_at must be an ISO date or timestamp') from exc
    if submission.get('independent') is not True or submission.get('human_review') is not True:
        raise ValueError('An explicit independent human-review declaration is required')
    if submission.get('review_method', 'human') != 'human':
        raise ValueError('Automated or AI grading cannot be imported as human review')
    assistance = submission.get('assistance_disclosure', '')
    if not isinstance(assistance, str) or len(assistance) > 4000:
        raise ValueError('assistance_disclosure must be bounded text')
    return dict(record, independent=True, human_review=True, review_method='human',
                assistance_disclosure=assistance, verification='self_reported_not_independently_verified',
                qualifications_independently_verified=False, independence_independently_verified=False,
                human_authorship_independently_verified=False)


def _visible(record, question):
    prediction = record['prediction']
    return dict(question=question['question'], source_scope=record['generation_scope'],
                answer=prediction['answer'], abstained=prediction['abstained'], claims=[
                    dict(text=claim['text'], citations=[
                        {key: citation[key] for key in ('source_id', 'chunk_id', 'quote', 'url', 'locator')
                         if key in citation} for citation in claim['citations']])
                    for claim in prediction['claims']])


def _failed(record):
    return bool(record['prediction'].get('execution_error') or record['prediction'].get('error'))


def _grade(value, prediction):
    if value is None:
        return None, 'missing_grade'
    if not isinstance(value, dict):
        raise ValueError('Item grading must be an object or null')
    status = value.get('status', 'graded')
    if status in ('requires_atomization', 'pending'):
        if set(value) - {'status', 'reason'} or not isinstance(value.get('reason'), str) or not value['reason'].strip():
            raise ValueError('Pending or atomization items require a reason and no claim grades')
        return None, status
    if status != 'graded' or set(value) - {'status', 'claims', 'correct_abstention', 'reason'}:
        raise ValueError('Unknown grading status or fields')
    if 'reason' in value and not isinstance(value['reason'], str):
        raise ValueError('Grade reason must be text')
    claims = value.get('claims')
    if not isinstance(claims, list) or len(claims) != len(prediction['claims']):
        raise ValueError('Grading claim count differs; request atomization instead of changing alignment')
    incomplete = False
    for claim, predicted in zip(claims, prediction['claims']):
        if not isinstance(claim, dict) or set(claim) != GRADE_FIELDS:
            raise ValueError('Each claim grade requires the three documented fields')
        for field in GRADE_FIELDS:
            if claim[field] is None:
                incomplete = True
            elif type(claim[field]) is not bool:
                raise ValueError('Claim labels must be booleans or unresolved null')
        if not predicted['citations'] and claim['citation_valid'] is True:
            raise ValueError('An uncited claim cannot have a valid-citation grade')
    if 'correct_abstention' not in value or value['correct_abstention'] is not None and type(value['correct_abstention']) is not bool:
        raise ValueError('correct_abstention must be boolean or null')
    if incomplete:
        return None, 'claim_grades_incomplete'
    if not claims and value['correct_abstention'] is None:
        return None, 'no_resolved_labels'
    annotation = dict(question_id=prediction['question_id'], system=prediction['system'],
                      claims=claims, correct_abstention=value['correct_abstention'])
    _validate_grade(annotation, prediction)
    return annotation, None


def _safe_directory(directory, name):
    target = directory / name
    if target.is_symlink() or not target.resolve().is_relative_to(directory.resolve()):
        raise ValueError('Review output directory redirects')
    target.mkdir(exist_ok=True)
    return target


def import_review(root, run_id, review_path):
    """Validate a completed packet copy and atomically publish separate artifacts.

    Required top-level declarations: reviewer, qualification, reviewed_at,
    independence_declaration, independent:true and human_review:true. Declarations
    are not verified credentials. Null/partial grades remain ungraded; atomized
    claim edits must be adjudicated separately. The original packet is immutable.
    """
    directory = _directory(root, run_id)
    if Path(review_path).resolve() == (directory / 'review_packet.json').resolve():
        raise ValueError('Review a copy; preserve the original shuffled packet')
    submission, submission_sha = _read_json(review_path)
    reviewer = _reviewer(submission)
    with review_write_lock(directory):
        manifest, _ = _read_json(directory / 'manifest.json')
        if (manifest.get('run_id') != run_id or not isinstance(manifest.get('inputs'), dict)
                or _hash(manifest['inputs']) != manifest.get('input_fingerprint')):
            raise ValueError('Frozen benchmark input identity mismatch')
        records = _records(directory, manifest)
        record_map = {(record['question_id'], record['system']): record for record in records}
        if len(record_map) != len(records):
            raise ValueError('Duplicate authoritative benchmark record')
        packet, packet_sha = _read_json(directory / 'review_packet.json')
        private, private_sha = _read_json(directory / 'review_key.private.json')
        if any(value.get('benchmark_run_id') != run_id for value in (submission, packet, private)):
            raise ValueError('Review packet or private mapping belongs to another run')
        originals = _index(packet.get('items'), 'original packet')
        mapping = _index(private.get('keys'), 'private mapping')
        submitted = _index(submission.get('items'), 'submitted packet')
        if originals.keys() != mapping.keys() or submitted.keys() - originals.keys():
            raise ValueError('Packet contains unknown IDs or incomplete private mapping')
        questions = {}
        for question in manifest['inputs'].get('questions', []):
            if (not isinstance(question, dict) or not isinstance(question.get('question_id'), str)
                    or not isinstance(question.get('question'), str) or question['question_id'] in questions):
                raise ValueError('Invalid or duplicate frozen review question')
            questions[question['question_id']] = question
        mapped_pairs = set()
        for identifier, entry in mapping.items():
            pair = entry.get('question_id'), entry.get('system')
            if not all(isinstance(value, str) for value in pair):
                raise ValueError('Malformed private question/system identity')
            record = record_map.get(pair)
            if (record is None or pair in mapped_pairs or _failed(record) or pair[0] not in questions
                    or entry.get('prediction_sha256') != _hash(record['prediction'])):
                raise ValueError('Private mapping or prediction hash is stale or invalid')
            mapped_pairs.add(pair)
            original = originals[identifier]
            expected = _visible(record, questions[pair[0]])
            if (set(original) != ITEM_FIELDS or original.get('grading') is not None
                    or {key: original[key] for key in expected} != expected):
                raise ValueError('Original packet text does not match the authoritative prediction')
        expected_pairs = {pair for pair, record in record_map.items() if not _failed(record)}
        if mapped_pairs != expected_pairs:
            raise ValueError('Original packet no longer covers the frozen successful outputs')
        annotations, excluded = [], []
        for identifier, original in originals.items():
            item = submitted.get(identifier)
            if item is None:
                excluded.append(dict(item_id=identifier, reason='item_not_submitted'))
                continue
            if set(item) != ITEM_FIELDS or any(item[key] != original[key] for key in ITEM_FIELDS - {'grading'}):
                raise ValueError('Only grading may change; answer/question/scope/claims/citations must remain intact')
            entry = mapping[identifier]
            prediction = record_map[entry['question_id'], entry['system']]['prediction']
            annotation, reason = _grade(item['grading'], prediction)
            if reason:
                excluded.append(dict(item_id=identifier, reason=reason))
            else:
                annotations.append(annotation)
        predictions = [record['prediction'] for record in records]
        report = summarize_benchmark(manifest, predictions, annotations)
        report['review_import_notice'] = 'Supplied human-review declarations are self-reported; independence and qualifications are not verified.'
        identity = dict(submission_sha256=submission_sha, packet_sha256=packet_sha,
                        private_mapping_sha256=private_sha, input_fingerprint=manifest['input_fingerprint'])
        import_id = _hash(identity)
        base = _safe_directory(directory, 'reviewed_imports')
        target = base / import_id
        if target.is_symlink() or not target.resolve().is_relative_to(base.resolve()):
            raise ValueError('Review import path redirects')
        raw = ''.join(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n'
                      for row in annotations).encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise ValueError('Reviewed annotations exceed the size limit')
        if target.exists():
            saved_report, _ = _read_json(target / 'report.reviewed.json')
            saved_reviewer, _ = _read_json(target / 'reviewer_record.private.json')
            annotations_path = target / 'annotations.reviewed.jsonl'
            if annotations_path.is_symlink() or not annotations_path.is_file() or annotations_path.stat().st_size > MAX_BYTES:
                raise ValueError('Existing reviewed annotations redirect or exceed bounds')
            if (saved_report != report or annotations_path.read_bytes() != raw
                    or any(saved_reviewer.get(key) != value for key, value in dict(reviewer,
                        review_import_id=import_id, annotations_imported=len(annotations),
                        ungraded_items=excluded, **identity).items())):
                raise ValueError('Existing review import no longer matches its recorded identity')
        else:
            temporary = Path(tempfile.mkdtemp(prefix='.review-', dir=base))
            try:
                (temporary / 'annotations.reviewed.jsonl').write_bytes(raw)
                _write(temporary / 'report.reviewed.json', report)
                _write(temporary / 'reviewer_record.private.json', dict(reviewer,
                    imported_at=datetime.now(timezone.utc).isoformat(), review_import_id=import_id,
                    annotations_imported=len(annotations), ungraded_items=excluded, **identity))
                temporary.rename(target)
            finally:
                if temporary.exists():
                    if (temporary.is_symlink() or not temporary.resolve().is_relative_to(base.resolve())
                            or not temporary.name.startswith('.review-')):
                        raise ValueError('Refusing redirected temporary review cleanup')
                    shutil.rmtree(temporary)
        return dict(benchmark_run_id=run_id, review_import_id=import_id,
                    annotations_imported=len(annotations), pending_items=len(excluded),
                    requires_atomization=sum(row['reason'] == 'requires_atomization' for row in excluded),
                    reviewer_verification='self_reported_not_independently_verified',
                    annotations=str(target / 'annotations.reviewed.jsonl'),
                    report=str(target / 'report.reviewed.json'),
                    reviewer_record=str(target / 'reviewer_record.private.json'),
                    original_outputs_changed=False, previous_imports_merged=False)
