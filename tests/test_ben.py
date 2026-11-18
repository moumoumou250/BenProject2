import contextlib
import io
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ben  # noqa: E402

SETTINGS_PATH = ROOT / "scripts" / "hooks" / "_settings_patch.py"
_spec = importlib.util.spec_from_file_location("settings_patch_for_tests", SETTINGS_PATH)
settings_patch = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(settings_patch)


class GraphIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ben.Store(Path(self.tmp.name) / ".ben")
        self.store.init("test", "ship it")

    def tearDown(self):
        self.tmp.cleanup()

    def test_corrupt_node_is_skipped_and_reported_by_validate(self):
        (self.store.facts_dir / "f001.json").write_text('{"id":"f001"}\n', encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rendered = ben.render_graph_text(self.store)
        self.assertIn("goal: ship it", rendered)
        self.assertIn("missing string 'description'", stderr.getvalue())
        errors = ben.validate_graph(self.store)
        self.assertTrue(any("f001.json" in error for error in errors))

    def test_init_refuses_non_empty_directory(self):
        root = Path(self.tmp.name) / "new-store"
        root.mkdir()
        (root / "unrelated.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ben.FGError, "non-empty directory"):
            ben.Store(root).init("", "goal")
        self.assertTrue((root / "unrelated.txt").exists())

    def test_validate_detects_goal_metadata_drift(self):
        goal = self.store.facts_dir / "goal.json"
        data = json.loads(goal.read_text(encoding="utf-8"))
        data["description"] = "different goal"
        goal.write_text(json.dumps(data), encoding="utf-8")
        errors = ben.validate_graph(self.store)
        self.assertIn("goal fact description does not match project goal", errors)

    def test_validate_detects_intent_state_mismatch(self):
        seed = self.store.add_fact("seed", "test", None)
        intent = self.store.add_intent([seed["id"]], "work", "test")
        path = self.store.intents_dir / f"{intent['id']}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "done"
        path.write_text(json.dumps(data), encoding="utf-8")
        errors = ben.validate_graph(self.store)
        self.assertTrue(any("completed status requires a target" in error for error in errors))

    def test_confirmation_is_enforced_at_write_boundary(self):
        fact = self.store.add_fact("starting point", "test", None)
        intent = self.store.add_intent(
            [fact["id"]], "delete data", "test", requires_confirmation=True
        )
        with self.assertRaisesRegex(ben.FGError, "requires confirmation"):
            self.store.conclude_with_new_fact(intent["id"], "must not run", "test", force=True)
        self.store.confirm_intent(intent["id"])
        self.store.claim_intent(intent["id"], "owner")
        with self.assertRaisesRegex(ben.FGError, "claimed by owner"):
            self.store.conclude_with_new_fact(intent["id"], "wrong worker", "other", force=True)
        result, concluded = self.store.conclude_with_new_fact(
            intent["id"], "approval was recorded", "owner", force=True
        )
        self.assertEqual(concluded["to"], result["id"])

    def test_lookup_ids_cannot_escape_store(self):
        with self.assertRaisesRegex(ben.FGError, "invalid fact id"):
            self.store.get_fact("../../outside")

    def test_stale_counter_never_overwrites_existing_node(self):
        first = self.store.add_fact("first", "test", None)
        project = self.store.load_project()
        project["counters"]["fact"] = 0
        self.store.save_project(project)
        second = self.store.add_fact("second", "test", None)
        self.assertEqual(first["id"], "f001")
        self.assertEqual(second["id"], "f002")
        self.assertEqual(self.store.get_fact("f001")["description"], "first")

    def test_fact_from_intent_closes_the_intent_atomically(self):
        seed = self.store.add_fact("seed", "test", None)
        intent = self.store.add_intent([seed["id"]], "observe", "test")
        fact = self.store.add_fact("observed", "test", intent["id"])
        self.assertEqual(self.store.get_intent(intent["id"])["to"], fact["id"])
        self.assertEqual(ben.validate_graph(self.store), [])

    def test_linking_existing_fact_sets_its_source_edge(self):
        seed = self.store.add_fact("seed", "test", None)
        result = self.store.add_fact("already observed", "test", None)
        intent = self.store.add_intent([seed["id"]], "link result", "test")
        self.store.conclude_intent(intent["id"], result["id"], "test")
        self.assertEqual(self.store.get_fact(result["id"])["source_intent"], intent["id"])
        self.assertEqual(ben.validate_graph(self.store), [])

    def test_pick_claim_skips_another_workers_lease(self):
        seed = self.store.add_fact("seed", "test", None)
        first = self.store.add_intent([seed["id"]], "first", "test")
        second = self.store.add_intent([seed["id"]], "second", "test")
        self.store.claim_intent(first["id"], "other-worker")
        args = type("Args", (), {
            "store": str(self.store.root), "claim": True,
            "worker": "my-worker", "any": False,
        })()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ben.cmd_pick(args)
        self.assertEqual(output.getvalue().strip(), second["id"])

    def test_static_view_escapes_script_terminators(self):
        self.store.add_fact("</script><script>alert(1)</script>", "test", None)
        html = ben._render_static_html(self.store)
        self.assertNotIn("</script><script>", html)
        self.assertIn(r"\u003c/script\u003e", html)

    def test_prompt_substitution_does_not_rewrite_inserted_braces(self):
        self.store.add_fact("literal {goal} marker", "test", None)
        prompt = ben.render_prompt(self.store, "{graph_yaml}\nGOAL={goal}")
        self.assertIn("literal {goal} marker", prompt)
        self.assertTrue(prompt.endswith("GOAL=ship it"))

    def test_brainstorm_template_token_does_not_rewrite_graph_text(self):
        self.store.add_fact("literal {max_options} marker", "test", None)
        args = type("Args", (), {
            "max_options": 2, "dry_run": True,
        })()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            ben._run_brainstorm(
                self.store, ROOT / "ben" / "agents" / "prompts", "sonnet", 10, False, ROOT, args
            )
        self.assertIn("literal {max_options} marker", output.getvalue())

    def test_verify_payload_requires_actionable_issues_on_failure(self):
        with self.assertRaisesRegex(ben.FGError, "explain"):
            ben._parse_verify_payload({"verified": False, "issues": ""})
        with self.assertRaisesRegex(ben.FGError, "leave 'issues' empty"):
            ben._parse_verify_payload({"verified": True, "issues": "warning"})

    def test_dispatch_verify_returns_failure_status(self):
        seed = self.store.add_fact("seed", "test", None)
        intent = self.store.add_intent([seed["id"]], "check", "test")
        result, _ = self.store.conclude_with_new_fact(intent["id"], "result", "test", force=True)
        args = type("Args", (), {
            "intent": intent["id"], "dry_run": False,
        })()
        with mock.patch(
            "ben.agents.dispatch.run_claude",
            return_value={"result": '{"accepted": true, "data": {"verified": false, "issues": "mismatch"}}'},
        ):
            rc = ben._dispatch_verify(
                self.store, ROOT / "ben" / "agents" / "prompts", "sonnet", 10, False, ROOT, args
            )
        self.assertEqual(rc, 1)

    def test_completed_graph_validates_and_duplicate_completion_is_rejected(self):
        fact = self.store.add_fact("evidence", "test", None)
        self.store.complete_project([fact["id"]], "finish", "test")
        self.assertEqual(self.store.load_project()["status"], "completed")
        self.assertEqual(ben.validate_graph(self.store), [])
        with self.assertRaisesRegex(ben.FGError, "already completed"):
            self.store.complete_project([fact["id"]], "finish again", "test")

    def test_brainstorm_batches_are_unique(self):
        seed = self.store.add_fact("seed", "test", None)
        payload = {
            "accepted": True,
            "data": {
                "options": [
                    {"from": [seed["id"]], "title": "one", "description": "first"}
                ]
            },
        }
        ben._apply_brainstorm(self.store, payload)
        ben._apply_brainstorm(self.store, payload)
        docs = [i["doc"] for i in self.store.list_intents()]
        self.assertEqual(len(docs), 2)
        tags = [line for doc in docs for line in doc.splitlines() if line.startswith("[brainstorm batch:")]
        self.assertEqual(len(set(tags)), 2)

    def test_brainstorm_pick_preserves_abandoned_edges(self):
        seed = self.store.add_fact("seed", "test", None)
        payload = {
            "accepted": True,
            "data": {"options": [
                {"from": [seed["id"]], "title": "one", "description": "first"},
                {"from": [seed["id"]], "title": "two", "description": "second"},
            ]},
        }
        ben._apply_brainstorm(self.store, payload)
        picked = self.store.list_intents()[0]
        args = type("Args", (), {"store": str(self.store.root), "id": picked["id"], "purge": False})()
        ben.cmd_brainstorm_pick(args)
        intents = self.store.list_intents()
        self.assertEqual(sum(i["to"] is None for i in intents), 1)
        self.assertEqual(sum(i["to"] is not None for i in intents), 1)
        self.assertEqual(ben.validate_graph(self.store), [])


class SettingsPatchTests(unittest.TestCase):
    def test_settings_patch_is_atomic_and_preserves_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"hooks": {"SessionStart": [{"matcher": "x", "hooks": [
                    {"type": "command", "command": "echo keep"
                    }
                ]}]}}),
                encoding="utf-8",
            )
            changed, _ = settings_patch.add(path, "/tmp/ben-hook.py")
            self.assertTrue(changed)
            data = json.loads(path.read_text(encoding="utf-8"))
            commands = [
                h["command"]
                for groups in data["hooks"].values()
                for group in groups
                for h in group.get("hooks", [])
            ]
            self.assertIn("echo keep", commands)
            self.assertEqual(sum("ben-hook.py" in command for command in commands), 2)
            settings_patch.remove(path, "/tmp/ben-hook.py")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["SessionStart"][0]["hooks"][0]["command"], "echo keep")

    def test_settings_patch_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                settings_patch.add(path, "/tmp/ben-hook.py")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                settings_patch.remove(path, "/tmp/ben-hook.py")

    def test_settings_validation_catches_malformed_event_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"hooks": {"SessionStart": {}}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hooks.SessionStart"):
                settings_patch.validate(path)


class PeerConfigTests(unittest.TestCase):
    def test_malformed_peer_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ben.Store(Path(tmp) / ".ben")
            store.init("", "peers")
            (store.root / ben.PEERS_FILE).write_text(
                json.dumps({"version": 1, "channel": "x", "peers": {"bad name": {"target": "x"}}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ben.FGError, "invalid peer name"):
                ben._load_peers(store)

    def test_setup_preflights_invalid_settings_before_creating_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".claude").mkdir()
            (project / ".claude" / "settings.json").write_text("[]", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(project)
                args = type("Args", (), {
                    "store": ".ben", "goal": "should not initialize",
                    "origin": "", "agents": False, "force": False,
                })()
                with self.assertRaisesRegex(ben.FGError, "JSON object"):
                    ben.cmd_setup(args)
            finally:
                os.chdir(old_cwd)
            self.assertFalse((project / ".ben" / "project.json").exists())


if __name__ == "__main__":
    unittest.main()


class TypedFactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ben.Store(Path(self.tmp.name) / ".ben")
        self.store.init("test", "capture the flag")

    def tearDown(self):
        self.tmp.cleanup()

    def test_typed_fact_roundtrip_and_render(self):
        fact = self.store.add_fact(
            "nginx 1.18 at 10.0.2.15:80", "user",
            kind="service", data={"host": "10.0.2.15", "port": 80},
        )
        self.assertEqual(fact["kind"], "service")
        self.assertEqual(fact["data"]["port"], "80")
        text = ben.render_graph_text(self.store)
        self.assertIn("<service>", text)
        self.assertIn("port=80", text)
        yaml = ben._to_yaml_like(ben.build_graph_view(self.store))
        self.assertIn("<service>", yaml)
        # prompt rendering scrubs braces so flag{...} cannot eat placeholders
        self.assertIn("port=80", yaml)

    def test_unknown_kind_and_bad_data_rejected(self):
        with self.assertRaises(ben.FGError):
            self.store.add_fact("x", "user", kind="exploit")
        with self.assertRaises(ben.FGError):
            self.store.add_fact("x", "user", kind="cred", data={"bad key!": "1"})

    def test_validate_rejects_invalid_kind_on_disk(self):
        fact = self.store.add_fact("x", "user", kind="cred")
        p = self.store.facts_dir / f"{fact['id']}.json"
        node = json.loads(p.read_text(encoding="utf-8"))
        node["kind"] = "exploit"
        p.write_text(json.dumps(node), encoding="utf-8")
        errors = ben.validate_graph(self.store)
        self.assertTrue(any("kind" in e for e in errors))

    def test_explore_payload_carries_kind_and_data(self):
        payload = {"accepted": True, "data": {
            "description": "RCE confirmed",
            "kind": "vuln",
            "data": {"cve": "CVE-2021-41773"},
        }}
        title, desc, doc, kind, data = ben._parse_explore_payload(payload)
        self.assertEqual(kind, "vuln")
        self.assertEqual(data, {"cve": "CVE-2021-41773"})


class FlagLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ben.Store(Path(self.tmp.name) / ".ben")
        self.store.init("test", "capture the flag")

    def tearDown(self):
        self.tmp.cleanup()

    def test_flag_record_and_dedupe(self):
        fact = self.store.add_fact(
            "flag captured: flag{a}", "agent",
            kind="flag", data={"value": "flag{a}", "challenge": "c01", "status": "recorded"},
        )
        dup = ben._find_flag_fact(self.store, "flag{a}")
        self.assertEqual(dup["id"], fact["id"])
        self.assertIsNone(ben._find_flag_fact(self.store, "flag{b}"))

    def test_flag_status_lifecycle_and_type_guard(self):
        fact = self.store.add_fact(
            "flag captured: flag{a}", "agent",
            kind="flag", data={"value": "flag{a}", "status": "recorded"},
        )
        updated = self.store.update_flag_fact(fact["id"], "submitted", '{"ok":true}')
        self.assertEqual(updated["data"]["status"], "submitted")
        self.assertEqual(updated["data"]["result"], '{"ok":true}')
        plain = self.store.add_fact("just text", "agent")
        with self.assertRaises(ben.FGError):
            self.store.update_flag_fact(plain["id"], "submitted", None)
        with self.assertRaises(ben.FGError):
            self.store.update_flag_fact(fact["id"], "hacked-status", None)

    def test_status_shows_flag_ledger(self):
        self.store.add_fact(
            "flag captured: flag{z}", "agent",
            kind="flag", data={"value": "flag{z}", "challenge": "c09", "status": "submitted"},
        )
        text = ben.render_status(self.store)
        self.assertIn("flag(s)", text)
        self.assertIn("status=submitted", text)
        self.assertIn("challenge=c09", text)


class DeadlineTests(unittest.TestCase):
    def test_minutes_and_iso_and_conflict(self):
        import time as _t
        a = type("A", (), {"deadline": None, "minutes": 5})()
        d = ben.deadline_from_args(a)
        self.assertGreater(d, _t.time())
        b = type("B", (), {"deadline": "2026-10-17T13:00:00", "minutes": None})()
        self.assertIsNotNone(ben.deadline_from_args(b))
        c = type("C", (), {"deadline": "2026-10-17T13:00:00+08:00", "minutes": 5})()
        with self.assertRaises(ben.FGError):
            ben.deadline_from_args(c)
        bad = type("D", (), {"deadline": "not-a-date", "minutes": None})()
        with self.assertRaises(ben.FGError):
            ben.deadline_from_args(bad)
        self.assertEqual(ben.deadline_from_args(type("E", (), {"deadline": None, "minutes": None})()), None)

    def test_format_time_budget(self):
        self.assertEqual(ben.format_time_budget(None), "")
        self.assertIn("TIME IS UP",
                      ben.format_time_budget(0))  # 0 -> epoch 1970, always past
        self.assertIn("remaining", ben.format_time_budget(_t.time() + 600))


import time as _t  # noqa: E402  (DeadlineTests)


class ArenaClientTests(unittest.TestCase):
    """Verify the exact TSecBench Challenges API contract (header, paths,
    params/body, error envelope)."""

    def _arena(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_arena_test", ROOT / "ben" / "arena.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_client_contract_against_local_server(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        arena = self._arena()
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                seen.append((self.command, self.path, self.headers.get("BENCHMARK_TOKEN"), body))

            def do_GET(self):
                self._record()
                if self.path.startswith("/openapi/v1/challenges/hint"):
                    return self._reply({"unique_code": "c1", "hint": "h"})
                return self._reply([{"unique_code": "c1", "difficulty": "easy", "level": "1",
                                     "total_score": 100, "flag_count": 2, "correct_flag_count": 0,
                                     "is_completed": False, "description": "d",
                                     "container_status": "stopped", "container_addr": []}])

            def do_POST(self):
                self._record()
                if self.path.startswith("/openapi/v1/challenges/submit"):
                    return self._reply({"correct": True, "awarded": 50, "cumulative_score": 50,
                                        "correct_flag_count": 1, "total_flag_count": 2,
                                        "matched_flag_index": 0})
                if self.path.startswith("/openapi/v1/challenges/close"):
                    return self._reply({"unique_code": "c1", "closed": True})
                return self._reply({"unique_code": "c1", "container_addr": ["10.0.0.9:80"]})

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = arena.ArenaClient(f"http://127.0.0.1:{server.server_address[1]}", "tok-x")
            chs = client.list_challenges()
            self.assertEqual(chs[0]["unique_code"], "c1")
            started = client.start_challenge("c1")
            self.assertEqual(started["container_addr"], ["10.0.0.9:80"])
            self.assertEqual(client.get_hint("c1")["hint"], "h")
            res = client.submit_flag("c1", "flag{a}")
            self.assertTrue(res["correct"])
            self.assertTrue(client.close_challenge("c1")["closed"])
        finally:
            server.shutdown()

        # every call carried the BENCHMARK_TOKEN header
        self.assertTrue(all(entry[2] == "tok-x" for entry in seen), seen)
        # exact paths + param/body shapes
        submit = [e for e in seen if e[1] == "/openapi/v1/challenges/submit"][0]
        self.assertEqual(submit[3], {"unique_code": "c1", "flag": "flag{a}"})
        start = [e for e in seen if "start" in e[1]][0]
        self.assertIn("unique_code=c1", start[1])
        hint = [e for e in seen if "hint" in e[1]][0]
        self.assertIn("unique_code=c1", hint[1])
        close = [e for e in seen if "close" in e[1]][0]
        self.assertIn("unique_code=c1", close[1])

    def test_error_envelope_surfaces_code(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        arena = self._arena()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.dumps({"code": "invalid_state", "message": "max active", "detail": {}}).encode()
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = arena.ArenaClient(f"http://127.0.0.1:{server.server_address[1]}", "t")
            with self.assertRaises(arena.ArenaError) as ctx:
                client.start_challenge("c1")
            self.assertEqual(ctx.exception.code, "invalid_state")
            self.assertEqual(ctx.exception.status, 409)
        finally:
            server.shutdown()

    def test_config_resolution_env_and_file(self):
        arena = self._arena()
        with mock.patch.dict("os.environ", {"BENCHMARK_BASE_URL": "http://env-base",
                                            "BENCHMARK_TOKEN": "env-tok"}):
            c = arena.ArenaClient.load(None)
            self.assertEqual(c.base_url, "http://env-base")
            self.assertEqual(c.token, "env-tok")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "arena.json").write_text(json.dumps(
                {"base_url": "http://file-base", "token": "ENV:BENCHMARK_TOKEN"}), encoding="utf-8")
            with mock.patch.dict("os.environ", {"BENCHMARK_TOKEN": "env-tok"}):
                c = arena.ArenaClient.load(Path(tmp))
                self.assertEqual(c.base_url, "http://file-base")
                self.assertEqual(c.token, "env-tok")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(arena.ArenaError):
                arena.ArenaClient.load(None)
        with self.assertRaises(arena.ArenaError):
            arena.ArenaClient("http://x", "")

    def test_rejects_unsafe_unique_code(self):
        arena = self._arena()
        client = arena.ArenaClient("http://x", "t")
        with self.assertRaises(arena.ArenaError):
            client.start_challenge("../etc/passwd")


class ArenaErrorBridgeTests(unittest.TestCase):
    """Regression for the live 409 crash: the platform answered
    "max active challenge instances reached (3)" and the raw ArenaError
    escaped the `except FGError` guard in _bench_parallel, killing the
    whole bench. Modules loaded through ben._load_arena_module() must
    raise ArenaError catchable as FGError."""

    def test_loaded_arena_error_subclasses_fgerror(self):
        arena = ben._load_arena_module()
        self.assertTrue(issubclass(arena.ArenaError, ben.FGError))

    def test_409_max_active_caught_as_fgerror(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        arena = ben._load_arena_module()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.dumps({
                    "code": "invalid_state",
                    "message": "max active challenge instances reached (3), "
                               "please close an existing challenge before starting a new one",
                    "detail": {},
                }).encode()
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = arena.ArenaClient(
                f"http://127.0.0.1:{server.server_address[1]}", "t")
            with self.assertRaises(ben.FGError) as ctx:
                client.start_challenge("c1")
            self.assertIn("max active", str(ctx.exception).lower())
        finally:
            server.shutdown()


class CommanderTests(unittest.TestCase):
    def test_parse_command_payload(self):
        ok = {"accepted": True, "data": {"action": "work", "target": "c03", "minutes": 25, "note": "close"}}
        self.assertEqual(ben._parse_command_payload(ok), ("work", "c03", 25, "close"))
        stop = {"accepted": True, "data": {"action": "stop", "reason": "all done"}}
        self.assertEqual(ben._parse_command_payload(stop), ("stop", "", 0, "all done"))
        rej = {"accepted": False, "reason": "bad board"}
        self.assertEqual(ben._parse_command_payload(rej)[0], "reject")
        with self.assertRaises(ben.FGError):
            ben._parse_command_payload({"accepted": True, "data": {"action": "hack"}})
        with self.assertRaises(ben.FGError):
            ben._parse_command_payload({"accepted": True, "data": {"action": "work", "minutes": 10}})
        with self.assertRaises(ben.FGError):
            ben._parse_command_payload({"accepted": True, "data": {"action": "work", "target": "c1", "minutes": 0}})

    def test_board_summary_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("c01", "c02"):
                store = ben.Store(root / name / ".ben")
                store.init("t", f"flag {name}")
            ben.Store(root / "c01" / ".ben").add_fact(
                "flag captured: flag{a}", "agent",
                kind="flag", data={"value": "flag{a}", "challenge": "c01", "status": "submitted"})
            rows = ben._board_summary(root)
            self.assertEqual([r["name"] for r in rows], ["c01", "c02"])
            by_name = {r["name"]: r for r in rows}
            self.assertEqual(by_name["c01"]["flags_submitted"], 1)
            self.assertEqual(by_name["c02"]["flags_submitted"], 0)
            board = ben.render_board(rows)
            self.assertIn("c01", board)
            self.assertIn("flags(sub/rec)", board)


class FleetTests(unittest.TestCase):
    def test_fleet_pane_commands(self):
        cfg = {"session": "s", "root": "runs", "deadline": "2026-10-17T13:00:00",
               "panes": []}
        engine = ben._ben_engine_prefix()
        self.assertEqual(
            ben._fleet_pane_command(cfg, {"type": "command"}),
            f"{engine} command --root runs --deadline 2026-10-17T13:00:00")
        self.assertEqual(
            ben._fleet_pane_command(cfg, {"type": "auto:c02", "extra_args": "--verify"}),
            f"{engine} --store runs/c02/.ben auto --deadline 2026-10-17T13:00:00 --verify")
        self.assertEqual(
            ben._fleet_pane_command(cfg, {"type": "auto:c02"}, base_dir=Path("/w")),
            f"cd /w && {engine} --store runs/c02/.ben auto --deadline 2026-10-17T13:00:00")
        self.assertEqual(
            ben._fleet_pane_command({"root": "runs", "panes": []}, {"type": "shell", "command": "top"}),
            "top")
        with self.assertRaises(ben.FGError):
            ben._fleet_pane_command(cfg, {"type": "warp"})
        with self.assertRaises(ben.FGError):
            ben._fleet_pane_command(cfg, {"type": "shell"})

    def test_fleet_init_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                import os
                os.chdir(tmp)
                args = type("A", (), {"action": "init", "file": "fleet.json"})()
                self.assertEqual(ben.cmd_fleet(args), 0)
                cfg = ben._fleet_load(Path("fleet.json"))
                self.assertTrue(cfg["panes"])
                args2 = type("A", (), {"action": "init", "file": "fleet.json"})()
                with self.assertRaises(ben.FGError):
                    ben.cmd_fleet(args2)
            finally:
                os.chdir(old)


class HireFireTests(unittest.TestCase):
    def test_parse_command_payload_hire_fire(self):
        hire = {"accepted": True, "data": {"action": "hire", "target": "c07", "minutes": 30}}
        self.assertEqual(ben._parse_command_payload(hire), ("hire", "c07", 30, ""))
        fire = {"accepted": True, "data": {"action": "fire", "target": "c07", "note": "stuck"}}
        self.assertEqual(ben._parse_command_payload(fire), ("fire", "c07", 0, "stuck"))
        with self.assertRaises(ben.FGError):
            ben._parse_command_payload({"accepted": True, "data": {"action": "warp", "target": "c"}})
        with self.assertRaises(ben.FGError):
            ben._parse_command_payload({"accepted": True, "data": {"action": "hire", "minutes": 10}})
        with self.assertRaises(ben.FGError):
            ben._parse_command_payload({"accepted": True, "data": {"action": "hire", "target": "c", "minutes": -1}})

    def test_active_workers_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = ben.AgentRegistry(root / "runs")
            self.assertEqual(ben._active_workers(root, "runs"), set())
            # spawn a short-lived sleeper as w-c01
            self.assertTrue(reg.spawn(
                "w-c01", ["bash", "-lc", "sleep 30"], cwd=root,
                env={"BEN_WORKER": "w-c01"},
            ))
            self.assertEqual(ben._active_workers(root, "runs"), {"c01"})
            self.assertTrue(ben._fire_worker(root, "c01", fleet_root="runs"))
            self.assertEqual(ben._active_workers(root, "runs"), set())

    def test_board_render_worker_column(self):
        rows = [
            {"name": "c01", "status": "active", "flags_submitted": 1, "flags_recorded": 0,
             "kinds": "1 flag", "open_intents": 2, "last_activity": "t", "goal": "g", "worker": "yes"},
            {"name": "c02", "status": "active", "flags_submitted": 0, "flags_recorded": 0,
             "kinds": "-", "open_intents": 0, "last_activity": "t", "goal": "g", "worker": "-"},
        ]
        board = ben.render_board(rows)
        self.assertIn("worker", board)
        self.assertIn("worker=yes means", board)


import os  # noqa: E402  (KeyRotationTests)


class KeyRotationTests(unittest.TestCase):
    def test_quota_matcher(self):
        self.assertTrue(ben._is_quota_error("insufficient balance (quota exceeded)"))
        self.assertTrue(ben._is_quota_error("Error 401: Unauthorized"))
        self.assertTrue(ben._is_quota_error("账户欠费，请充值"))
        self.assertFalse(ben._is_quota_error("connection timed out"))
        self.assertFalse(ben._is_quota_error("claude exited 2: bad args"))

    def test_pool_load_and_rotate(self):
        pool_json = json.dumps([
            {"base_url": "http://a", "token": "t1", "model": "m1"},
            {"base_url": "http://b", "token": "t2", "model": "m2"},
        ])
        with mock.patch.dict("os.environ", {
            "BEN_KEY_POOL": pool_json, "ANTHROPIC_AUTH_TOKEN": "t1",
            "ANTHROPIC_BASE_URL": "http://a", "BEN_MODEL": "m1"}):
            self.assertTrue(ben._rotate_key())
            self.assertEqual(os.environ["ANTHROPIC_AUTH_TOKEN"], "t2")
            self.assertEqual(os.environ["ANTHROPIC_BASE_URL"], "http://b")
            self.assertEqual(os.environ["BEN_MODEL"], "m2")
        with mock.patch.dict("os.environ", {"BEN_KEY_POOL": "not json"}):
            self.assertEqual(ben._load_key_pool(), [])
        with mock.patch.dict("os.environ", {"BEN_KEY_POOL": ""}):
            self.assertFalse(ben._rotate_key())
        # single-entry pool: rotate returns True but keeps the key
        with mock.patch.dict("os.environ", {
            "BEN_KEY_POOL": json.dumps([{"base_url": "http://a", "token": "t1"}]),
            "ANTHROPIC_AUTH_TOKEN": "t1"}):
            self.assertTrue(ben._rotate_key())
            self.assertEqual(os.environ["ANTHROPIC_AUTH_TOKEN"], "t1")

    def test_pool_entry_zero_is_the_primary_sdk_key(self):
        pool_json = json.dumps([
            {"api_key": "p1", "base_url": "http://a", "model": "m1"},
            {"api_key": "p2", "base_url": "http://b", "model": "m2"},
        ])
        from ben.llm.llm import _sdk_credentials
        # pool-only: entry #0 seeds the active credentials
        with mock.patch.dict("os.environ", {"BEN_KEY_POOL": pool_json}, clear=True):
            api_key, api_base, model = _sdk_credentials()
            self.assertEqual((api_key, api_base, model), ("p1", "http://a", "m1"))
            self.assertEqual(os.environ["BEN_API_KEY"], "p1")
            # rotation advances from the seeded primary to entry #1
            self.assertTrue(ben._rotate_key(backend="sdk"))
            self.assertEqual(os.environ["BEN_API_KEY"], "p2")
            self.assertEqual(os.environ["BEN_API_BASE"], "http://b")
        # explicit env vars win over the seed
        with mock.patch.dict("os.environ", {
            "BEN_KEY_POOL": pool_json, "BEN_API_KEY": "explicit",
            "BEN_MODEL": "explicit-model"}, clear=True):
            api_key, api_base, model = _sdk_credentials()
            self.assertEqual(api_key, "explicit")
            self.assertEqual(model, "explicit-model")
            self.assertFalse(ben._seed_key_from_pool())


class HookExecutionTests(unittest.TestCase):
    """Regression for #2: the hook script itself must run and emit valid JSON.

    SettingsPatchTests only asserted the command string was written; the hook
    binary was never executed (its fg->ben rename import bug shipped silently
    because Claude Code swallows hook stderr).
    """

    def _run_hook(self, event, cwd, stdin=None):
        import subprocess
        # DEVNULL keeps the child from blocking on the parent's stdin when
        # the suite runs with a non-TTY, never-closing stdin (pipes).
        kwargs = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "hooks" / "ben-hook.py"), event],
            capture_output=True, text=True, timeout=30,
            cwd=cwd, **kwargs,
        )
        return proc

    def test_sessionstart_and_userpromptsubmit_execute_and_emit_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ben.Store(Path(tmp) / ".ben")
            store.init("hooktest", "verify hook executes")
            for event, stdin in (("sessionstart", None),
                                 ("userpromptsubmit", '{"prompt": "hi"}')):
                proc = self._run_hook(event, tmp, stdin)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr)
                payload = json.loads(proc.stdout)
                outer = payload["hookSpecificOutput"]
                self.assertEqual(outer["hookEventName"].lower(), event)
                ctx = outer.get("additionalContext") or outer.get("contextForClaude")
                self.assertIn("fact-graph", ctx)


class AgentRegistryTests(unittest.TestCase):
    def test_registry_spawn_kill_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = ben.AgentRegistry(root)
            self.assertTrue(reg.spawn("w-c01", ["bash", "-lc", "sleep 60"], cwd=root))
            self.assertTrue(reg.alive("w-c01"))
            self.assertIn("c01", reg.active_workers())
            self.assertTrue(reg.kill("w-c01"))
            self.assertFalse(reg.alive("w-c01"))

    def test_registry_spawn_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = ben.AgentRegistry(root)
            self.assertTrue(reg.spawn("w-c01", ["bash", "-lc", "sleep 60"], cwd=root))
            self.assertFalse(reg.spawn("w-c01", ["bash", "-lc", "sleep 60"], cwd=root))
            reg.kill("w-c01")

    def test_registry_pid_reuse_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = ben.AgentRegistry(root)
            self.assertTrue(reg.spawn("w-x", ["bash", "-lc", "sleep 60"], cwd=root))
            with reg._locked():
                data = reg._load()
                data["workers"]["w-x"]["start_key"] = "999999999"
                reg._save(data)
            self.assertFalse(reg.alive("w-x"))
            # force kill leftover
            import os, signal
            pid = data["workers"]["w-x"]["pid"]
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass

    def test_registry_logs_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = ben.AgentRegistry(root)
            self.assertTrue(reg.spawn(
                "w-c01", ["bash", "-lc", "echo hello-worker; sleep 2"], cwd=root,
            ))
            import time
            time.sleep(0.3)
            text = reg.logs_tail("w-c01", 20)
            self.assertIn("hello-worker", text)
            reg.kill("w-c01")

    def test_registry_concurrent_spawn(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reg = ben.AgentRegistry(root)
            results = []

            def one(i):
                results.append(reg.spawn(
                    f"w-c{i:02d}", ["bash", "-lc", "sleep 30"], cwd=root,
                ))

            threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(sum(1 for r in results if r), 8)
            for i in range(8):
                reg.kill(f"w-c{i:02d}")


class FleetProcTests(unittest.TestCase):
    def test_fleet_hire_fire_proc(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                cfg = {"session": "ben-fleet", "root": "runs", "_base_dir": tmp}
                self.assertTrue(ben._hire_worker(cfg, "c01", 1, max_steps=1))
                self.assertFalse(ben._hire_worker(cfg, "c01", 1, max_steps=1))
                self.assertEqual(ben._active_workers(tmp, "runs"), {"c01"})
                self.assertTrue(ben._fire_worker(tmp, "c01", fleet_root="runs"))
                self.assertEqual(ben._active_workers(tmp, "runs"), set())
            finally:
                os.chdir(old)

    def test_fleet_up_down_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                path = Path("fleet.json")
                path.write_text(json.dumps({
                    "session": "ben-fleet",
                    "root": "runs",
                    "panes": [
                        {"name": "board", "type": "shell",
                         "command": "bash -lc 'echo board; sleep 30'"},
                    ],
                }), encoding="utf-8")
                args = type("A", (), {"action": "up", "file": "fleet.json",
                                      "target": None, "minutes": None,
                                      "max_steps": None, "extra_args": None})()
                self.assertEqual(ben.cmd_fleet(args), 0)
                with self.assertRaises(ben.FGError):
                    ben.cmd_fleet(args)
                args_down = type("A", (), {"action": "down", "file": "fleet.json",
                                           "target": None, "minutes": None,
                                           "max_steps": None, "extra_args": None})()
                self.assertEqual(ben.cmd_fleet(args_down), 0)
            finally:
                os.chdir(old)


class SdkEngineTests(unittest.TestCase):
    def test_engine_auto_falls_back_to_cli(self):
        with mock.patch.dict("os.environ", {"BEN_ENGINE": "auto", "BEN_API_KEY": "",
                                            "OPENAI_API_KEY": "", "BEN_MODEL": "sonnet"},
                             clear=False):
            # wipe keys for this process view
            os.environ.pop("BEN_API_KEY", None)
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ["BEN_ENGINE"] = "auto"
            os.environ["BEN_MODEL"] = "sonnet"
            from ben.llm.runner import resolve_engine
            self.assertEqual(resolve_engine(), "cli")

    def test_sdk_planner_repairs_prose_then_json(self):
        """tools=False must nudge when the model narrates instead of JSON."""
        from tests.fake_openai import make_final, start_server
        script = [
            make_final("I'll inspect the graph first, then propose intents."),
            make_final(
                '{"complete": false, "intents": [{"title": "recon", '
                '"description": "map API", "requires_confirmation": false}]}'
            ),
        ]
        server, port = start_server(script)
        try:
            with mock.patch.dict("os.environ", {
                "BEN_ENGINE": "sdk",
                "BEN_API_KEY": "test-key",
                "BEN_API_BASE": f"http://127.0.0.1:{port}/v1",
                "BEN_MODEL": "fake-model",
                "BEN_MAX_TURNS": "5",
            }):
                try:
                    import openai  # noqa: F401
                except ImportError:
                    self.skipTest("openai not installed")
                from ben.llm.sdk import run_sdk
                with tempfile.TemporaryDirectory() as tmp:
                    env = run_sdk(
                        "propose next intents as JSON",
                        model="fake-model",
                        timeout=30,
                        skip_permissions=True,
                        append_system=None,
                        cwd=Path(tmp),
                        tools=False,
                    )
                self.assertIn('"intents"', env["result"])
                self.assertGreaterEqual(env["turns"], 2)
        finally:
            server.shutdown()

    def test_sdk_tool_loop_two_turns(self):
        from tests.fake_openai import make_final, make_tool_turn, start_server
        script = [
            make_tool_turn("call_1", "shell", {"command": "echo hi"}),
            make_final('{"accepted": true, "data": {}}'),
        ]
        server, port = start_server(script)
        try:
            with mock.patch.dict("os.environ", {
                "BEN_ENGINE": "sdk",
                "BEN_API_KEY": "test-key",
                "BEN_API_BASE": f"http://127.0.0.1:{port}/v1",
                "BEN_MODEL": "fake-model",
                "BEN_MAX_TURNS": "10",
            }):
                try:
                    import openai  # noqa: F401
                except ImportError:
                    self.skipTest("openai not installed")
                from ben.llm.sdk import run_sdk
                with tempfile.TemporaryDirectory() as tmp:
                    env = run_sdk(
                        "do the thing",
                        model="fake-model",
                        timeout=30,
                        skip_permissions=True,
                        append_system=None,
                        cwd=Path(tmp),
                        tools=True,
                    )
                self.assertIn("accepted", env["result"])
                self.assertEqual(env["engine"], "sdk")
        finally:
            server.shutdown()

    def test_sdk_malformed_tool_args_recovers(self):
        from ben.tools.builtin import repair_tool_arguments
        obj, err = repair_tool_arguments("{command: 'echo hi',}")
        # may fail or succeed depending on repair — must not raise
        self.assertTrue(obj is not None or err is not None)
        obj2, err2 = repair_tool_arguments('{"command": "echo hi"}')
        self.assertIsNone(err2)
        self.assertEqual(obj2["command"], "echo hi")

    def test_sdk_max_turns_raises(self):
        from tests.fake_openai import make_tool_turn, start_server
        script = [
            make_tool_turn(f"call_{i}", "shell", {"command": "true"})
            for i in range(5)
        ]
        server, port = start_server(script)
        try:
            with mock.patch.dict("os.environ", {
                "BEN_ENGINE": "sdk",
                "BEN_API_KEY": "test-key",
                "BEN_API_BASE": f"http://127.0.0.1:{port}/v1",
                "BEN_MODEL": "fake-model",
                "BEN_MAX_TURNS": "3",
            }):
                try:
                    import openai  # noqa: F401
                except ImportError:
                    self.skipTest("openai not installed")
                from ben.llm.sdk import run_sdk
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(ben.FGError):
                        run_sdk(
                            "loop forever",
                            model="fake-model",
                            timeout=60,
                            skip_permissions=True,
                            append_system=None,
                            cwd=Path(tmp),
                            tools=True,
                        )
        finally:
            server.shutdown()

    def test_sdk_compact_keeps_tool_pairs(self):
        from ben.llm.context import compact_if_needed
        with mock.patch.dict("os.environ", {"BEN_CONTEXT_CHARS": "50"}):
            messages = [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "task"},
            ]
            for i in range(20):
                messages.append({
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": f"c{i}", "type": "function",
                                    "function": {"name": "shell", "arguments": "{}"}}],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": f"c{i}",
                    "content": "x" * 200,
                })
            out = compact_if_needed(messages)
            self.assertEqual(out[0]["role"], "system")
            self.assertEqual(out[1]["role"], "user")
            # middle tool bodies should be stubbed
            stubbed = [m for m in out if m.get("role") == "tool" and m.get("_compacted")]
            self.assertTrue(stubbed)


class PeersProcTests(unittest.TestCase):
    def test_send_proc_lands_as_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                os.chdir(tmp)
                store = ben.Store(Path(tmp) / ".ben")
                store.init("t", "goal")
                data = ben._default_peers(store)
                data["peers"]["harley"] = {
                    "target": "w-c01",
                    "sender": "tester",
                    "created_at": "t",
                    "note": None,
                }
                ben._save_peers(store, data)
                args = type("A", (), {
                    "store": str(store.root), "peer": "harley",
                    "message": ["hello", "worker"], "sender": None,
                    "channel": None, "no_log": True, "raw": True,
                })()
                self.assertEqual(ben.cmd_send(args), 0)
                hints = store.list_hints()
                self.assertEqual(len(hints), 1)
                self.assertEqual(hints[0]["to"], "w-c01")
                self.assertIn("hello worker", hints[0]["content"])
            finally:
                os.chdir(old)

    def test_hint_to_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ben.Store(Path(tmp) / ".ben")
            store.init("t", "goal")
            store.add_hint("broadcast", "user")
            store.add_hint("private", "user", to="w-c01")
            store.add_hint("other", "user", to="w-c02")
            with mock.patch.dict("os.environ", {"BEN_WORKER": "w-c01"}):
                from ben.agents.prompt import _visible_hints
                vis = _visible_hints(store.list_hints())
                contents = {h["content"] for h in vis}
                self.assertIn("broadcast", contents)
                self.assertIn("private", contents)
                self.assertNotIn("other", contents)

    def test_tmux_target_rejected_with_migration_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ben.Store(Path(tmp) / ".ben")
            store.init("t", "goal")
            args = type("A", (), {
                "store": str(store.root), "discover": False, "add": "x",
                "remove": None, "target": "api-6:0.0", "sender": None,
                "channel": None, "note": None, "json": False,
            })()
            with self.assertRaises(ben.FGError) as ctx:
                ben.cmd_peers(args)
            self.assertIn("no longer supported", str(ctx.exception))

    def test_cli_help_mentions_no_tmux(self):
        help_text = ben.build_parser().format_help()
        self.assertNotIn("tmux panes", help_text.lower())


class ConfigEnvTests(unittest.TestCase):
    """Centralized config: .env parsing, precedence, defaults, validation."""

    def tearDown(self):
        ben.config._LOADED_FROM_FILE.clear()
        ben.config._DOTENV_VALUES.clear()
        ben.config._DOTENV_PATH = None

    def test_parse_env_text_quotes_comments_and_export(self):
        text = (
            "# comment\n"
            "\n"
            "PLAIN=value\n"
            'DOUBLE="quoted value"\n'
            "SINGLE='single value'\n"
            "export EXPORTED=yes\n"
            "not a assignment\n"
            "1BAD=x\n"
        )
        parsed = {k: v for _ln, k, v in ben.config.parse_env_text(text) if k}
        self.assertEqual(parsed["PLAIN"], "value")
        self.assertEqual(parsed["DOUBLE"], "quoted value")
        self.assertEqual(parsed["SINGLE"], "single value")
        self.assertEqual(parsed["EXPORTED"], "yes")
        # malformed lines yield empty keys and are skipped by the loader
        keys = [k for _ln, k, v in ben.config.parse_env_text(text)]
        self.assertEqual(keys.count(""), 2)

    def test_load_dotenv_env_wins_and_source_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "BEN_MODEL=from-file\nBEN_TIMEOUT=999\nBEN_API_KEY=sk-file-1234\n",
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"BEN_MODEL": "from-env"}, clear=False):
                loaded = ben.config.load_dotenv(env_file)
                self.assertEqual(loaded, env_file)
                self.assertEqual(os.environ["BEN_MODEL"], "from-env")
                self.assertEqual(ben.config.get("BEN_MODEL"), "from-env")
                self.assertEqual(os.environ["BEN_TIMEOUT"], "999")
                self.assertEqual(ben.config.source("BEN_MODEL"), "env")
                self.assertEqual(ben.config.source("BEN_TIMEOUT"), ".env")
                self.assertEqual(ben.config.source("BEN_BIN"), "default")
                # secrets are masked, non-secrets are not
                self.assertEqual(ben.config.mask("BEN_API_KEY", "sk-file-1234"), "****1234")
                self.assertEqual(ben.config.mask("BEN_MODEL", "glm-5.3"), "glm-5.3")

    def test_parse_env_text_multiline_json_pool(self):
        text = (
            "BEN_KEY_POOL=[\n"
            '  {"api_key": "sk-a", "api_base": "https://gw-a/v1", "model": "m-a"},\n'
            '  {"api_key": "sk-b", "api_base": "https://gw-b/v1", "model": "m-b"}\n'
            "]\n"
            "BEN_MODEL=grok-4.6\n"
        )
        parsed = {k: v for _ln, k, v in ben.config.parse_env_text(text) if k}
        pool = json.loads(parsed["BEN_KEY_POOL"])
        self.assertEqual(pool[0]["api_key"], "sk-a")
        self.assertEqual(parsed["BEN_MODEL"], "grok-4.6")
        # the loader feeds it straight into the key-pool machinery
        with mock.patch.dict("os.environ", {}, clear=True):
            with tempfile.TemporaryDirectory() as tmp:
                env_file = Path(tmp) / ".env"
                env_file.write_text(text, encoding="utf-8")
                ben.config.load_dotenv(env_file)
                entries = ben._load_key_pool()
                self.assertEqual(len(entries), 2)
                self.assertEqual(entries[1]["model"], "m-b")

    def test_load_dotenv_missing_file_is_silent(self):
        self.assertIsNone(ben.config.load_dotenv(Path(tempfile.gettempdir()) / "no-such.env"))

    def test_get_and_typed_accessors_with_defaults(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ben.config.get("BEN_ENGINE"), "auto")
            self.assertEqual(ben.config.get("BEN_MODEL"), "sonnet")
            self.assertEqual(ben.config.get_int("BEN_TIMEOUT"), 600)
            self.assertEqual(ben.config.get_int("BEN_MAX_TURNS"), 40)
            self.assertEqual(ben.config.get_float("AI_SEND_INITIAL_DELAY"), 0.1)
            with self.assertRaises(ben.FGError):
                ben.config.get_int("EDITOR")  # declared without default
            with mock.patch.dict("os.environ", {"BEN_TIMEOUT": "abc"}, clear=False):
                with self.assertRaisesRegex(ben.FGError, "must be a valid int"):
                    ben.config.get_int("BEN_TIMEOUT")
            with self.assertRaises(KeyError):
                ben.config.get("NOT_A_BEN_KEY")

    def test_config_problems_missing_and_present_credentials(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            problems = ben.config.config_problems()
            self.assertEqual(len(problems), 1)
            self.assertIn("no model credential", problems[0])
        with mock.patch.dict("os.environ", {"BEN_API_KEY": "sk-x"}, clear=True):
            self.assertEqual(ben.config.config_problems(), [])
        with mock.patch.dict(
            "os.environ", {"BEN_API_KEY": "sk-x", "BEN_TIMEOUT": "abc"}, clear=True
        ):
            problems = ben.config.config_problems()
            self.assertTrue(any("BEN_TIMEOUT" in p for p in problems))
        with mock.patch.dict(
            "os.environ", {"BEN_API_KEY": "sk-x", "BEN_ENGINE": "bogus"}, clear=True
        ):
            problems = ben.config.config_problems()
            self.assertTrue(any("BEN_ENGINE" in p for p in problems))

    def test_env_example_keys_are_all_registered(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        keys = {k for _ln, k, v in ben.config.parse_env_text(text) if k}
        unknown = keys - set(ben.config.ENV_SPECS)
        self.assertEqual(unknown, set(), msg=f"unregistered keys in .env.example: {unknown}")

    def test_grok_build_subscription_model_slugs(self):
        from ben.llm import grok_build

        self.assertEqual(grok_build.subscription_model("grok"), "grok-4.6")
        self.assertEqual(grok_build.subscription_model("grok/grok-4.6"), "grok-4.6")
        self.assertEqual(grok_build.subscription_model("  Grok/grok-4.5  "), "grok-4.5")
        self.assertIsNone(grok_build.subscription_model("grok/"))
        self.assertIsNone(grok_build.subscription_model("xai/grok-4.6"))
        self.assertTrue(grok_build.skips_api_key("grok"))
        self.assertFalse(grok_build.skips_api_key("xai/grok-4.6"))

    def test_grok_build_config_requires_login(self):
        from ben.llm import grok_build

        with mock.patch.dict("os.environ", {"BEN_MODEL": "grok"}, clear=True):
            with mock.patch.object(grok_build, "is_authenticated", return_value=False):
                problems = ben.config.config_problems()
                self.assertTrue(any("Grok Build login" in p for p in problems))
            with mock.patch.object(grok_build, "is_authenticated", return_value=True):
                self.assertEqual(ben.config.config_problems(), [])

    def test_ben_config_subcommand_check_and_table(self):
        # Isolate from the repo-root .env: dotenv_candidates() always includes
        # <repo>/.env, so point BEN_ENV_FILE at an empty file that loads first.
        with tempfile.TemporaryDirectory() as tmp:
            empty_env = Path(tmp) / "empty.env"
            empty_env.write_text("", encoding="utf-8")
            out = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {"BEN_API_KEY": "sk-zzz", "BEN_ENV_FILE": str(empty_env)},
                clear=True,
            ):
                with contextlib.redirect_stdout(out):
                    rc = ben.main(["config", "--check"])
                self.assertEqual(rc, 0)
                self.assertIn("config ok", out.getvalue())
            out = io.StringIO()
            with mock.patch.dict(
                "os.environ", {"BEN_ENV_FILE": str(empty_env)}, clear=True
            ):
                with contextlib.redirect_stdout(out):
                    rc = ben.main(["config"])
                self.assertEqual(rc, 0)
                rendered = out.getvalue()
                self.assertIn("BEN_ENGINE", rendered)
                self.assertIn("sdk gateway", rendered)
                self.assertIn("no model credential", rendered)

    def test_main_loads_dotenv_before_argparse_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env").write_text("BEN_TIMEOUT=777\n", encoding="utf-8")
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.dict(
                    "os.environ", {"BEN_API_KEY": "sk-env-zzz"}, clear=False
                ):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        rc = ben.main(["config", "--check"])
                    self.assertEqual(rc, 0)
                    self.assertEqual(ben.config.get("BEN_TIMEOUT"), "777")
                    ns = ben.build_parser().parse_args(["auto"])
                    self.assertEqual(ns.timeout, 777)
            finally:
                os.chdir(old_cwd)
                os.environ.pop("BEN_TIMEOUT", None)
                ben.config._LOADED_FROM_FILE.discard("BEN_TIMEOUT")
                ben.config._DOTENV_VALUES.pop("BEN_TIMEOUT", None)


class StatusViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = ben.Store(Path(self.tmp.name) / ".ben")
        self.store.init("test", "ship it")

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_view_aggregates_graph(self):
        from ben.web.status import build_status_view
        seed = self.store.add_fact("seed", "test", None)
        cred = self.store.add_fact("found creds", "test", None, title="creds",
                                   kind="cred", data={"user": "admin", "password": "x"})
        vuln = self.store.add_fact("found vuln", "test", None, kind="vuln")
        open_i = self.store.add_intent([seed["id"]], "open task", "test")
        claimed_i = self.store.add_intent([seed["id"]], "claimed task", "test")
        self.store.claim_intent(claimed_i["id"], "some-worker")
        done_i = self.store.add_intent([seed["id"]], "done task", "test")
        self.store.conclude_intent(done_i["id"], cred["id"], "test")

        s = build_status_view(self.store)
        self.assertEqual(s["summary"]["facts"], 4)          # seed+cred+vuln+goal
        self.assertEqual(s["summary"]["intents"], 3)
        self.assertEqual(s["summary"]["tasks_done"], 1)
        self.assertEqual(s["summary"]["tasks_claimed"], 1)
        self.assertEqual(s["summary"]["tasks_open"], 2)
        self.assertEqual(s["summary"]["kind_counts"]["cred"], 1)
        self.assertEqual(s["summary"]["kind_counts"]["vuln"], 1)
        # ordering: claimed first, done last
        self.assertEqual([t["id"] for t in s["tasks"]],
                         [claimed_i["id"], open_i["id"], done_i["id"]])
        self.assertEqual(s["tasks"][0]["worker"], "some-worker")
        # recent facts exclude the goal terminal and carry data
        self.assertNotIn("goal", [f["id"] for f in s["recent_facts"]])
        cred_view = next(f for f in s["recent_facts"] if f["id"] == cred["id"])
        self.assertEqual(cred_view["data"]["password"], "x")
        self.assertGreaterEqual(s["elapsed_s"], 0)

    def test_status_view_keeps_dead_workers_visible(self):
        """A crashed worker must show as alive=False, and polling must not reap."""
        from ben.web.status import build_status_view
        reg_root = Path(self.tmp.name) / "fleet"
        reg = ben.AgentRegistry(reg_root)
        with reg._locked():
            data = reg._load()
            data["workers"]["w-crashed"] = {
                # a pid that cannot be running: the "process died, record stayed"
                "pid": 999999,
                "start_key": None,
                "argv": ["ben", "auto"],
                "cwd": self.tmp.name,
                "log": str(reg.log_path("w-crashed")),
                "started_at": "2026-01-01T00:00:00Z",
                "meta": {"minutes": 5},
            }
            reg._save(data)

        s = build_status_view(self.store, registry_root=reg_root)
        self.assertEqual([w["name"] for w in s["workers"]], ["w-crashed"])
        self.assertFalse(s["workers"][0]["alive"])
        # the read itself must not have pruned the registry
        with reg._locked():
            self.assertIn("w-crashed", reg._load()["workers"])

    def test_status_view_links_worker_to_current_task(self):
        from ben.web.status import build_status_view
        reg_root = Path(self.tmp.name) / "fleet"
        reg = ben.AgentRegistry(reg_root)
        self.assertTrue(reg.spawn("w-c01", ["bash", "-lc", "echo hi; sleep 60"],
                                 cwd=self.tmp.name, meta={"target": "c01", "minutes": 5}))
        with reg._locked():
            pid = reg._load()["workers"]["w-c01"]["pid"]
        seed = self.store.add_fact("seed", "test", None)
        task = self.store.add_intent([seed["id"]], "in flight", "test")
        self.store.claim_intent(task["id"], f"mymodel-{pid}")

        # spawn writes asynchronously; poll briefly for the first log line
        deadline = time.time() + 3.0
        s = None
        while time.time() < deadline:
            s = build_status_view(self.store, registry_root=reg_root)
            if s["log_tail"].get("w-c01"):
                break
            time.sleep(0.05)
        self.assertIsNotNone(s)
        self.assertEqual(len(s["workers"]), 1)
        w = s["workers"][0]
        self.assertEqual(w["name"], "w-c01")
        self.assertTrue(w["alive"])
        self.assertEqual(w["timebox_s"], 300)
        self.assertIsNotNone(w["timebox_left_s"])
        self.assertEqual([c["id"] for c in w["current"]], [task["id"]])
        self.assertTrue(s["log_tail"]["w-c01"])
        self.assertIn("hi", s["log_tail"]["w-c01"][0])
        reg.kill("w-c01")

    def test_status_view_degrades_without_registry(self):
        from ben.web.status import build_status_view
        import os
        # chdir away from the repo so the cwd fallback can't find runs/workers.json
        old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        try:
            s = build_status_view(self.store)
            self.assertEqual(s["workers"], [])
            self.assertFalse(s["registry_found"])
            self.assertEqual(s["log_tail"], {})
        finally:
            os.chdir(old_cwd)

    def test_static_html_inlines_status(self):
        self.store.add_fact("</script> evil", "test", None)
        html = ben._render_static_html(self.store)
        self.assertIn("/*__STATUS_JSON__*/", html)
        self.assertIn(r"\u003c/script\u003e", html)
        self.assertNotIn("/*__STATUS_JSON__*/ null /*__STATUS_END__*/", html)


class ConsoleAttachTests(unittest.TestCase):
    def test_console_name_accepts_peer_prefix(self):
        from ben.commands.console_cmds import _norm_name
        self.assertEqual(_norm_name("main"), "main")
        self.assertEqual(_norm_name("c-main"), "main")
        self.assertEqual(_norm_name("  c-claude  "), "claude")

    def test_console_log_path_resolves_default_and_keeps_bytes(self):
        from ben.runtime.console import capture_console, console_log_path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            log = console_log_path(base, "main")
            self.assertEqual(log.name, "c-main.raw")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("line one\nline two\n", encoding="utf-8")
            # capture stays compatible with the file attach() tails
            self.assertIn("line two", capture_console(base, "main", lines=5))

    def test_console_start_fails_fast_without_ptmx(self):
        """No /dev/ptmx must raise a clear error instead of a socket timeout."""
        from unittest import mock
        import ben.runtime.console as console_mod
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".ben"
            base.mkdir()
            with mock.patch.object(console_mod, "_pty_available", return_value=False):
                with self.assertRaises(ben.FGError) as ctx:
                    console_mod.start_console(base, "demo", ["bash", "-lc", "true"])
            msg = str(ctx.exception)
            self.assertIn("/dev/ptmx", msg)
            self.assertIn("pseudo-terminal", msg)


class StaleTaskTests(unittest.TestCase):
    def test_worker_current_carries_task_age(self):
        from ben.web.status import build_status_view
        with tempfile.TemporaryDirectory() as tmp:
            store = ben.Store(Path(tmp) / ".ben")
            store.init("test", "ship it")
            reg_root = Path(tmp) / "runs"
            reg = ben.AgentRegistry(reg_root)
            self.assertTrue(reg.spawn("w-a", ["bash", "-lc", "echo x; sleep 60"],
                                     cwd=tmp, meta={"target": "a", "minutes": 5}))
            with reg._locked():
                pid = reg._load()["workers"]["w-a"]["pid"]
            seed = store.add_fact("seed", "test", None)
            task = store.add_intent([seed["id"]], "slow task", "test")
            store.claim_intent(task["id"], f"m-{pid}")

            s = build_status_view(store, registry_root=reg_root)
            cur = s["workers"][0]["current"][0]
            self.assertEqual(cur["id"], task["id"])
            self.assertIsNotNone(cur["age_s"])
            self.assertGreaterEqual(cur["age_s"], 0)
            reg.kill("w-a")
