import unittest
from collections import defaultdict

from check_report_coverage import NATIVE_PLATFORMS, check_partition, std_native_reports
from compatibility_matrix import embedded_matrix, native_matrix, std_matrix


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.jobs = native_matrix()["include"]

    def test_all_platforms_and_both_version_partitions(self):
        groups = defaultdict(list)
        for job in self.jobs:
            platform = job["platform"]
            total = int(job["shard-total"])
            for version, key in (("1.26", "shard-index"), ("1.27", "paired-shard-index")):
                groups[platform, version].append((int(job[key]), total))
        self.assertEqual({(p, v) for p in NATIVE_PLATFORMS for v in ("1.26", "1.27")}, set(groups))
        for key, shards in groups.items():
            with self.subTest(platform_version=key):
                self.assertIsNone(check_partition(shards))

    def test_windows_targets_match_the_host_architecture(self):
        for job in self.jobs:
            if job["os"] == "windows-2022":
                self.assertIn(job["windows_arch"], ("amd64", "386"))
            elif job["os"] == "windows-11-arm":
                self.assertEqual("arm64", job["windows_arch"])
        self.assertEqual(80, len(self.jobs))

    def test_std_matrix_matches_the_independent_report_contract(self):
        jobs = std_matrix()["include"]
        reports = {(j["platform"], j["lane"], j["go_version"], int(j["shard_index"]), int(j["shard_total"])) for j in jobs}
        self.assertEqual(std_native_reports(), reports)
        self.assertEqual(13, len(jobs))

    def test_embedded_hosts_execute_or_build_the_firmware(self):
        jobs = embedded_matrix()["include"]
        self.assertEqual(set(NATIVE_PLATFORMS), {j["platform"] for j in jobs})
        for job in jobs:
            expected = "build-only" if job["platform"] in ("windows-msvc/arm64", "windows-mingw/arm64") else "emulator"
            self.assertEqual(expected, job["mode"])


if __name__ == "__main__":
    unittest.main()
