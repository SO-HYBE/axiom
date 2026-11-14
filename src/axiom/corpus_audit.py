"""Report Phase 1 coverage without confusing AI drafts with human review."""
import argparse
import json
from pathlib import Path
from collections import Counter
from .research import load_chunks


def audit(root):
    chunks = load_chunks(root)
    path = root / 'data/conditions.jsonl'
    records = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []
    sources = {c['source_id']: c for c in chunks}
    from .conditions import validate_records
    validation = validate_records(records, chunks)
    valid_ids = set(validation['valid_record_ids'])
    reviewed = [r for r in records if r.get('record_id') in valid_ids and r.get('review_status') == 'human_reviewed' and r.get('reviewer')]

    from .review import rows, review_state
    state = review_state(root, chunks, records, rows(root/'data/review_queue.jsonl'))
    decisions = {key for key, event in state.items() if event['decision'] == 'accept'}
    condition_ids = {r['record_id'] for r in reviewed if ('condition',r['record_id']) not in state}
    condition_ids.update(item for kind,item in decisions if kind == 'condition')
    passage_ids = {item for kind,item in decisions if kind == 'passage'}
    participant_cases = 0
    for path in (root/'data/participant_feedback').glob('*.json'):
        feedback = json.loads(path.read_text(encoding='utf-8'))
        if feedback.get('type') == 'participant_textual_support_pilot':
            participant_cases += len(feedback.get('cases', []))
    engineering_ready = len(sources) >= 12 and validation['valid_count'] >= 20 and not validation['errors'] and not validation['corpus_errors']
    return {
        'phase': 1,
        'engineering_ready': engineering_ready,
        'scientific_validation_status': 'pending_qualified_review',
        'next_engineering_phase': 2 if engineering_ready else 1,
        'documents': len(sources),
        'passages': len(chunks),
        'experiment_families': dict(Counter(c['experiment'] for c in sources.values())),
        'participant_feedback_cases': participant_cases,
        'condition_records': len(records),
        'provenance_valid_conditions': validation['valid_count'],
        'condition_validation_errors': validation['errors'],
        'human_reviewed_condition_records': len(condition_ids),
        'human_reviewed_passages': len(passage_ids),
        'gates': {
            'twelve_documents': len(sources) >= 12,
            'twenty_human_reviewed_conditions': len(condition_ids) >= 20,
            'forty_human_reviewed_passages': len(passage_ids) >= 40
        },
        'notice': 'Engineering readiness and scientific validation are separate. Review-count targets track validation work and do not block engineering. Recorded reviewer identities do not establish domain qualifications.'
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path.cwd())
    args = p.parse_args()
    print(json.dumps(audit(args.root), indent=2))


if __name__ == '__main__':
    main()
