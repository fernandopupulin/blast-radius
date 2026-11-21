"""Pack source and fixture reads observed on the pinned suite."""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

base, observations, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))
bits = {name: 1 << index for index, name in enumerate(profile["ids"])}
direct = defaultdict(int)
shared = defaultdict(set)
cached = defaultdict(lambda: defaultdict(int))
for file in sorted(observations.glob("*.json")):
    observed = json.loads(file.read_bytes())
    for path, users in observed["reads"].items():
        for user in users:
            direct[path] |= bits.get(user, 0)
    for path, prefixes in observed["shared_reads"].items():
        shared[path].update(prefixes)
    for path, owners in observed["cached_consumers"].items():
        for owner, users in owners.items():
            for user in users:
                cached[path][owner] |= bits.get(user, 0)

reads = dict(direct)
precise = {}
for path, prefixes in shared.items():
    mask = direct[path]
    consumers = direct[path]
    for prefix in sorted(prefixes):
        for test, bit in bits.items():
            if test.startswith(prefix + "::"):
                mask |= bit
        consumers |= cached[path].get(prefix, 0)
    reads[path] = mask
    if all(cached[path].get(prefix, 0) for prefix in prefixes):
        precise[path] = consumers

profile["file_reads"] = {path: format(mask, "x") for path, mask in sorted(reads.items())}
profile["cached_fixture_readers"] = {path: format(mask, "x") for path, mask in sorted(precise.items())}
output.write_bytes(gzip.compress(json.dumps(profile, separators=(",", ":")).encode(), mtime=0))
print(len(reads), "observed file dependencies;", len(precise), "cached SQL pair fixtures")
