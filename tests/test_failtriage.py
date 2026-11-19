#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test suite for ung220z-tool-failtriage.

Run from the repository root:
    python3 tests/test_failtriage.py

16 tests: 3 unit (parser / device / ranking) + 13 behavioural (spawn the CLI and
assert exit codes, JSON shape, precedence, determinism and stdin equivalence).
"""

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "bin", "ung220z-failtriage")
IN = os.path.join(ROOT, "examples", "in")
OUT = os.path.join(ROOT, "examples", "out")

# Load the executable (it has no .py suffix) as a module for unit tests only.
_loader = SourceFileLoader("failtriage", CLI)
_spec = importlib.util.spec_from_loader("failtriage", _loader)
ft = importlib.util.module_from_spec(_spec)
_loader.exec_module(ft)


def run(args, stdin_text=None):
    """Run the CLI, return (returncode, stdout, stderr)."""
    p = subprocess.run([sys.executable, CLI] + args,
                       input=stdin_text if stdin_text is not None else None,
                       capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout, p.stderr


def read_log(name):
    with open(os.path.join(IN, name), "r", encoding="utf-8") as f:
        return f.read()


# ── unit tests ─────────────────────────────────────────────────────────────
class TestUnits(unittest.TestCase):
    def test_01_parse_log_lines(self):
        text = "[09:06:29] INFO   会话开始  目标=192.168.1.1  账户=user\n" \
               "这是一行提示，不是日志\n" \
               "[09:06:30] HTTP   telnet.gch → TelnetSet Success!\n"
        entries, skipped = ft.parse_lines(text)
        self.assertEqual(len(entries), 2)
        self.assertEqual(skipped, 1)
        self.assertEqual(entries[0]["tag"], "INFO")
        self.assertEqual(entries[0]["line"], 1)

    def test_02_detect_device(self):
        text = "...\n硬件型号 | GM232 | 固件版本 | V1A0.A04.01\n"
        dev = ft.detect_device(text)
        self.assertEqual(dev["model"], "GM232")
        self.assertEqual(dev["firmware"], "V1A0.A04.01")

    def test_03_precedence_gch_before_port(self):
        entries, _ = ft.parse_lines(read_log("gch-400-port23-closed.log"))
        signals = ft.extract_signals(entries)
        ranked = ft.rank_root_causes(signals)
        codes = [r["code"] for r in ranked]
        self.assertEqual(codes[0], "GCH_HTTP_ERROR")
        self.assertIn("TELNET_PORT_CLOSED", codes)
        self.assertLess(codes.index("GCH_HTTP_ERROR"), codes.index("TELNET_PORT_CLOSED"))


# ── behavioural tests ──────────────────────────────────────────────────────
class TestBehaviour(unittest.TestCase):
    def test_04_success_exit0(self):
        rc, out, err = run(["-i", "examples/in/success.log"])
        self.assertEqual(rc, 0, err)
        self.assertIn("SUCCESS", out)

    def test_05_gch400_exit1_and_root_cause(self):
        rc, out, err = run(["-i", "examples/in/gch-400-port23-closed.log", "--json"])
        self.assertEqual(rc, 1, err)
        rep = json.loads(out)
        self.assertEqual(rep["summary"]["root_cause"], "GCH_HTTP_ERROR")
        self.assertEqual(rep["summary"]["verdict"], "out_of_scope_model")
        # the L9 body line is a contributing signal, not the primary cause
        self.assertGreaterEqual(len(rep["root_causes"]), 2)

    def test_06_gch404_carries_status_code(self):
        rc, out, _ = run(["-i", "examples/in/gch-404.log", "--json"])
        self.assertEqual(rc, 1)
        rep = json.loads(out)
        http = [s for s in rep["signals"] if s["id"] == "gch_http_error"]
        self.assertTrue(any("404" in s["detail"] for s in http))
        self.assertEqual(rep["device"]["model"], "GM232")

    def test_07_port23_closed_only(self):
        rc, out, _ = run(["-i", "examples/in/gch-success-port23-closed.log", "--json"])
        self.assertEqual(rc, 1)
        rep = json.loads(out)
        self.assertEqual(rep["summary"]["root_cause"], "TELNET_PORT_CLOSED")
        self.assertEqual(rep["summary"]["verdict"], "in_scope_telnet_disabled")

    def test_08_telnet_auth_refused(self):
        rc, out, _ = run(["-i", "examples/in/telnet-auth-refused.log", "--json"])
        self.assertEqual(rc, 1)
        rep = json.loads(out)
        self.assertEqual(rep["summary"]["root_cause"], "TELNET_AUTH_REFUSED")
        self.assertEqual(rep["summary"]["verdict"], "in_scope_credential_mismatch")

    def test_09_web_unreachable(self):
        rc, out, _ = run(["-i", "examples/in/web-unreachable.log", "--json"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["summary"]["root_cause"], "WEB_UNREACHABLE")

    def test_10_decrypt_failed(self):
        rc, out, _ = run(["-i", "examples/in/decrypt-failed.log", "--json"])
        self.assertEqual(rc, 1)
        self.assertEqual(json.loads(out)["summary"]["root_cause"], "CFG_DECRYPT_FAILED")

    def test_11_inconclusive_exit0_by_default_exit1_on_warning(self):
        rc0, out0, _ = run(["-i", "examples/in/inconclusive.log", "--json"])
        self.assertEqual(rc0, 0)
        self.assertEqual(json.loads(out0)["summary"]["root_cause"], "INCONCLUSIVE")
        rc1, _, _ = run(["-i", "examples/in/inconclusive.log", "--fail-on", "warning"])
        self.assertEqual(rc1, 1)

    def test_12_fail_on_never(self):
        rc, _, _ = run(["-i", "examples/in/gch-404.log", "--fail-on", "never"])
        self.assertEqual(rc, 0)

    def test_13_bad_input_path_exit2(self):
        rc, _, err = run(["-i", "/nonexistent/definitely-not-a-log.log"])
        self.assertEqual(rc, 2)
        self.assertIn("无法读取输入", err)

    def test_14_empty_stdin_exit2(self):
        rc, _, err = run([], stdin_text="")
        self.assertEqual(rc, 2)
        self.assertIn("输入为空", err)

    def test_15_json_equals_examples_out(self):
        cases = ["success", "gch-400-port23-closed", "gch-404", "telnet-auth-refused",
                 "gch-success-port23-closed", "web-unreachable", "decrypt-failed",
                 "inconclusive"]
        for name in cases:
            with self.subTest(case=name):
                rc, out, err = run(["-i", "examples/in/%s.log" % name, "--json"])
                self.assertIn(rc, (0, 1), err)
                with open(os.path.join(OUT, "%s.json" % name), encoding="utf-8") as fh:
                    expected = json.load(fh)
                self.assertEqual(json.loads(out), expected)

    def test_16_deterministic_and_stdin_equivalent(self):
        args = ["-i", "examples/in/gch-400-port23-closed.log", "--json"]
        _, a, _ = run(args)
        _, b, _ = run(args)
        self.assertEqual(a, b)  # byte-identical replay
        rc_s, out_s, _ = run(["--json"], stdin_text=read_log("gch-400-port23-closed.log"))
        rc_f, out_f, _ = run(args)
        self.assertEqual(rc_s, rc_f)
        a_rep, b_rep = json.loads(out_s), json.loads(out_f)
        # only input.path differs between stdin and file mode; everything else must be identical
        self.assertIsNone(a_rep["input"].pop("path"))
        b_rep["input"].pop("path")
        self.assertEqual(a_rep, b_rep)


if __name__ == "__main__":
    unittest.main(verbosity=2)