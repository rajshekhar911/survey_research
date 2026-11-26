"""End-to-end API test: python3 -m unittest discover -s tests -v"""
import base64
import csv
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import design  # noqa: E402
import server  # noqa: E402

PW = "test-password-123"


class SurveyE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.SETTINGS["min_seconds"] = 0
        cls.srv = server.make_server("127.0.0.1", 0, Path(cls.tmp.name) / "t.db", PW)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def req(self, path, body=None, admin=False):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        if admin:
            r.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{PW}".encode()).decode())
        try:
            with urllib.request.urlopen(r) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if "json" in resp.headers["Content-Type"] else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def run_respondent(self, pid):
        s, st = self.req("/api/start", {"consent": True, "pid": pid, "src": "test"})
        self.assertEqual(s, 200)
        tok = st["token"]
        self.assertEqual(st["current_page"], "task_0")
        self.assertEqual(len(st["design"]["tasks"]), server.N_TASKS)
        for i in range(server.N_TASKS):
            s, _ = self.req("/api/choice", {"token": tok, "task": i, "chosen_pos": 0, "ms": 4000})
            self.assertEqual(s, 200)
        self.req("/api/event", {"token": tok, "page": "task_0", "type": "verify_open",
                                "detail": {"task": 0, "pos": 1, "brand": "=cmd"}})
        s, done = self.req("/api/complete", {"token": tok})
        self.assertEqual(s, 200, done)
        return tok, done

    def test_design_properties(self):
        stim = design.load_stimuli()
        for seed in range(200):
            d = design.generate_design(stim, seed, n_tasks=8)
            self.assertEqual(len({t["category"] for t in d["tasks"]}), 8)  # each category once
            for t in d["tasks"]:
                alts = t["alts"]
                self.assertEqual(sorted(a["claim"] for a in alts),
                                 ["none", "unverifiable", "verifiable"])
                self.assertEqual(len({a["brand"] for a in alts}), 3)
                self.assertEqual(len({a["price"] for a in alts}), 3)
                self.assertEqual(len({a["affect"] for a in alts}), 2)
        d = design.generate_design(stim, 5, n_tasks=12)  # longer designs still work
        cats = [t["category"] for t in d["tasks"]]
        self.assertTrue(all(a != b for a, b in zip(cats, cats[1:])))

    def test_full_flow_and_exports(self):
        tok, done = self.run_respondent("P-full")
        self.assertEqual(done["status"], "completed")
        self.assertTrue(done["completion_code"].startswith("C"))
        s, _ = self.req("/api/choice", {"token": tok, "task": 0, "chosen_pos": 1})
        self.assertEqual(s, 409)  # completed survey cannot be changed
        s, again = self.req("/api/start", {"consent": True, "pid": "P-full"})
        self.assertEqual(again["completion_code"], done["completion_code"])  # no second entry

        s, stats = self.req("/admin/api/stats", admin=True)
        self.assertEqual(s, 200)
        self.assertGreaterEqual(stats["completed"], 1)

        s, raw = self.req("/admin/export/choices_long.csv", admin=True)
        rows = [r for r in csv.DictReader(io.StringIO(raw)) if r["pid"] == "P-full"]
        self.assertEqual(len(rows), server.N_TASKS * 3)
        self.assertEqual(sum(int(r["chosen"]) for r in rows), server.N_TASKS)

        s, raw = self.req("/admin/export/respondents.csv", admin=True)
        row = next(r for r in csv.DictReader(io.StringIO(raw)) if r["pid"] == "P-full")
        self.assertEqual(row["flag_position_straightline"], "True")

        s, raw = self.req("/admin/export/events.csv", admin=True)
        self.assertIn("verify_open", raw)
        s, cs = self.req("/admin/export/choice_sets.json", admin=True)
        self.assertTrue(cs["respondents"])

    def test_resume_mid_survey(self):
        s, st = self.req("/api/start", {"consent": True})
        tok = st["token"]
        self.req("/api/choice", {"token": tok, "task": 0, "chosen_pos": 2})
        self.req("/api/choice", {"token": tok, "task": 1, "chosen_pos": 1})
        s, r = self.req("/api/resume", {"token": tok})
        self.assertEqual(r["current_page"], "task_2")
        s, _ = self.req("/api/complete", {"token": tok})
        self.assertEqual(s, 409)  # not finished yet

    def test_validation_and_auth(self):
        self.assertEqual(self.req("/api/start", {"consent": False})[0], 400)
        s, st = self.req("/api/start", {"consent": True})
        tok = st["token"]
        self.assertEqual(self.req("/api/choice", {"token": tok, "task": 0, "chosen_pos": 5})[0], 400)
        self.assertEqual(self.req("/api/choice", {"token": tok, "task": 99, "chosen_pos": 0})[0], 400)
        self.assertEqual(self.req("/api/choice", {"token": "x" * 30, "task": 0, "chosen_pos": 0})[0], 401)
        self.assertEqual(self.req("/api/event", {"token": tok, "type": "hack"})[0], 400)
        self.assertEqual(self.req("/admin/api/stats")[0], 401)
        self.assertEqual(self.req("/admin/export/contacts.csv", admin=True)[0], 404)
        self.assertEqual(self.req("/static/../server.py")[0], 404)
        s, page = self.req("/")
        self.assertIn("app.js", page)


if __name__ == "__main__":
    unittest.main()
