"""Deterministic public review handoff; no grades, inference or private mapping."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import zipfile

from .benchmark_review import ITEM_FIELDS, _failed, _index, _read_json, _visible
from .benchmark_run import MAX_BYTES, _directory, _hash, _read, _records, _write, prepare_review_packet
from .review import review_write_lock

MAX_TOTAL_BYTES = 8 * 1024 * 1024
DECLARATIONS = ('reviewer', 'qualification', 'reviewed_at', 'independence_declaration',
                'independent', 'human_review')
MEMBERS = frozenset({'review_packet.json', 'review_packet.template.json', 'corpus_snapshot.json',
                     'sources.json', 'benchmark_sources.json', 'INDEPENDENT_REVIEW.md',
                     'README.md', 'bundle_manifest.json'})


def _encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _safe(root, path):
    if not path.resolve().is_relative_to(root):
        raise ValueError('Review bundle path escapes project root')
    for component in (path, *path.parents):
        if component.is_symlink() or hasattr(component, 'is_junction') and component.is_junction():
            raise ValueError('Review bundle path redirects')
        if component == root:
            break
    return path


def _blob(root, path):
    path = _safe(root, path)
    if not path.is_file():
        raise ValueError('Required public review file is missing')
    with path.open('rb') as stream:
        content = stream.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise ValueError('Public review file exceeds the size limit')
    return content


def _validate_packet(directory, run_id):
    manifest, _ = _read_json(directory / 'manifest.json')
    if (manifest.get('run_id') != run_id or not isinstance(manifest.get('inputs'), dict)
            or _hash(manifest['inputs']) != manifest.get('input_fingerprint')):
        raise ValueError('Review bundle benchmark input mismatch')
    packet, _ = _read_json(directory / 'review_packet.json')
    private, _ = _read_json(directory / 'review_key.private.json')
    if any(value.get('benchmark_run_id') != run_id for value in (packet, private)):
        raise ValueError('Public packet or private mapping belongs to another run')
    originals = _index(packet.get('items'), 'public packet')
    mapping = _index(private.get('keys'), 'private mapping')
    if originals.keys() != mapping.keys():
        raise ValueError('Public packet IDs and private mapping differ')
    records = _records(directory, manifest)
    record_map = {(record['question_id'], record['system']): record for record in records}
    if len(record_map) != len(records):
        raise ValueError('Duplicate authoritative review record')
    questions = {}
    for question in manifest['inputs'].get('questions', []):
        if (not isinstance(question, dict) or not isinstance(question.get('question_id'), str)
                or not isinstance(question.get('question'), str) or question['question_id'] in questions):
            raise ValueError('Invalid or duplicate frozen review question')
        questions[question['question_id']] = question
    pairs = set()
    for identifier, entry in mapping.items():
        pair = entry.get('question_id'), entry.get('system')
        if not all(isinstance(value, str) for value in pair):
            raise ValueError('Malformed private review identity')
        record = record_map.get(pair)
        if (record is None or _failed(record) or pair in pairs or pair[0] not in questions
                or entry.get('prediction_sha256') != _hash(record['prediction'])):
            raise ValueError('Private mapping or frozen prediction hash is stale')
        pairs.add(pair)
        item = originals[identifier]
        expected = _visible(record, questions[pair[0]])
        if (set(item) != ITEM_FIELDS or item['grading'] is not None
                or {key:item[key] for key in expected} != expected):
            raise ValueError('Public packet answer or grades changed')
    if pairs != {pair for pair, record in record_map.items() if not _failed(record)}:
        raise ValueError('Review packet does not cover the saved successful outputs')
    corpus = _read(directory / 'corpus_snapshot.json')
    if not isinstance(corpus, list) or _hash(corpus) != manifest['inputs'].get('corpus_sha256'):
        raise ValueError('Review corpus snapshot mismatch')
    return manifest, packet


def _template(packet):
    value = deepcopy(packet)
    value.update({field:None for field in DECLARATIONS})
    value.update(review_method='human', assistance_disclosure='')
    return value


def prepare_review_bundle(root, run_id):
    """Export a fixed public allowlist while preserving existing shuffled item IDs.

    The packet is created only when both it and its private mapping are absent.
    An incomplete pair, changed packet, filled template or stale mapping fails
    closed. Only successful answer records enter review; missing grades stay null.
    """
    root = Path(root).resolve()
    directory = _directory(root, run_id)
    packet_path = _safe(root, directory / 'review_packet.json')
    _safe(root, directory / 'review_key.private.json')
    # The helper admits or validates the pair under the same writer lock. A
    # pre-lock existence test can race another exporter and replace item IDs.
    prepare_review_packet(root, run_id)
    with review_write_lock(directory):
        manifest, packet = _validate_packet(directory, run_id)
        for name in ('sources.json', 'benchmark_sources.json'):
            _read_json(_safe(root, root / 'data' / name))
        template = _template(packet)
        template_path = _safe(root, directory / 'review_packet.template.json')
        template_blob = _encoded(template)
        template_exists = template_path.exists()
        if template_exists:
            existing, _ = _read_json(template_path)
            # False, zero, empty strings and omitted declarations are edits,
            # not blank declarations. Hashing also distinguishes bool/int.
            if _hash(existing) != _hash(template):
                raise ValueError('Existing template has been edited; preserve it and use a reviewed copy')
            template_blob = _blob(root, template_path)
        files = {
            'review_packet.json': _blob(root, packet_path),
            'review_packet.template.json': template_blob,
            'corpus_snapshot.json': _blob(root, directory / 'corpus_snapshot.json'),
            'sources.json': _blob(root, root / 'data/sources.json'),
            'benchmark_sources.json': _blob(root, root / 'data/benchmark_sources.json'),
            'INDEPENDENT_REVIEW.md': _blob(root, root / 'docs/INDEPENDENT_REVIEW.md'),
        }
        instructions = (
            '# Independent review handoff\n\n'
            f'Benchmark run: {run_id}\nSuccessful answer items: {len(packet["items"])}\nScientific grades created: 0\n\n'
            'Read INDEPENDENT_REVIEW.md. Keep review_packet.json unchanged. Make a copy of '
            'review_packet.template.json, fill the actual reviewer declarations and change only '
            'item grading fields. Unknown labels remain null; compound or omitted assertions '
            'need requires_atomization rather than silently changed claim alignment.\n\n'
            'The corpus snapshot is the exact locally extracted context frozen for generation. '
            'Use each question\'s stated source scope and consult primary URLs for scientific '
            'interpretation. The two inventories describe source rights and provenance at export; '
            'their own file hashes are recorded in bundle_manifest.json.\n\n'
            'The private mapping, expected answers/rubrics and failed job bodies are excluded. '
            'Writing style can still reveal a system. This is not guaranteed blinding. '
            'Hashes establish local consistency, not publisher authenticity or scientific truth.\n\n'
            'Return the completed copy to the owner. The owner imports it using:\n\n'
            f'python -m axiom benchmark-review-import {run_id} completed-review.json\n\n'
            'No model or network request is made by this export or the import tool.\n')
        files['README.md'] = instructions.encode('utf-8')
        if sum(map(len, files.values())) > MAX_TOTAL_BYTES or any(len(value) > MAX_BYTES for value in files.values()):
            raise ValueError('Public review bundle exceeds size limits')
        inventory = dict(schema_version='ignis-review-bundle-v1', benchmark_run_id=run_id,
                         input_fingerprint=manifest['input_fingerprint'],
                         corpus_sha256=manifest['inputs']['corpus_sha256'], items=len(packet['items']),
                         grades_created=0, private_mapping_included=False,
                         files=[dict(path=name, bytes=len(value), sha256=hashlib.sha256(value).hexdigest())
                                for name,value in sorted(files.items())])
        files['bundle_manifest.json'] = _encoded(inventory)
        if set(files) != MEMBERS:
            raise ValueError('Public review bundle admission mismatch')
        if sum(map(len, files.values())) > MAX_TOTAL_BYTES or any(len(value) > MAX_BYTES for value in files.values()):
            raise ValueError('Public review bundle exceeds size limits')
        bundle = _safe(root, directory / 'review_bundle.zip')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.review-bundle-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, blob in sorted(files.items()):
                    info = zipfile.ZipInfo(name, date_time=(2026,1,1,0,0,0))
                    info.external_attr = (stat.S_IFREG | 0o644) << 16
                    archive.writestr(info, blob, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            temporary.replace(bundle)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        if not template_exists:
            _write(template_path, template)
        manifest_path = _safe(root, directory / 'review_bundle.manifest.json')
        _write(manifest_path, inventory)
        return dict(benchmark_run_id=run_id, bundle=str(bundle), packet=str(packet_path),
                    template=str(template_path), manifest=str(manifest_path), items=len(packet['items']),
                    grades_created=0, private_mapping_included=False,
                    bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest())
