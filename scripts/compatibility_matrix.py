"""Generate compatibility jobs from the supported native host profiles."""

import argparse
import json


HOSTS = (
    ("darwin/arm64", "macos-latest", "", ""),
    ("darwin/amd64", "macos-15-intel", "", ""),
    ("linux/amd64", "ubuntu-latest", "", ""),
    ("linux/arm64", "ubuntu-24.04-arm", "", ""),
    ("windows-msvc/amd64", "windows-2022", "msvc", "amd64"),
    ("windows-mingw/amd64", "windows-2022", "mingw", "amd64"),
    ("windows-msvc/386", "windows-2022", "msvc", "386"),
    ("windows-mingw/386", "windows-2022", "mingw", "386"),
    ("windows-msvc/arm64", "windows-11-arm", "msvc", "arm64"),
    ("windows-mingw/arm64", "windows-11-arm", "mingw", "arm64"),
)


def host_jobs():
    return [dict(platform=p, os=os, windows_abi=abi, windows_arch=arch)
            for p, os, abi, arch in HOSTS]


def native_matrix():
    return {"include": [{
        **host,
        "shard-index": str(index),
        "shard-total": "8",
        "paired-shard-index": str((index + 4) % 8),
    } for host in host_jobs() for index in range(8)]}


def std_matrix():
    jobs = []
    for host in host_jobs():
        platform = host["platform"]
        total = 2 if platform in ("linux/amd64", "windows-msvc/arm64") else 1
        common = dict(**host, llvm=22, lane="full", go_version="1.27",
                      host_go_arch="arm64" if host["windows_arch"] == "arm64" else "x64" if host["windows_arch"] else "",
                      check_symbols=platform == "linux/amd64", std_buildmodes=platform == "linux/amd64")
        jobs.extend(dict(**common, shard_index=str(i), shard_total=str(total)) for i in range(total))
        if platform == "linux/amd64":
            jobs.append(dict(common, lane="compatibility", go_version="1.20-1.26",
                             shard_index="0", shard_total="1", std_buildmodes=False))
    return {"include": jobs}


def embedded_matrix():
    return {"include": [dict(**host, mode="build-only" if host["os"] == "windows-11-arm" else "emulator")
                        for host in host_jobs()]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=("goroot", "std", "embedded"))
    suite = parser.parse_args().suite
    matrix = {"goroot": native_matrix, "std": std_matrix, "embedded": embedded_matrix}[suite]()
    print(json.dumps(matrix, separators=(",", ":")))
