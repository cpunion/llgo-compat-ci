"""Require each selected core regression to actually execute successfully."""

import argparse
from collections import Counter
from pathlib import Path


def check_results(log, expected):
    observed = Counter()
    errors = []
    for line in log.splitlines():
        if not line.startswith("GOROOT_CASE_RESULT\t"):
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            errors.append("malformed result: " + line)
            continue
        _, path, _, result = fields
        observed[path] += 1
        if result not in ("pass", "flaky-pass", "unexpected-pass"):
            errors.append(f"{path}: {result}")
    if observed != Counter(expected):
        errors.append(f"case coverage mismatch: expected {list(expected)}, observed {dict(observed)}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()
    errors = check_results(args.log.read_text(), args.expected.split(","))
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
