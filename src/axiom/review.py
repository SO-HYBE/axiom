"""Inspect queued evidence and record explicit human decisions for Phase 1."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from .conditions import validate_records
from .research import load_chunks


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8-sig').splitlines() if line.strip()] if path.is_file() else []


def fingerprint(record):
    encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def targets(chunks, records, queue):
    corpus = {chunk['chunk_id']: chunk for chunk in chunks}
    result = {}
    for entry in queue:
        chunk = corpus.get(entry.get('chunk_id'))
        if chunk and chunk['sha256'] == entry.get('text_sha256') and chunk['source_id'] == entry.get('source_id'):
            result['passage', chunk['chunk_id']] = chunk
    valid = set(validate_records(records, chunks)['valid_record_ids'])
    for record in records:
        if isinstance(record, dict) and isinstance(record.get('record_id'), str) and record['record_id'] in valid:
            result['condition', record['record_id']] = record
    return result


@contextmanager
def review_write_lock(directory):
    # An OS lock is released even if the writer process exits unexpectedly.
    with (directory / '.write.lock').open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        deadline = time.monotonic() + 3
        while True:
            try:
                lock.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError('Another review write is in progress. Retry shortly.')
                time.sleep(0.02)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def review_order(event):
    sequence = event.get('sequence', 0)
    if type(sequence) is not int or sequence < 0:
        raise ValueError('Invalid review sequence')
    return sequence, event['time'], event['id']


def review_state(root, chunks, records, queue):
    current = targets(chunks, records, queue)
    state = {}
    for path in sorted((root / 'data/reviews').glob('*.json')):
        event = json.loads(path.read_text(encoding='utf-8'))
        key = (event['kind'], event['item_id'])
        if key not in current or fingerprint(current[key]) != event['fingerprint']:
            continue
        if event['decision'] not in ('accept', 'revise') or not event['reviewer'].strip() or not event['note'].strip():
            raise ValueError('Invalid review entry: ' + path.name)
        if key not in state or review_order(event) > review_order(state[key]):
            state[key] = event
    return state


def inputs(root):
    return load_chunks(root), rows(root/'data/conditions.jsonl'), rows(root/'data/review_queue.jsonl')


def record_decision(root, kind, item_id, decision, reviewer, note):
    if decision not in ('accept','revise') or not reviewer.strip() or not note.strip():
        raise ValueError('A decision, reviewer name and review note are required')
    item = targets(*inputs(root)).get((kind,item_id))
    if item is None:
        raise ValueError('Item is absent, stale, or failed provenance validation')
    event = dict(id=uuid4().hex, time=datetime.now(timezone.utc).isoformat(), kind=kind, item_id=item_id,
                 fingerprint=fingerprint(item), decision=decision, reviewer=reviewer.strip(), note=note.strip())
    directory = root/'data/reviews'; directory.mkdir(parents=True, exist_ok=True)
    with review_write_lock(directory):
        existing = [json.loads(path.read_text(encoding='utf-8')) for path in directory.glob('*.json')]
        event['sequence'] = max((review_order(row)[0] for row in existing), default=0) + 1
        temp = directory/(event['id']+'.tmp')
        try:
            temp.write_text(json.dumps(event, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
            os.replace(temp, temp.with_suffix('.json'))
        finally:
            temp.unlink(missing_ok=True)
    return event


def inspection(key, current, chunks, records, state):
    item = current[key]
    chunk = next(c for c in chunks if c['chunk_id'] == item['chunk_id'])
    return {'kind': key[0], 'item_id': key[1], 'source': chunk['url'],
            'locator': chunk['locator'], 'passage': chunk['text'],
            'conditions': [r for r in records if r['chunk_id'] == chunk['chunk_id']],
            'decision': state.get(key)}


def session(root, reviewer):
    chunks, records, queue = inputs(root)
    current = targets(chunks, records, queue)
    state = review_state(root, chunks, records, queue)
    for key in current:
        if key in state:
            continue
        print(json.dumps(inspection(key, current, chunks, records, state), indent=2, ensure_ascii=True))
        while True:
            decision = input('After checking the original page: accept / revise / skip / quit? ').strip().lower()
            if decision in ('accept', 'revise', 'skip', 'quit'):
                break
        if decision == 'quit':
            return
        if decision == 'skip':
            continue
        note = input('Record the reason for your decision: ').strip()
        if not note:
            print('No decision saved. A review note is required.')
            continue
        record_decision(root, *key, decision, reviewer, note)
        print('Decision saved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest='command', required=True)
    show = sub.add_parser('show')
    show.add_argument('item_id', nargs='?')
    guided = sub.add_parser('session')
    guided.add_argument('--reviewer', required=True)
    save = sub.add_parser('record')
    save.add_argument('kind', choices=['passage', 'condition'])
    save.add_argument('item_id')
    save.add_argument('decision', choices=['accept', 'revise'])
    save.add_argument('--reviewer', required=True)
    save.add_argument('--note', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'session':
            session(args.root, args.reviewer)
            return
        if args.command == 'record':
            output = record_decision(args.root, args.kind, args.item_id, args.decision,
                                     args.reviewer, args.note)
        else:
            chunks, records, queue = inputs(args.root)
            current = targets(chunks, records, queue)
            state = review_state(args.root, chunks, records, queue)
            if args.item_id:
                key = next((k for k in current if k[1] == args.item_id), None)
                if key is None:
                    parser.error('Unknown or invalid review item')
            else:
                key = next((k for k in current if k not in state), None)
            output = inspection(key, current, chunks, records, state) if key else {'message': 'All available items have a recorded decision.'}
        print(json.dumps(output, indent=2, ensure_ascii=True))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'AXIOM review: {exc}\n')
    except (EOFError, KeyboardInterrupt):
        parser.exit(0, 'Review session ended. Saved decisions are retained.\n')

if __name__ == '__main__':
    main()
