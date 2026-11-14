"""Build a deterministic, unreviewed passage queue; never generate approvals."""
import argparse
import json
from pathlib import Path
from .research import load_chunks


def build_queue(chunks, records, limit=40):
    by_id = {c['chunk_id']: c for c in chunks}
    selected = []
    def add(cid):
        if cid in by_id and cid not in selected and len(selected) < limit:
            selected.append(cid)
    for record in records:
        add(record['chunk_id'])
    # Round-robin across sources to keep the review queue broader than the seed annotations.
    buckets = {}
    for c in chunks:
        buckets.setdefault(c['source_id'], []).append(c)
    for values in buckets.values():
        values.sort(key=lambda c: (-sum(w in c['text'].lower() for w in ('oxygen','pressure','flow','fuel','microgravity','results')), c['chunk_id']))
    while len(selected) < min(limit, len(by_id)):
        before = len(selected)
        for source in sorted(buckets):
            while buckets[source] and buckets[source][0]['chunk_id'] in selected:
                buckets[source].pop(0)
            if buckets[source]:
                add(buckets[source].pop(0)['chunk_id'])
        if len(selected) == before:
            break
    return [{'chunk_id':cid, 'source_id':by_id[cid]['source_id'], 'locator':by_id[cid]['locator'],
             'url':by_id[cid]['url'], 'text_sha256':by_id[cid]['sha256'],
             'condition_record_ids':[r['record_id'] for r in records if r['chunk_id']==cid],
             'review_status':'pending_human_review','reviewer':None,
             'checks':['original_page','extraction_quality','scientific_scope','units_and_ranges','proposal_vs_observation','limitations']} for cid in selected]


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path.cwd());a=p.parse_args()
    records=[json.loads(x) for x in (a.root/'data/conditions.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
    queue=build_queue(load_chunks(a.root),records)
    (a.root/'data/review_queue.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in queue),encoding='utf-8')
    print(json.dumps({'queued_passages':len(queue),'human_reviews_performed':0}))

if __name__=='__main__':main()
