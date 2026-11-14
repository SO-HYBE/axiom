"""Test reviewer decisions using temporary repositories and synthetic evidence only."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from axiom.review import fingerprint, record_decision, review_read_lock, review_state
from axiom.review_queue import build_queue


def synthetic_chunk(chunk_id, text):
    return {
        "chunk_id": chunk_id, "source_id": "fixture-source", "experiment": "synthetic experiment",
        "title": "Synthetic test evidence", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "locator": "Fixture page 1", "url": "https://example.invalid/synthetic",
        "source_kind": "synthetic_fixture", "evidence_tier": 2, "conditions": {},
    }


def write_rows(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


class ReviewDecisionTests(unittest.TestCase):
    def test_read_lock_does_not_create_a_lock_file_for_immutable_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with review_read_lock(directory):
                self.assertTrue(directory.is_dir())
            self.assertFalse((directory / '.write.lock').exists())

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=os.environ.get("AXIOM_TEST_TMPDIR"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "data/processed").mkdir(parents=True)
        self.chunks = [
            synthetic_chunk("fixture-queued", "Synthetic apparatus uses fixture plastic."),
            synthetic_chunk("fixture-unqueued", "Synthetic passage outside the queue."),
        ]
        self.records = [{
            "record_id": "fixture-condition", "source_id": "fixture-source", "chunk_id": "fixture-queued",
            "quote": "fixture plastic", "field": "fuel", "value": "fixture plastic", "unit": None,
            "scope": "setup", "evidence_status": "reported", "review_status": "ai_draft", "reviewer": None,
        }]
        self.queue = build_queue(self.chunks, self.records, limit=1)
        self.save_inputs()

    def save_inputs(self):
        write_rows(self.root / "data/processed/chunks.jsonl", self.chunks)
        write_rows(self.root / "data/conditions.jsonl", self.records)
        write_rows(self.root / "data/review_queue.jsonl", self.queue)

    def state(self):
        return review_state(self.root, self.chunks, self.records, self.queue)

    def decide(self, kind, item_id, decision="accept", reviewer="synthetic-reviewer"):
        return record_decision(self.root, kind, item_id, decision, reviewer, "Synthetic test fixture decision only.")

    def test_fingerprint_stable_across_key_order_sensitive_to_edited_content(self):
        record = self.records[0]
        digest = fingerprint(record)
        self.assertRegex(digest, r"^[a-fA-F0-9]{64}$")
        self.assertEqual(digest, fingerprint(dict(reversed(list(record.items())))))
        self.assertNotEqual(digest, fingerprint({**record, "scope": "experiment_range"}))

    def test_empty_state_then_independent_passage_and_condition_decisions(self):
        self.assertEqual(self.state(), {})
        self.decide("passage", "fixture-queued")
        self.decide("condition", "fixture-condition", "revise")
        state = self.state()
        self.assertEqual(set(state), {("passage", "fixture-queued"), ("condition", "fixture-condition")})
        self.assertEqual(state["passage", "fixture-queued"]["decision"], "accept")
        self.assertEqual(state["condition", "fixture-condition"]["decision"], "revise")
        stored = json.loads((self.root / "data/conditions.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(stored["review_status"], "ai_draft")
        self.assertIsNone(stored["reviewer"])

    def test_latest_current_decision_replaces_previous_decision_for_same_item(self):
        self.decide("condition", "fixture-condition")
        self.decide("condition", "fixture-condition", "revise", reviewer="synthetic-second-reviewer")
        event = self.state()["condition", "fixture-condition"]
        self.assertEqual(event["decision"], "revise")
        self.assertEqual(event["reviewer"], "synthetic-second-reviewer")

    def test_changed_condition_excludes_old_decision(self):
        self.decide("condition", "fixture-condition")
        self.records[0] = {**self.records[0], "scope": "individual_test"}
        self.assertNotIn(("condition", "fixture-condition"), self.state())
        self.save_inputs()
        self.decide("condition", "fixture-condition", "revise")
        self.assertEqual(self.state()["condition", "fixture-condition"]["decision"], "revise")

    def test_changed_passage_excludes_old_decision(self):
        self.decide("passage", "fixture-queued")
        self.chunks[0] = synthetic_chunk("fixture-queued", "Revised synthetic text contains fixture plastic.")
        self.queue = build_queue(self.chunks, self.records, limit=1)
        self.assertNotIn(("passage", "fixture-queued"), self.state())

    def test_removed_queue_item_excludes_old_passage_decision(self):
        self.decide("passage", "fixture-queued")
        self.queue = []
        self.assertNotIn(("passage", "fixture-queued"), self.state())

    def test_unqueued_passage_and_unknown_condition_rejected_without_creating_decision(self):
        for kind, item_id in (("passage", "fixture-unqueued"), ("condition", "fixture-missing")):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.decide(kind, item_id)
        self.assertEqual(self.state(), {})

    def test_provenance_invalid_condition_cannot_be_accepted(self):
        self.records[0] = {**self.records[0], "quote": "invented evidence"}
        self.save_inputs()
        with self.assertRaises(ValueError):
            self.decide("condition", "fixture-condition")
        self.assertEqual(self.state(), {})

    def test_invalid_decision_kind_or_empty_reviewer_do_not_change_existing_state(self):
        self.decide("passage", "fixture-queued")
        prior_state = self.state()
        for kind, decision, reviewer in (("passage", "unknown", "synthetic-reviewer"),
                                         ("unknown", "accept", "synthetic-reviewer"),
                                         ("passage", "accept", " ")):
            with self.subTest(kind=kind, decision=decision, reviewer=reviewer), self.assertRaises(ValueError):
                self.decide(kind, "fixture-queued", decision, reviewer)
        self.assertEqual(self.state(), prior_state)


    def test_same_wall_clock_tick_uses_creation_order_instead_of_random_id(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from unittest.mock import patch
        fixed=datetime(2026,11,4,tzinfo=timezone.utc)
        with patch('axiom.review.datetime') as clock, patch('axiom.review.uuid4',side_effect=[SimpleNamespace(hex='b'*32),SimpleNamespace(hex='a'*32)]):
            clock.now.return_value=fixed
            self.decide('condition','fixture-condition','accept')
            self.decide('condition','fixture-condition','revise')
        self.assertEqual(self.state()['condition','fixture-condition']['decision'],'revise')

    def test_concurrent_review_writers_get_distinct_ordered_sequences(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            events=list(pool.map(lambda i:self.decide('condition','fixture-condition','accept' if i%2 else 'revise'),range(8)))
        self.assertEqual(sorted(e['sequence'] for e in events),list(range(1,9)))
        last=max(events,key=lambda e:e['sequence'])
        self.assertEqual(self.state()['condition','fixture-condition']['id'],last['id'])


if __name__ == "__main__":
    unittest.main()
