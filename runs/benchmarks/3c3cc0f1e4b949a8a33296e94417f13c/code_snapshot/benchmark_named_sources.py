"""Reproducible, explicitly located NASA benchmark source descriptions.

Separate from the core PDF corpus. Catalog fields and file names never become
measurement rows. The offline loader replays extraction from hashed raw bytes;
local hashes detect corruption, not publisher authenticity or scientific truth.
"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.request import Request, build_opener

from .critic import CONDITIONS
from .ingest import CheckedRedirect, normalize, split_text, validate_url
from .source_text import extract_html_sections
from .archived_source import (ARCHIVE_URL, ARCHIVE_AS_OF, ORIGINAL_URL, PUBLICATION_DATE,
                              fetch_archived_blog, verify_archived_provenance, extract_archived_blog)

MAX_BYTES = 2_000_000
MANIFEST = 'data/benchmark_sources.json'
POLICY = 'https://www.nasa.gov/nasa-brand-center/images-and-media/'
NEWS = 'https://www.nasa.gov/centers-and-facilities/glenn/flame-burns-out-on-nasas-long-running-spacecraft-fire-experiment/'
FACTSHEET = 'https://www.nasa.gov/wp-content/uploads/2025/07/spacecraft-fire-safety-demonstration-saffire.pdf'
FLEX_TEXT = 'https://ntrs.nasa.gov/api/citations/20150023456/downloads/20150023456.txt'


def _psi(identifier, version, title, experiment, sections):
    accession = 'PSI-' + str(identifier)
    return dict(source_id='psi-' + str(identifier), title=title, experiment=experiment,
                source_kind='dataset_catalog', evidence_tier=3, sections=sections,
                url='https://psi.nasa.gov/physci/repo/data/investigations/' + accession,
                accession=accession, version=version,
                assets=[dict(key='record', url=f'https://psi.nasa.gov/geode-py/ws/repo/investigations/{accession}/{version}')])


SPECS = [
    _psi(69, 5, 'Flame Extinguishment Experiment (FLEX)', 'FLEX', ['Objectives', 'Approach']),
    _psi(25, 4, 'Burning and Suppression of Solids - II (BASS-II)', 'BASS-II', ['Objectives', 'DOI', 'License']),
    _psi(98, 4, 'Spacecraft Fire Safety Experiment - I (Saffire-I)', 'Saffire-I', ['Objectives', 'Files', 'DOI']),
    dict(source_id='named-rtdfs', title='Residence Time Driven Flame Spread (RTDFS)', experiment='RTDFS',
         source_kind='experiment_overview', evidence_tier=3,
         url='https://science.nasa.gov/biological-physical/investigations/rtdfs/',
         sections=['Science Objectives'], assets=[dict(key='article', url='https://science.nasa.gov/biological-physical/investigations/rtdfs/')]),
    dict(source_id='named-saffire-vi-news', title="Flame Burns Out on NASA's Long-Running Spacecraft Fire Experiment",
         experiment='Saffire-VI', source_kind='news_overview', evidence_tier=3, url=NEWS,
         sections=['Article, 2024-02-14'], assets=[dict(key='article', url=NEWS)]),
    dict(source_id='named-saffire-factsheet', title='Spacecraft Fire Safety Demonstration (Saffire)',
         experiment='Saffire', source_kind='factsheet', evidence_tier=3, url=FACTSHEET,
         sections=['Spacecraft Fire Safety'], assets=[dict(key='pdf', url=FACTSHEET)]),
    dict(source_id='ntrs-20150023456', title='Detailed Results from the Flame Extinguishment Experiment (FLEX) March 2009 to December 2011',
         experiment='FLEX', source_kind='technical_report', evidence_tier=1,
         url='https://ntrs.nasa.gov/citations/20150023456', sections=['report section 4.2'],
         assets=[dict(key='text', url=FLEX_TEXT), dict(key='rights', url='https://ntrs.nasa.gov/api/citations/20150023456')]),
    dict(source_id='named-flex-blog', title='Cool Flames on the International Space Station: An Anatomy of Discovery',
         experiment='FLEX', source_kind='scientist_explanation', evidence_tier=3, url=ORIGINAL_URL,
         sections=['Article, 2013-11-25'], archive_url=ARCHIVE_URL, archive_as_of=ARCHIVE_AS_OF,
         publication_date=PUBLICATION_DATE,
         assets=[dict(key='article', url=ARCHIVE_URL, archived=True)]),
]
SPECS[2]['assets'].append(dict(key='files', url='https://psi.nasa.gov/geode-py/ws/files/v2',
    body={'folder': 'PSI-98/', 'fileType': 'study', 'studyId': 'PSI-98', 'version': 4, 'obfuscationcode': ''}))
BY_ID = {spec['source_id']: spec for spec in SPECS}
PSI_DOIS = {'PSI-25': '10.60555/4qc4-de67', 'PSI-69': '10.60555/mbq8-0451', 'PSI-98': '10.60555/0t15-1z43'}


def _digest(blob):
    return hashlib.sha256(blob).hexdigest()


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _json(blob):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate named source JSON key')
            result[key] = value
        return result
    result = json.loads(blob, object_pairs_hook=pairs,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite source value')))
    if not isinstance(result, dict):
        raise ValueError('Named source JSON must be an object')
    return result


def _path(root, relative):
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Named source path escapes project root')
    return path


def _read(root, relative):
    path = _path(root, relative)
    with path.open('rb') as stream:
        blob = stream.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError('Named source exceeds size limit')
    return blob


def _write(root, relative, blob):
    path = _path(root, relative)
    if len(blob) > MAX_BYTES:
        raise ValueError('Named source output exceeds size limit')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    _path(root, str(temporary.relative_to(root)))
    temporary.write_bytes(blob)
    temporary.replace(path)


def _fetch(url, body=None):
    validate_url(url)
    data = None if body is None else _encoded(body)
    headers = {'User-Agent': 'IGNIS-research/0.1', 'Accept-Encoding': 'identity'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=data, headers=headers)
    with build_opener(CheckedRedirect()).open(request, timeout=30) as response:
        if response.url != url:
            raise ValueError('Named source redirected away from its exact URL: ' + response.url)
        length = response.headers.get('Content-Length')
        if length and int(length) > MAX_BYTES:
            raise ValueError('Named source exceeds size limit')
        blob = response.read(MAX_BYTES + 1)
        if len(blob) > MAX_BYTES:
            raise ValueError('Named source exceeds size limit')
        return blob, dict(url=url, final_url=response.url, method='GET' if body is None else 'POST',
                          request_body_sha256=None if data is None else _digest(data),
                          retrieved_at=datetime.now(timezone.utc).isoformat(), bytes=len(blob),
                          sha256=_digest(blob), content_type=response.headers.get('Content-Type', ''))


def _verify(blob, meta, asset):
    body = asset.get('body')
    if (not isinstance(meta, dict) or meta.get('url') != asset['url'] or meta.get('final_url') != asset['url']
            or meta.get('method') != ('GET' if body is None else 'POST')
            or meta.get('request_body_sha256') != (None if body is None else _digest(_encoded(body)))
            or meta.get('sha256') != _digest(blob) or type(meta.get('bytes')) is not int
            or meta['bytes'] != len(blob) or not meta.get('retrieved_at') or not meta.get('content_type')):
        raise ValueError('Named source provenance mismatch')
    if asset.get('archived'):
        verify_archived_provenance(meta)


def _asset(root, spec, asset):
    relative = f"data/raw/named/{spec['source_id']}-{asset['key']}.bin"
    sidecar = relative + '.provenance.json'
    if _path(root, relative).exists() or _path(root, sidecar).exists():
        blob, meta = _read(root, relative), _json(_read(root, sidecar))
    else:
        blob, meta = (fetch_archived_blog(asset['url']) if asset.get('archived')
                      else _fetch(asset['url'], asset.get('body')))
        _verify(blob, meta, asset)
        _write(root, relative, blob)
        _write(root, sidecar, _encoded(meta))
    _verify(blob, meta, asset)
    return blob, dict(meta, path=relative)


def _file_names(value, depth=0):
    if depth > 20 or not isinstance(value, list):
        raise ValueError('Invalid PSI file listing tree')
    names = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('Invalid PSI file listing entry')
        if item.get('restricted') is not False or item.get('restrictedAccess') is not False or item.get('visible') is not True:
            continue
        # Folder labels use displayName; leaf file paths are publisher key fields.
        name = item.get('displayName') or item.get('key')
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Missing PSI file listing name')
        names.append(name)
        if item.get('files'):
            names.extend(_file_names(item['files'], depth + 1))
    if len(names) > 2000:
        raise ValueError('PSI file listing exceeds bounds')
    return names


def _extract(spec, assets):
    """Return exact selected section text and rights; never experimental fields."""
    sections = []
    def add(section, text, locator):
        if not isinstance(text, str) or not normalize(text):
            raise ValueError('Named source section is missing: ' + section)
        sections.append((section, normalize(text), locator))
    if 'accession' in spec:
        record = _json(assets['record'])
        if (record.get('accession') != spec['accession'] or type(record.get('version')) is not int
                or record['version'] != spec['version'] or record.get('public') is not True
                or record.get('restricted') is not False or record.get('licenseIdentifier') != 'CC0-1.0'
                or record.get('licenseLink') != 'https://spdx.org/licenses/CC0-1.0.html'
                or record.get('doi') != PSI_DOIS[spec['accession']]):
            raise ValueError('PSI identity, version, access or license mismatch')
        # Field paths are publisher JSON names, not inferred measurement columns.
        for section in spec['sections']:
            if section == 'Files':
                names = _file_names(_json(assets['files']).get('files'))
                if not names:
                    raise ValueError('Empty PSI file listing')
                add(section, '\n'.join(names), 'PSI Files tab; recursive JSON files[].displayName (folders) and key (file paths); listing only')
            else:
                key = {'Objectives': 'objective', 'Approach': 'approach', 'DOI': 'doi', 'License': 'licenseIdentifier'}[section]
                text = record.get(key)
                if section in ('Objectives', 'Approach'):
                    # PSI objective/approach values may be HTML fragments.
                    text = _fragment(text)
                add(section, text, 'PSI version ' + str(spec['version']) + '; JSON field ' + key)
        rights = dict(statement='CC0-1.0', url=record.get('licenseLink'), basis='Publisher licenseIdentifier in version-pinned PSI JSON')
    elif spec['source_id'] == 'ntrs-20150023456':
        rights_record = _json(assets['rights'])
        if (rights_record.get('id') != 20150023456 or rights_record.get('distribution') != 'PUBLIC'
                or rights_record.get('copyright', {}).get('determinationType') not in ('PUBLIC_USE_PERMITTED', 'GOV_PUBLIC_USE_PERMITTED')):
            raise ValueError('FLEX report distribution or rights not permitted')
        text = assets['text'].decode('utf-8-sig')
        matches = list(re.finditer(r'(?m)^\s*4\.2\s+Analyzed Data\s*$', text))
        if len(matches) != 1:
            raise ValueError('Cannot uniquely locate FLEX report section 4.2 body')
        tail = text[matches[0].end():]
        end = re.search(r'(?m)^\s*5\.0\s+Observations and Discussion\s*$', tail)
        if not end:
            raise ValueError('Cannot locate FLEX report section 4.2 end')
        add('report section 4.2', tail[:end.start()], 'NASA report section 4.2 Analyzed Data; printed page 16; official NTRS text extraction')
        rights = dict(statement=rights_record['copyright']['determinationType'], url=spec['url'], basis='Document-specific NTRS public-use determination')
    elif spec['source_id'] == 'named-flex-blog':
        for row in extract_archived_blog(assets['article']):
            add(row['section'], row['text'], row['locator'])
        rights = dict(_nasa_rights(),
            basis='NASA factual/informational prose-use guidance, checked 2026-11-06; original NASA article in an identified Internet Archive capture; no media, comments or endorsement')
    elif 'pdf' in assets:
        from pypdf import PdfReader
        if not assets['pdf'].startswith(b'%PDF-'):
            raise ValueError('Expected Saffire factsheet PDF')
        reader = PdfReader(io.BytesIO(assets['pdf']))
        if reader.is_encrypted or len(reader.pages) != 2:
            raise ValueError('Unexpected Saffire factsheet structure')
        text = reader.pages[0].extract_text() or ''
        start = re.search(r'Spacecraft\s+Fire\s+Safety\s*\n', text)
        end = re.search(r'\bSaffire-I\b', text[start.end():]) if start else None
        if not start or not end:
            raise ValueError('Cannot locate Saffire factsheet section')
        add('Spacecraft Fire Safety', text[start.end():start.end() + end.start()], 'PDF physical page 1; heading Spacecraft Fire Safety; before Saffire-I')
        rights = _nasa_rights()
    else:
        extracted = extract_html_sections(assets['article'])
        if spec['source_id'] == 'named-rtdfs':
            selected = [row for row in extracted if row['section'].split(' / ')[-1] == 'Science Objectives']
            if not selected:
                raise ValueError('RTDFS Science Objectives missing')
            for row in selected:
                add('Science Objectives', row['text'], row['locator'])
        else:
            for row in extracted:
                add('Article, 2024-02-14', row['text'], row['locator'])
        rights = _nasa_rights()
    chunks = []
    for section, text, locator in sections:
        for part in split_text(text):
            digest = _digest(part.encode('utf-8'))
            asset_key = ('files' if section == 'Files' else 'record') if 'accession' in spec else ('text' if 'text' in assets else 'pdf' if 'pdf' in assets else 'article')
            chunks.append(dict(chunk_id=f"{spec['source_id']}-named-{len(chunks)+1:03d}-{digest[:16]}",
                source_id=spec['source_id'], title=spec['title'], experiment=spec['experiment'], url=spec['url'],
                document_url=spec.get('archive_url') or (spec['url'] if 'pdf' in assets else None), text=part, sha256=digest,
                source_kind=spec['source_kind'], evidence_tier=spec['evidence_tier'], section=section,
                locator=section + '; ' + locator, conditions={key: None for key in CONDITIONS},
                evidence_role='source_description' if 'accession' in spec else 'scoped_document_text',
                named_scope_verified=True, source_asset_key=asset_key, permission_status='allowed', status='active',
                notice='Exact located source text; no measurement-table extraction or scientific review is implied.'))
            if spec.get('archive_url'):
                chunks[-1].update(original_url=spec['url'], archive_url=spec['archive_url'],
                    archive_as_of=spec['archive_as_of'], publication_date=spec['publication_date'],
                    notice='Original NASA article in a dated archived copy, not a current NASA canonical page; scientific interpretation is unreviewed.')
    if not chunks:
        raise ValueError('Named source has no selected text')
    return chunks, rights


def _fragment(text):
    if not isinstance(text, str):
        raise ValueError('PSI prose field must be text')
    if '<' not in text:
        return text
    rows = extract_html_sections(('<main><article><div class="entry-content">' + text + '</div></article></main>').encode())
    return '\n'.join(row['text'] for row in rows)


def _nasa_rights():
    return dict(statement='NASA factual/informational text use with attribution; no document-specific CC license identified',
                url=POLICY, basis='NASA media-use guidance, checked 2026-11-05; selected prose only, excluding third-party media; no endorsement')


def collect_named_sources(root):
    """Fetch missing exact assets, reuse valid caches, and save a bounded manifest.

    No refresh silently replaces old raw bytes. Failed sources remain explicit.
    The legacy FLEX blog uses one verified archived original, never a generic
    blog listing or an unrelated replacement article.
    """
    root = Path(root).resolve()
    records = []
    for spec in SPECS:
        record = {key: spec[key] for key in ('source_id', 'title', 'url', 'experiment', 'source_kind', 'evidence_tier')}
        try:
            assets, provenance = {}, []
            for asset in spec['assets']:
                blob, meta = _asset(root, spec, asset)
                assets[asset['key']] = blob
                provenance.append(dict(meta, key=asset['key']))
            chunks, rights = _extract(spec, assets)
            relative = f"data/processed/named_sources/{spec['source_id']}.json"
            output = _encoded(chunks)
            _write(root, relative, output)
            record.update(status='active', permission_status='allowed', rights=rights,
                          assets=provenance, derived_path=relative, derived_sha256=_digest(output),
                          chunk_count=len(chunks), sections=spec['sections'])
            if spec.get('archive_url'):
                record.update(original_url=spec['url'], archive_url=spec['archive_url'],
                    archive_as_of=spec['archive_as_of'], publication_date=spec['publication_date'],
                    source_availability='archived_original')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            record.update(status='unavailable', permission_status='pending', reason=f'{type(exc).__name__}: {exc}')
        records.append(record)
    generated_at = datetime.now(timezone.utc).isoformat()
    if _path(root, MANIFEST).exists():
        previous = _json(_read(root, MANIFEST))
        if previous.get('sources') == records:
            generated_at = previous['generated_at']
    manifest = dict(schema_version='named-benchmark-sources-v1', generated_at=generated_at,
                    sources=records, active_sources=sum(r['status'] == 'active' for r in records),
                    failed_sources=sum(r['status'] != 'active' for r in records),
                    notice='Source snapshots, no independently reviewed scientific labels or raw experimental measurements.')
    _write(root, MANIFEST, _encoded(manifest))
    return manifest


def _load(root):
    root = Path(root).resolve()
    if not _path(root, MANIFEST).exists():
        return [], []
    manifest = _json(_read(root, MANIFEST))
    if (not isinstance(manifest, dict) or manifest.get('schema_version') != 'named-benchmark-sources-v1'
            or not isinstance(manifest.get('sources'), list) or len(manifest['sources']) > 20):
        raise ValueError('Invalid named source manifest')
    inventory, chunks, seen = [], [], set()
    for record in manifest['sources']:
        if not isinstance(record, dict) or not isinstance(record.get('source_id'), str):
            raise ValueError('Invalid named source record')
        identifier = record['source_id']
        if identifier in seen:
            raise ValueError('Duplicate named source ID')
        seen.add(identifier)
        if record.get('status') != 'active':
            if record.get('status') != 'unavailable' or record.get('permission_status') != 'pending':
                raise ValueError('Invalid named source state')
            if identifier not in BY_ID:
                raise ValueError('Unknown unavailable named source')
            inventory.append(dict(record))
            continue
        spec = BY_ID.get(identifier)
        if not spec or record.get('permission_status') != 'allowed' or any(record.get(k) != spec[k] for k in ('url', 'title', 'source_kind', 'experiment', 'evidence_tier')):
            raise ValueError('Named source identity or rights mismatch')
        if spec.get('archive_url') and any(record.get(key) != expected for key, expected in (
                ('original_url', spec['url']), ('archive_url', spec['archive_url']),
                ('archive_as_of', spec['archive_as_of']), ('publication_date', spec['publication_date']),
                ('source_availability', 'archived_original'))):
            raise ValueError('Named archived source identity or capture mismatch')
        provenance = record.get('assets', [])
        if (not isinstance(provenance, list) or not all(isinstance(meta, dict) for meta in provenance)
                or len(provenance) != len(spec['assets'])):
            raise ValueError('Incomplete named source provenance')
        assets = {}
        for asset, meta in zip(spec['assets'], provenance):
            relative = f"data/raw/named/{identifier}-{asset['key']}.bin"
            if meta.get('path') != relative or meta.get('key') != asset['key']:
                raise ValueError('Named raw source path mismatch')
            blob = _read(root, relative)
            sidecar = _json(_read(root, relative + '.provenance.json'))
            if {k: v for k, v in meta.items() if k not in ('path', 'key')} != sidecar:
                raise ValueError('Named source sidecar mismatch')
            _verify(blob, meta, asset)
            assets[asset['key']] = blob
        expected, rights = _extract(spec, assets)
        relative = f'data/processed/named_sources/{identifier}.json'
        if record.get('derived_path') != relative or record.get('rights') != rights or record.get('sections') != spec['sections']:
            raise ValueError('Named derived source identity mismatch')
        derived = _read(root, relative)
        if record.get('derived_sha256') != _digest(derived) or derived != _encoded(expected) or record.get('chunk_count') != len(expected):
            raise ValueError('Named source extraction or digest mismatch')
        inventory.append(dict(record))
        for chunk in expected:
            origin = next(meta for meta in provenance if meta['key'] == chunk['source_asset_key'])
            chunk['source_sha256'] = origin['sha256']
            chunk['provenance'] = provenance
        chunks.extend(expected)
    return inventory, chunks


def load_named_chunks(root):
    return _load(root)[1]


def load_named_inventory(root):
    return _load(root)[0]
