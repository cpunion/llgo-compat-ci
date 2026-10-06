import json
import tempfile
import unittest
from pathlib import Path

from check_report_coverage import (
    GOROOT_PLATFORMS,
    WASM_SHARDS,
    check_goroot,
    check_partition,
    check_std,
    std_native_reports,
)


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.versions = ("1.26.7", "1.27.0")

    def goroot_rows(self):
        return [
            [platform, version, str(index), "1", "1", "1", "0", "0", "8"]
            for platform in GOROOT_PLATFORMS
            for version in self.versions
            for index in range(8)
        ]

    def check_rows(self, rows):
        summary = self.root / "summary.tsv"
        summary.write_text("".join("\t".join(row) + "\n" for row in rows))
        return check_goroot(summary, self.versions)[0]

    def make_std_reports(self):
        native_dir, wasm_dir = self.root / "native", self.root / "wasm"
        native_dir.mkdir()
        for pos, key in enumerate(sorted(std_native_reports())):
            (native_dir / f"summary-{pos}.tsv").write_text("\t".join(map(str, (*key, "success"))) + "\n")
        for profile, total in WASM_SHARDS.items():
            for index in range(total):
                path = wasm_dir / f"{profile}-{index}" / "acceptance.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"profile": profile, "shard": index, "shards": total}))
        return native_dir, wasm_dir

    def test_mixed_windows_splits_cover_every_hash_once(self):
        shards = [(index, 8) for index in range(8) if index != 5]
        shards += [(5, 32), (13, 32), (21, 32), (29, 64), (61, 64)]
        self.assertIsNone(check_partition(shards))

    def test_equal_count_cannot_hide_duplicate_and_missing_shards(self):
        self.assertIn("overlapping", check_partition([(index, 8) for index in range(7)] + [(0, 8)]))

    def test_partial_and_invalid_partitions_fail(self):
        self.assertIn("coverage is 7/8", check_partition([(index, 8) for index in range(7)]))
        self.assertIn("invalid", check_partition([(8, 8)]))
        self.assertIn("invalid", check_partition([(0, 0)]))

    def test_full_goroot_coverage(self):
        self.assertEqual([], self.check_rows(self.goroot_rows()))

    def test_issue35_partial_matrix_cannot_pass(self):
        rows = []
        for version in self.versions:
            rows += [["js/wasm", version, str(index), "1", "1", "1", "0", "0", "16"] for index in range(16)]
            rows += [["windows-msvc/arm64", version, str(index), "1", "1", "1", "0", "0", "64"] for index in (29, 61)]
        errors = self.check_rows(rows)
        self.assertTrue(any("darwin/arm64" in error for error in errors))
        self.assertTrue(any("windows-msvc/arm64" in error and "1/32" in error for error in errors))

    def test_goroot_incomplete_case_results_fail(self):
        rows = self.goroot_rows()
        rows[0][4] = "0"
        self.assertTrue(any("incomplete case results" in error for error in self.check_rows(rows)))

    def test_goroot_unknown_selection_and_missing_denominator_fail(self):
        rows = self.goroot_rows()
        rows[0][3] = "?"
        rows[1].pop()
        errors = self.check_rows(rows)
        self.assertTrue(any("nine TSV columns" in error for error in errors))
        self.assertTrue(any("invalid literal" in error for error in errors))

    def test_std_full_report_set(self):
        errors, description = check_std(*self.make_std_reports())
        self.assertEqual([], errors)
        self.assertEqual("native reports 11/11, Wasm reports 14/14", description)

    def test_std_missing_native_and_entire_wasi_profile(self):
        native, wasm = self.make_std_reports()
        next(native.glob("summary-*.tsv")).unlink()
        for path in wasm.glob("W32-WASI-*/acceptance.json"):
            path.unlink()
        errors, description = check_std(native, wasm)
        self.assertEqual(6, len(errors))
        self.assertIn("native reports 10/11, Wasm reports 9/14", description)
        self.assertTrue(any("W32-WASI" in error for error in errors))

    def test_std_duplicate_and_wrong_shard_total_fail(self):
        native, wasm = self.make_std_reports()
        sample = next(native.glob("summary-*.tsv"))
        (native / "summary-duplicate.tsv").write_text(sample.read_text())
        path = next(wasm.glob("J32-GoJS-*/acceptance.json"))
        data = json.loads(path.read_text())
        data["shards"] = 5
        path.write_text(json.dumps(data))
        errors, _ = check_std(native, wasm)
        self.assertTrue(any("duplicate native" in error for error in errors))
        self.assertTrue(any("unexpected Wasm" in error for error in errors))
        self.assertTrue(any("missing Wasm" in error for error in errors))

    def test_std_malformed_json_fails(self):
        native, wasm = self.make_std_reports()
        next(wasm.rglob("acceptance.json")).write_text("invalid json")
        errors, _ = check_std(native, wasm)
        self.assertEqual(2, len(errors))


if __name__ == "__main__":
    unittest.main()
