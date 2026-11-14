"""Offline, provenance-checked NTRS abstracts for explicitly scoped benchmarks.

This adapter never rewrites the main corpus or substitutes a PDF for an abstract.
The local provenance digest detects cache corruption; it is not a NASA signature.
"""
import hashlib
import json
from pathlib import Path

from .critic import CONDITIONS


ABSTRACT_SOURCES = {
    '20160000593': ('PRESENTATION', 'presentation_abstract'),
    '20150023456': ('TECHNICAL_PUBLICATION', 'technical_report_abstract'),
}
PUBLIC_RIGHTS = frozenset({'PUBLIC_USE_PERMITTED', 'GOV_PUBLIC_USE_PERMITTED'})
ALLOWED_SOURCE_STATES = frozenset({'active', 'ingested', 'large_file_deferred'})
MAX_METADATA_BYTES = 2_000_000


def _within_root(root, path):
    if not path.resolve().is_relative_to(root):
        raise ValueError('Benchmark scope cache path escapes project root')
    return path


def _read_bytes(root, path):
    _within_root(root, path)
    if not path.is_file():
        raise ValueError('Benchmark scope cache is not a regular file')
    with path.open('rb') as handle:
        content = handle.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError('Benchmark scope metadata exceeds size limit')
    return content


def _json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key in benchmark scope metadata')
            result[key] = value
        return result

    try:
        result = json.loads(content.decode('utf-8-sig'), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid benchmark scope JSON') from exc
    if not isinstance(result, dict):
        raise ValueError('Benchmark scope JSON must be an object')
    return result


def load_scope_chunks(root):
    """Return verified cached abstract chunks for the two named NTRS references.

    Missing inventory, missing source entries, missing metadata, or an empty
    abstract produce no chunk. Inventory rights/state holds exclude the source.
    A present metadata file requires its matching provenance sidecar. Malformed
    records, mismatched IDs/URLs/hashes, or inconsistent distribution rights
    raise ValueError. No downloads or human/scientific approval occur here.
    """
    root = Path(root).resolve()
    inventory_path = _within_root(root, root / 'data/sources.json')
    if not inventory_path.exists():
        return []
    inventory = _json(_read_bytes(root, inventory_path)).get('sources')
    if not isinstance(inventory, list) or any(not isinstance(s, dict) for s in inventory):
        raise ValueError('Invalid benchmark source inventory')
    selected = {}
    for source in inventory:
        source_id = source.get('source_id')
        if source_id not in {'ntrs-' + identifier for identifier in ABSTRACT_SOURCES}:
            continue
        if source_id in selected:
            raise ValueError('Duplicate benchmark source inventory entry')
        selected[source_id] = source

    chunks = []
    for identifier, (sti_type, abstract_kind) in ABSTRACT_SOURCES.items():
        source_id = 'ntrs-' + identifier
        source = selected.get(source_id)
        if source is None:
            continue
        if source.get('permission_status') != 'allowed':
            continue
        if source.get('status') not in ALLOWED_SOURCE_STATES:
            continue
        metadata_url = 'https://ntrs.nasa.gov/api/citations/' + identifier
        citation_url = 'https://ntrs.nasa.gov/citations/' + identifier
        if (str(source.get('ntrs_id')) != identifier
                or source.get('metadata_url') != metadata_url
                or source.get('url') != citation_url):
            raise ValueError('Benchmark source identity or HTTPS URL mismatch')
        path = _within_root(root, root / 'data/raw' / (source_id + '.json'))
        sidecar = _within_root(root, path.with_name(path.name + '.provenance.json'))
        if not path.exists():
            if path.is_symlink():
                raise ValueError('Broken benchmark metadata link')
            continue
        content = _read_bytes(root, path)
        provenance = _json(_read_bytes(root, sidecar))
        digest = hashlib.sha256(content).hexdigest()
        if (provenance.get('sha256') != digest
                or provenance.get('url') != metadata_url
                or provenance.get('final_url') != metadata_url
                or type(provenance.get('bytes')) is not int
                or provenance['bytes'] != len(content)):
            raise ValueError('Benchmark metadata provenance mismatch')
        content_type = provenance.get('content_type')
        retrieved_at = provenance.get('retrieved_at')
        if (not isinstance(content_type, str)
                or content_type.split(';', 1)[0].strip().lower() != 'application/json'
                or not isinstance(retrieved_at, str) or not retrieved_at.strip()):
            raise ValueError('Incomplete benchmark metadata provenance')
        metadata = _json(content)
        if type(metadata.get('id')) is not int or metadata['id'] != int(identifier):
            raise ValueError('Cached NTRS record ID mismatch')
        if metadata.get('stiType') != sti_type:
            raise ValueError('Cached NTRS record type mismatch')
        copyright_info = metadata.get('copyright')
        if (metadata.get('distribution') != 'PUBLIC'
                or not isinstance(copyright_info, dict)
                or copyright_info.get('determinationType') not in PUBLIC_RIGHTS):
            raise ValueError('Cached NTRS distribution or rights are not permitted')
        declared_rights = source.get('rights_determination')
        if declared_rights is not None and declared_rights != copyright_info['determinationType']:
            raise ValueError('Inventory and cached NTRS rights disagree')
        text = metadata.get('abstract')
        if text is None or text == '' or isinstance(text, str) and not text.strip():
            continue
        if not isinstance(text, str):
            raise ValueError('Cached NTRS abstract must be text')
        title = metadata.get('title')
        experiment = source.get('experiment')
        tier = source.get('evidence_tier')
        if (not isinstance(title, str) or not title.strip()
                or not isinstance(experiment, str) or not experiment.strip()
                or type(tier) is not int or tier < 1):
            raise ValueError('Invalid abstract description or evidence tier')
        text_digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        chunks.append({
            'chunk_id': source_id + '-abstract-' + text_digest[:16],
            'source_id': source_id, 'title': title, 'url': citation_url,
            'metadata_url': metadata_url, 'document_url': None,
            'locator': 'NTRS metadata abstract', 'text': text,
            'sha256': text_digest, 'source_sha256': digest,
            'source_kind': abstract_kind, 'experiment': experiment,
            'evidence_tier': tier, 'conditions': {key: None for key in CONDITIONS},
            'permission_status': 'allowed', 'status': 'active',
            'source_inventory_status': source['status'],
            'provenance': {key: provenance[key] for key in
                           ('url', 'final_url', 'retrieved_at', 'sha256', 'bytes', 'content_type')},
            'scope': 'abstract_only',
            'notice': 'Metadata abstract only; no full report or scientific validation is implied.',
        })
    return chunks
