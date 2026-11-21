"""Merge baseline branch operand domains into the selector's impact map."""

from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys


def main(mapping, traces, output):
    profile = json.loads(gzip.decompress(Path(mapping).read_bytes()))
    bits = {name: 1 << index for index, name in enumerate(profile["ids"])}
    outside = set()
    tests = defaultdict(dict)
    files = sorted(Path(traces).glob("*.json.gz"))
    for path in files:
        observations = json.loads(gzip.decompress(path.read_bytes()))
        outside.update(observations["outside"])
        for test, vectors in observations["tests"].items():
            for site, domain in vectors.items():
                tests[test][site] = tests[test].get(site, 0) | domain
    if len(files) < 2:
        raise ValueError("Missing child process branch observations")
    sites = defaultdict(lambda: defaultdict(int))
    for test, vectors in tests.items():
        bit = bits[test]
        for site, domain in vectors.items():
            if site not in outside:
                sites[site][domain] |= bit
    profile["branch_truth_domains"] = {
        site: [[domain, f"{mask:x}"] for domain, mask in sorted(groups.items())]
        for site, groups in sorted(sites.items()) if not site.startswith("C")
    }
    profile["comparison_relations"] = {
        site[1:]: [[domain, f"{mask:x}"] for domain, mask in sorted(groups.items())]
        for site, groups in sorted(sites.items()) if site.startswith("C")
    }
    data = json.dumps(profile, separators=(",", ":")).encode()
    Path(output).write_bytes(gzip.compress(data, mtime=0))
    print(f"Packed {len(sites)} condition sites from {len(tests)} tests and {len(files)} processes.")


if __name__ == "__main__":
    main(*sys.argv[1:])
