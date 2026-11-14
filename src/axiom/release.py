"""Bounded, deterministic offline release archives with explicit file integrity.

This is a text-corpus distribution: original PDF hashes/URLs remain in the source
inventory, while core PDF bytes, credentials, model caches and private review mappings
are excluded. Local hashes detect tampering; they are not publisher signatures.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

RUN_IDS = ('3c3cc0f1e4b949a8a33296e94417f13c',)
PRIMARY_RUN = RUN_IDS[-1]
MAX_FILE_BYTES = 2_000_000
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_FILES = 1500
ARCHIVE_NAME = 'axiom-release.zip'
MANIFEST_NAME = 'release_manifest.json'
ROOT_FILES = ('README.md', 'AGENTS.md', 'pyproject.toml', 'requirements.txt')
OPTIONAL_ROOT_FILES = ('launch.ps1', 'launch.cmd', 'DEVELOPMENT_HISTORY.md', 'CHALLENGE_NOTES.md', 'PROJECT_WORK.md', 'LICENSE')
WHEELS = ('pypdf-6.13.0-py3-none-any.whl', 'setuptools-80.9.0-py3-none-any.whl')
DATA_FILES = ('sources.json', 'benchmark_sources.json', 'conditions.jsonl', 'review_queue.jsonl',
              'condition.schema.json', 'chunk.schema.json', 'demo.json')
RUN_FILES = ('manifest.json', 'report.json', 'corpus_snapshot.json', 'conditions_snapshot.json',
             'predictions.json', 'predictions.jsonl', 'engineering_audit.json', 'failure_hashes.json',
             'review_packet.json', 'review_packet.template.json')


def _encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _name(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid release member path')
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in ('', '.', '..') for part in path.parts):
        raise ValueError('Invalid release member path')
    lowered = [part.lower() for part in path.parts]
    if (any(part in ('.env', '.git', '.venv', '__pycache__', 'model-cache', 'model_cache', 'cache') for part in lowered)
            or any('.private.' in part or part.endswith('.pyc') or part.endswith('.egg-info') for part in lowered)):
        raise ValueError('Private or generated cache member is excluded')
    return value


def _redirect(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def _safe(root, relative):
    relative = _name(relative)
    path = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if _redirect(current):
            raise ValueError('Redirected release source is excluded')
    if not path.resolve().is_relative_to(root):
        raise ValueError('Release source escapes project root')
    return path


def _read(root, relative):
    path = _safe(root, relative)
    if not path.is_file():
        raise ValueError('Required release file is missing: ' + relative)
    with path.open('rb') as stream:
        blob = stream.read(MAX_FILE_BYTES + 1)
    if len(blob) > MAX_FILE_BYTES:
        raise ValueError('Release source exceeds file size limit: ' + relative)
    return blob


def _json(root, relative):
    value = json.loads(_read(root, relative))
    if not isinstance(value, dict):
        raise ValueError('Release metadata must be an object')
    return value


def _sources(root):
    names = set(ROOT_FILES)
    names.update(name for name in OPTIONAL_ROOT_FILES if _safe(root, name).exists())
    names.update('wheelhouse/' + name for name in WHEELS if _safe(root, 'wheelhouse/' + name).exists())
    for base, extensions in (('src/axiom', {'.py', '.html'}), ('tests', {'.py', '.cjs'}), ('docs', {'.md'})):
        directory = _safe(root, base)
        if not directory.is_dir():
            raise ValueError('Required release source directory is missing: ' + base)
        for path in directory.rglob('*'):
            relative = path.relative_to(root).as_posix()
            if '__pycache__' in path.parts:
                continue
            if _redirect(path):
                raise ValueError('Redirected release source is excluded')
            if path.is_file() and path.suffix in extensions:
                names.add(_name(relative))
    names.update('data/' + name for name in DATA_FILES if _safe(root, 'data/' + name).exists())
    feedback = 'data/participant_feedback/2026-11-02-five-passages.json'
    if _safe(root, feedback).exists():
        names.add(feedback)
    names.update(('data/processed/chunks.jsonl', 'data/processed/manifest.json'))
    core = _json(root, 'data/processed/manifest.json')
    identifiers = {'ntrs-20160000593', 'ntrs-20150023456'}
    identifiers.update(source['source_id'] for source in core.get('sources', []) if source.get('status') == 'ingested')
    for identifier in identifiers:
        if not isinstance(identifier, str) or not re.fullmatch(r'ntrs-\d+', identifier):
            raise ValueError('Invalid core source identity for release')
        names.update((f'data/raw/{identifier}.json', f'data/raw/{identifier}.json.provenance.json'))
    named = _json(root, 'data/benchmark_sources.json')
    for source in named.get('sources', []):
        if source.get('status') != 'active':
            continue
        for asset in source.get('assets', []):
            relative = asset.get('path')
            if not isinstance(relative, str) or not re.fullmatch(r'data/raw/named/[A-Za-z0-9_-]+\.bin', relative):
                raise ValueError('Invalid named raw asset path')
            names.update((relative, relative + '.provenance.json'))
        relative = source.get('derived_path')
        if not isinstance(relative, str) or not re.fullmatch(r'data/processed/named_sources/[A-Za-z0-9_-]+\.json', relative):
            raise ValueError('Invalid named derived asset path')
        names.add(relative)
    for path in _safe(root, 'benchmarks').glob('*'):
        if _redirect(path):
            raise ValueError('Redirected benchmark source is excluded')
        if path.is_file() and path.suffix in ('.json', '.jsonl'):
            names.add(path.relative_to(root).as_posix())
    for identifier in RUN_IDS:
        base = 'runs/benchmarks/' + identifier
        manifest = _json(root, base + '/manifest.json')
        if manifest.get('run_id') != identifier:
            raise ValueError('Selected benchmark identity mismatch')
        for filename in RUN_FILES:
            if _safe(root, base + '/' + filename).exists():
                names.add(base + '/' + filename)
        for filename in ('manifest.json', 'report.json', 'corpus_snapshot.json', 'conditions_snapshot.json'):
            names.add(base + '/' + filename)
        for job in manifest.get('jobs', []):
            qid, system = job.get('question_id'), job.get('system')
            if not isinstance(qid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', qid) or system not in ('baseline', 'rag_only', 'ignis'):
                raise ValueError('Invalid benchmark job path')
            relative = f'{base}/jobs/{qid}--{system}.json'
            if _safe(root, relative).exists():
                names.add(relative)
        for filename in manifest.get('inputs', {}).get('code_sha256', {}):
            if not isinstance(filename, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*\.py', filename):
                raise ValueError('Invalid frozen code path')
            names.add(base + '/code_snapshot/' + filename)
    if len(names) > MAX_FILES:
        raise ValueError('Release exceeds file count limit')
    return sorted(names)


def _allowed(name):
    """The archive cannot enlarge its admission policy by changing its manifest."""
    if name in (*ROOT_FILES, *OPTIONAL_ROOT_FILES) or name in {'wheelhouse/' + wheel for wheel in WHEELS}:
        return True
    if re.fullmatch(r'(src/axiom/.+\.(py|html)|tests/.+\.(py|cjs)|docs/.+\.md|benchmarks/[^/]+\.(json|jsonl))', name):
        return True
    if name in {'data/' + file for file in DATA_FILES} | {'data/processed/chunks.jsonl', 'data/processed/manifest.json', 'data/participant_feedback/2026-11-02-five-passages.json'}:
        return True
    if re.fullmatch(r'data/(raw/ntrs-\d+\.json(\.provenance\.json)?|raw/named/[A-Za-z0-9_-]+\.bin(\.provenance\.json)?|processed/named_sources/[A-Za-z0-9_-]+\.json)', name):
        return True
    for identifier in RUN_IDS:
        prefix = 'runs/benchmarks/' + identifier + '/'
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix):]
        return rest in RUN_FILES or bool(re.fullmatch(r'jobs/[A-Za-z0-9_-]{1,100}--(baseline|rag_only|ignis)\.json|code_snapshot/[A-Za-z][A-Za-z0-9_]*\.py', rest))
    return False


def _credential_values(root):
    from .providers import settings
    values = settings(root)
    secrets = []
    for name in ('GROQ_KEY', 'OPENROUTER_KEY'):
        value = values.get(name)
        if isinstance(value, str) and len(value) >= 8:
            secrets.extend((value.encode(), json.dumps(value).encode()[1:-1]))
    return secrets


def _check_source_snapshots(files):
    core = json.loads(files['data/processed/manifest.json'])
    if (core.get('corpus_sha256') != _sha(files['data/processed/chunks.jsonl'])
            or core.get('sources_inventory_sha256') != _sha(files['data/sources.json'])):
        raise ValueError('Core corpus or inventory differs from its source manifest')
    named = json.loads(files['data/benchmark_sources.json'])
    for source in named.get('sources', []):
        if source.get('status') != 'active':
            continue
        for asset in source.get('assets', []):
            blob = files[asset['path']]
            sidecar = json.loads(files[asset['path'] + '.provenance.json'])
            declared = {key: value for key, value in asset.items() if key not in ('path', 'key')}
            if (asset.get('sha256') != _sha(blob) or asset.get('bytes') != len(blob) or sidecar != declared):
                raise ValueError('Named source differs from its provenance manifest')
        if source.get('derived_sha256') != _sha(files[source['derived_path']]):
            raise ValueError('Named extracted source differs from its manifest')


def _output(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if _redirect(parent):
            raise ValueError('Release output directory redirects')
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_release(root, output_dir):
    """Create a repeatable local ZIP, embedded manifest and SHA256 sidecar.

    Only allowlisted project files and four selected frozen benchmark histories
    are admitted. Existing release outputs are replaced atomically. No model or
    network calls occur. The owner must still run the clean-install checks.
    """
    root = Path(root).resolve()
    files, total = {}, 0
    secrets = _credential_values(root)
    for name in _sources(root):
        if not _allowed(name):
            raise ValueError('File is outside the release admission policy')
        blob = _read(root, name)
        if any(secret in blob for secret in secrets):
            raise ValueError('A configured provider credential appears in a release artifact')
        total += len(blob)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Release exceeds total size limit')
        files[name] = blob
    _check_source_snapshots(files)
    progress = _json(root, f'runs/benchmarks/{PRIMARY_RUN}/report.json')['progress']['overall']
    if any(type(progress.get(key)) is not int or progress[key] < 0 for key in ('scheduled', 'completed', 'failed', 'pending', 'graded')):
        raise ValueError('Invalid saved benchmark accounting')
    if progress['scheduled'] != progress['completed'] + progress['failed'] + progress['pending']:
        raise ValueError('Saved benchmark accounting does not balance')
    manifest = dict(schema_version='ignis-release-v1', kind='offline-text-corpus-and-saved-comparison',
                    file_count=len(files), total_bytes=total,
                    files=[dict(path=name, bytes=len(blob), sha256=_sha(blob)) for name, blob in files.items()],
                    benchmark_run_ids=list(RUN_IDS), primary_benchmark_run=PRIMARY_RUN,
                    benchmark_status={key: progress[key] for key in ('scheduled', 'completed', 'failed', 'pending', 'graded')},
                    requirements='Python 3.12+; pypdf==6.13.0 for PDF ingestion and named-source replay',
                    exclusions=['credentials', 'model caches', 'private review mapping', 'Git history', 'core PDF collection bytes'],
                    notice='Saved outputs are replayed observations, not new inference or scientific validation.')
    output = _output(output_dir)
    archive = output / ARCHIVE_NAME
    temporary = output / (ARCHIVE_NAME + '.tmp')
    for path in (archive, temporary, output / MANIFEST_NAME, output / (ARCHIVE_NAME + '.sha256')):
        if _redirect(path):
            raise ValueError('Release output file redirects')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for name, blob in sorted(dict(files, **{MANIFEST_NAME: _encoded(manifest)}).items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                package.writestr(info, blob, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    (output / MANIFEST_NAME).write_bytes(_encoded(manifest))
    digest = _sha(archive.read_bytes())
    (output / (ARCHIVE_NAME + '.sha256')).write_text(digest + '  ' + ARCHIVE_NAME + '\n', encoding='ascii')
    verified = verify_release(archive)
    return dict(archive=str(archive), manifest=str(output / MANIFEST_NAME), archive_sha256=digest,
                files=len(files), bytes=archive.stat().st_size, benchmark_status=manifest['benchmark_status'],
                verified=verified['verified'])


def verify_release(path):
    """Verify a ZIP's bounded canonical paths, complete manifest and every hash.

    This does not extract files or trust the ZIP's own filesystem permissions.
    Manifest/hash agreement is an integrity check, not proof of authorship.
    """
    path = Path(path)
    if path.is_dir():
        path = path / ARCHIVE_NAME
    if _redirect(path) or not path.is_file() or path.stat().st_size > MAX_TOTAL_BYTES + MAX_FILE_BYTES:
        raise ValueError('Invalid or oversized release archive')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES + 1:
            raise ValueError('Release exceeds file count limit')
        names = [_name(entry.filename) for entry in entries]
        if any(name != MANIFEST_NAME and not _allowed(name) for name in names):
            raise ValueError('Archive member is outside the release admission policy')
        if len(set(name.casefold() for name in names)) != len(names):
            raise ValueError('Duplicate release member')
        if any(entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.file_size > MAX_FILE_BYTES for entry in entries):
            raise ValueError('Unsupported or oversized release member')
        if sum(entry.file_size for entry in entries) > MAX_TOTAL_BYTES + MAX_FILE_BYTES:
            raise ValueError('Release exceeds total size limit')
        manifest = json.loads(archive.read(MANIFEST_NAME))
        if not isinstance(manifest, dict) or manifest.get('schema_version') != 'ignis-release-v1' or not isinstance(manifest.get('files'), list):
            raise ValueError('Invalid release manifest')
        expected = {}
        for record in manifest['files']:
            name = _name(record['path'])
            if name in expected or name == MANIFEST_NAME:
                raise ValueError('Duplicate release manifest entry')
            expected[name] = record
        if set(names) != set(expected) | {MANIFEST_NAME}:
            raise ValueError('Release members differ from the manifest')
        total = 0
        for name, record in expected.items():
            blob = archive.read(name)
            if record.get('bytes') != len(blob) or record.get('sha256') != _sha(blob):
                raise ValueError('Release member digest mismatch: ' + name)
            total += len(blob)
        if manifest.get('file_count') != len(expected) or manifest.get('total_bytes') != total:
            raise ValueError('Release manifest accounting mismatch')
    return dict(verified=True, archive=str(path.resolve()), archive_sha256=_sha(path.read_bytes()),
                files=len(expected), total_bytes=total, benchmark_status=manifest.get('benchmark_status'),
                notice='Byte integrity verified; no scientific grading or publisher authentication implied.')
