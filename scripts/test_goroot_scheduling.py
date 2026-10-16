"""Execute the workflow's runner steps with a controlled corpus runner."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/goroot.yml"
VERSIONS = ("1.26.7", "1.27.0")
FAKE_RUNNER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
def option(name):
    return args[args.index(name) + 1]
version = pathlib.Path(option("-goroot")).name
record = dict(version=version, shard=option("-shard-index"), args=args)
def event(kind):
    data = (json.dumps(dict(record, event=kind)) + "\n").encode()
    fd = os.open(os.environ["FAKE_EVENTS"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.write(fd, data)
    os.close(fd)
if "-list-case-paths" in args:
    event("select")
    if os.environ.get("FAKE_SELECTION_FAILURE") == version:
        sys.exit(2)
    print("\n".join(json.loads(os.environ["FAKE_CASES"]).get(version, ["ordinary.go"])))
    sys.exit(0)
event("start")
marker = pathlib.Path(os.environ["RUNNER_TEMP"]) / ("started-" + version)
marker.touch()
if os.environ["FAKE_PARALLEL"] == "1":
    # A rendezvous proves overlap without depending on process start timing.
    deadline = time.monotonic() + 5
    while len(list(marker.parent.glob("started-*"))) != 2:
        if time.monotonic() >= deadline:
            sys.exit(3)
        time.sleep(0.01)
else:
    time.sleep(0.1)
event("end")
sys.exit(1 if os.environ.get("FAKE_RUN_FAILURE") == version else 0)
'''


@unittest.skipUnless(shutil.which("bash"), "workflow steps require Bash")
class SchedulingTests(unittest.TestCase):
    def run_step(self, *, platform="windows-msvc/386", profile="", cases=None,
                 serial=True, run_failure="", selection_failure=""):
        steps = WORKFLOW.read_text().split("      - name: Run GOROOT runner\n")[1:]
        self.assertEqual(2, len(steps))
        step = steps[bool(profile)].split("        run: |\n", 1)[1]
        script = textwrap.dedent(step.split("\n      - ", 1)[0])
        expressions = {
            "matrix.shard-index": "1",
            "matrix.windows_arch": platform.rsplit("/", 1)[-1] if platform.startswith("windows-") else "",
            "matrix.platform": platform,
            "matrix.wasm_profile": profile,
            "steps.go126.outputs.version": VERSIONS[0],
            "steps.go127.outputs.version": VERSIONS[1],
        }
        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda m: expressions[m[1]], script)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "test/goroot").mkdir(parents=True)
            runner = root / "runner"
            runner.write_text(FAKE_RUNNER)
            runner.chmod(0o755)
            events = root / "events.jsonl"
            env = dict(os.environ, RUNNER_TEMP=temp,
                       RUNNER_OS="Windows" if platform.startswith("windows-") else "macOS" if platform.startswith("darwin/") else "Linux",
                       GO126_GOROOT=str(root / VERSIONS[0]), GO127_GOROOT=str(root / VERSIONS[1]),
                       PAIRED_SHARD_INDEX="5", LLGO_GOROOT_SHARD_TOTAL="16" if profile else "8",
                       LLGO_GOROOT_TEST_TIMEOUT="150m", LLGO_GOROOT_RUNNER=str(runner),
                       GOROOT_XFAIL="/mock/wasi-policy.yaml" if profile == "W32-WASI" else "test/goroot/xfail.yaml",
                       FAKE_EVENTS=str(events), FAKE_CASES=json.dumps(cases or {}),
                       FAKE_PARALLEL="0" if serial else "1", FAKE_RUN_FAILURE=run_failure,
                       FAKE_SELECTION_FAILURE=selection_failure)
            result = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                                    cwd=root, env=env, text=True, capture_output=True, timeout=15)
            records = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
        if selection_failure:
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse(any(r["event"] == "start" for r in records))
            return records
        self.assertEqual(1 if run_failure else 0, result.returncode, result.stdout + result.stderr)
        runs = [r for r in records if r["event"] in ("start", "end")]
        self.assertEqual(4, len(runs), runs)
        if serial:
            self.assertEqual([("start", VERSIONS[0]), ("end", VERSIONS[0]),
                              ("start", VERSIONS[1]), ("end", VERSIONS[1])],
                             [(r["event"], r["version"]) for r in runs])
        else:
            self.assertEqual(["start", "start", "end", "end"], [r["event"] for r in runs])
        starts = {r["version"]: r for r in runs if r["event"] == "start"}
        self.assertEqual("1", starts[VERSIONS[0]]["shard"])
        self.assertEqual("9" if profile else "5", starts[VERSIONS[1]]["shard"])
        for record in starts.values():
            self.assertIn("-test.timeout=150m", record["args"])
            self.assertNotIn("-case", record["args"])
            self.assertNotIn("-run-timeout", record["args"])
            if profile:
                self.assertEqual(env["GOROOT_XFAIL"], record["args"][record["args"].index("-xfail") + 1])
        return records

    def test_windows_386_stress_in_either_go_version(self):
        for case in ("index0.go", "cmplxdivide.go", "fixedbugs/issue39541.go"):
            for version in VERSIONS:
                with self.subTest(case=case, version=version):
                    self.run_step(cases={version: [case]})

    def test_intel_channel_stress_preserves_memory_budget(self):
        for version in VERSIONS:
            records = self.run_step(platform="darwin/amd64", cases={version: ["ken/chan.go"]})
            for record in records:
                if record["event"] == "start":
                    args = record["args"]
                    self.assertEqual("4096", args[args.index("-max-rss-mib") + 1])

    def test_intel_rangegen_retains_existing_memory_budget(self):
        records = self.run_step(platform="darwin/amd64", cases={VERSIONS[1]: ["rangegen.go"]})
        for record in records:
            if record["event"] == "start":
                args = record["args"]
                self.assertEqual("8192", args[args.index("-max-rss-mib") + 1])

    def test_other_native_shards_remain_parallel(self):
        for platform in ("windows-msvc/386", "windows-mingw/386", "darwin/amd64", "darwin/arm64", "linux/amd64"):
            with self.subTest(platform=platform):
                self.run_step(platform=platform, serial=False)
        self.run_step(platform="darwin/arm64", cases={VERSIONS[0]: ["ken/chan.go"]}, serial=False)

    def test_emscripten32_winbatch_in_either_go_version(self):
        for version in VERSIONS:
            self.run_step(platform="wasm", profile="J32-Emscripten", cases={version: ["winbatch.go"]})

    def test_other_wasm_shards_remain_parallel(self):
        for profile in ("J32-Emscripten", "J64-Emscripten", "W32-WASI"):
            with self.subTest(profile=profile):
                self.run_step(platform="wasm", profile=profile, serial=False)
        self.run_step(platform="wasm", profile="W32-WASI", cases={VERSIONS[0]: ["winbatch.go"]}, serial=False)

    def test_run_failure_is_reported_after_both_versions(self):
        for profile, case in (("", "index0.go"), ("J32-Emscripten", "winbatch.go")):
            for serial in (True, False):
                for version in VERSIONS:
                    with self.subTest(profile=profile, serial=serial, failure=version):
                        self.run_step(profile=profile, serial=serial, run_failure=version,
                                      cases={VERSIONS[0]: [case]} if serial else {})

    def test_selection_failure_cannot_silently_fall_back_to_parallel(self):
        for profile in ("", "J32-Emscripten"):
            for version in VERSIONS:
                with self.subTest(profile=profile, failure=version):
                    self.run_step(profile=profile, selection_failure=version)


if __name__ == "__main__":
    unittest.main()
