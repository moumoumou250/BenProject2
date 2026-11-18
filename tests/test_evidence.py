"""R-03 evidence gate + R-07 perf smoke."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import ben
from ben.core.evidence import merge_evidence_into_data, validate_evidence_for_intent


class EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ben.Store(Path(self.tmp.name) / ".ben")
        self.store.init("ev", "prove evidence")
        self.seed = self.store.add_fact("seed", "test", None)
        self.intent = self.store.add_intent([self.seed["id"]], "work", "test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_done_without_evidence_raises(self):
        with self.assertRaisesRegex(ben.FGError, "evidence"):
            self.store.conclude_with_new_fact(
                self.intent["id"], "x", "agent",
            )

    def test_force_sets_forced_flag(self):
        fact, _ = self.store.conclude_with_new_fact(
            self.intent["id"], "forced result", "agent", force=True,
        )
        self.assertEqual((fact.get("data") or {}).get("forced"), "true")

    def test_evidence_intent_mismatch(self):
        ev = {"intent": "i999", "sha": "abc", "exit": 0, "checks": [{"name": "a", "exit": 0}]}
        with self.assertRaisesRegex(ben.FGError, "does not match"):
            validate_evidence_for_intent(ev, intent_id="i001", expected_sha="abc")

    def test_evidence_sha_mismatch(self):
        ev = {
            "intent": self.intent["id"],
            "sha": "oldsha",
            "exit": 0,
            "checks": [{"name": "a", "exit": 0}],
        }
        report = Path(self.tmp.name) / "report.json"
        report.write_text(json.dumps(ev), encoding="utf-8")
        with mock.patch("ben.core.evidence.git_head_sha", return_value="newsha"):
            with self.assertRaisesRegex(ben.FGError, "does not match HEAD"):
                self.store.conclude_with_new_fact(
                    self.intent["id"], "x", "agent", evidence=str(report),
                )

    def test_valid_evidence_concludes(self):
        ev = {
            "intent": self.intent["id"],
            "sha": "deadbeef",
            "exit": 0,
            "checks": [{"name": "arch", "exit": 0}, {"name": "pytest", "exit": 0}],
            "path": "report.json",
        }
        report = Path(self.tmp.name) / "report.json"
        report.write_text(json.dumps(ev), encoding="utf-8")
        with mock.patch("ben.core.evidence.git_head_sha", return_value="deadbeef"):
            with mock.patch("ben.core.roles.check_role_paths"):
                fact, _ = self.store.conclude_with_new_fact(
                    self.intent["id"], "ok", "agent", evidence=str(report),
                )
        self.assertEqual((fact.get("data") or {}).get("sha"), "deadbeef")

    def test_cmd_done_force_leaves_hint(self):
        args = type("Args", (), {
            "store": str(self.store.root),
            "id": self.intent["id"],
            "fact": "done via force",
            "title": None,
            "kind": None,
            "data": None,
            "doc": None,
            "doc_file": None,
            "worker": "agent",
            "force": True,
            "evidence": None,
        })()
        self.assertEqual(ben.cmd_done(args), 0)
        hints = self.store.list_hints()
        self.assertTrue(any("forced conclude" in h.get("content", "") for h in hints))


class StorePerfTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("BEN_PERF") == "1", "set BEN_PERF=1")
    def test_add_intents_under_budget(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = ben.Store(Path(tmp.name) / ".ben")
        store.init("perf", "speed")
        facts = [store.add_fact(f"f{i}", "t", None) for i in range(200)]
        ids = [f["id"] for f in facts]
        t0 = time.perf_counter()
        for i in range(100):
            store.add_intent([ids[i % 200]], f"intent {i}", "perf")
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 1.0, f"100 intents took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
