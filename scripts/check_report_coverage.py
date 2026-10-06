"""Check the compatibility coverage contract independently of job totals."""

import argparse
import csv
import json
import math
from collections import defaultdict
from fractions import Fraction
from pathlib import Path


NATIVE_PLATFORMS = (
    "darwin/arm64",
    "linux/amd64",
    "windows-msvc/amd64",
    "windows-msvc/arm64",
    "windows-msvc/386",
    "windows-mingw/amd64",
    "windows-mingw/arm64",
    "windows-mingw/386",
)
GOROOT_PLATFORMS = (*NATIVE_PLATFORMS, "js/wasm")
WASM_SHARDS = {
    "J32-GoJS": 3,
    "J32-Emscripten": 3,
    "J64-Emscripten": 3,
    "W32-WASI": 5,
}


def check_partition(shards):
    """Case-index residues must be disjoint and cover the entire corpus."""
    for index, total in shards:
        if total <= 0 or not 0 <= index < total:
            return f"invalid shard {index}/{total}"
    for pos, (index, total) in enumerate(shards):
        for other_index, other_total in shards[:pos]:
            # Two congruence classes intersect exactly when their residues
            # agree modulo the gcd, including mixed 8/16/32/64 partitions.
            if (index - other_index) % math.gcd(total, other_total) == 0:
                return f"overlapping shards {other_index}/{other_total} and {index}/{total}"
    coverage = sum((Fraction(1, total) for _, total in shards), Fraction())
    if coverage != 1:
        return f"corpus coverage is {coverage}, expected 1"
    return None


def check_goroot(summary, versions):
    groups = defaultdict(list)
    errors = []
    expected = {(platform, version) for platform in GOROOT_PLATFORMS for version in versions}
    with Path(summary).open() as stream:
        for line, row in enumerate(csv.reader(stream, delimiter="\t"), 1):
            try:
                if len(row) != 9:
                    raise ValueError("expected nine TSV columns, including shard total")
                platform, version = row[:2]
                index, selected, observed, passed, failed, skipped, total = map(int, row[2:])
                key = (platform, version)
                if key not in expected:
                    raise ValueError(f"unexpected platform/version {platform} Go {version}")
                groups[key].append((index, total))
                if min(selected, observed, passed, failed, skipped) < 0:
                    raise ValueError("negative case count")
                if selected != observed or observed != passed + failed + skipped:
                    raise ValueError(f"incomplete case results: selected={selected}, observed={observed}")
            except ValueError as error:
                errors.append(f"GOROOT report line {line}: {error}")
    for platform, version in sorted(expected):
        error = check_partition(groups[platform, version])
        if error:
            errors.append(f"{platform} · Go {version}: {error}")
    return errors, f"{len(GOROOT_PLATFORMS)} platforms × {len(versions)} Go versions"


def std_native_reports():
    expected = {("linux/amd64", "compatibility", "1.20-1.26", 0, 1)}
    for platform in NATIVE_PLATFORMS:
        total = 2 if platform in ("linux/amd64", "windows-msvc/arm64") else 1
        expected.update((platform, "full", "1.27", index, total) for index in range(total))
    return expected


def check_std(native_dir, wasm_dir):
    errors = []
    expected_native = std_native_reports()
    native = set()
    for path in sorted(Path(native_dir).rglob("summary-*.tsv")):
        for row in csv.reader(path.read_text().splitlines(), delimiter="\t"):
            try:
                if len(row) != 6:
                    raise ValueError("expected six native TSV columns")
                key = (*row[:3], int(row[3]), int(row[4]))
                if key not in expected_native:
                    raise ValueError(f"unexpected native report {key}")
                if key in native:
                    raise ValueError(f"duplicate native report {key}")
                native.add(key)
            except ValueError as error:
                errors.append(f"{path.name}: {error}")
    for platform, lane, version, index, total in sorted(expected_native - native):
        errors.append(f"missing native report: {platform} · {lane} · Go {version} · {index}/{total}")

    expected_wasm = {(profile, index, total) for profile, total in WASM_SHARDS.items() for index in range(total)}
    wasm = set()
    for path in sorted(Path(wasm_dir).rglob("acceptance.json")):
        try:
            report = json.loads(path.read_text())
            key = (report["profile"], report["shard"], report["shards"])
            if key not in expected_wasm:
                raise ValueError(f"unexpected Wasm report {key}")
            if key in wasm:
                raise ValueError(f"duplicate Wasm report {key}")
            wasm.add(key)
        except (ValueError, KeyError, TypeError) as error:
            errors.append(f"{path.parent.name}/{path.name}: {error}")
    for profile, index, total in sorted(expected_wasm - wasm):
        errors.append(f"missing Wasm report: {profile} · {index}/{total}")
    return errors, f"native reports {len(native)}/{len(expected_native)}, Wasm reports {len(wasm)}/{len(expected_wasm)}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="suite", required=True)
    goroot = subparsers.add_parser("goroot")
    goroot.add_argument("--summary", required=True)
    goroot.add_argument("--versions", required=True)
    std = subparsers.add_parser("std")
    std.add_argument("--native-reports", required=True)
    std.add_argument("--wasm-reports", required=True)
    args = parser.parse_args()
    if args.suite == "goroot":
        versions = args.versions.split(",")
        if len(versions) != 2 or len(set(versions)) != 2:
            parser.error("GOROOT requires two distinct Go versions")
        errors, description = check_goroot(args.summary, versions)
    else:
        errors, description = check_std(args.native_reports, args.wasm_reports)
    print(f"Coverage: {'❌ incomplete' if errors else '✅ complete'} ({description}).")
    print()
    if errors:
        print("> [!WARNING]\n> Compatibility coverage is incomplete; missing reports are not passing tests.\n")
        for error in errors:
            print(f"- {error}")
        print()
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
