"""Pack source and fixture reads observed on the pinned suite."""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

base, observations, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))
bits = {name: 1 << index for index, name in enumerate(profile["ids"])}
reads = defaultdict(int)
for file in sorted(observations.glob("*.json")):
    observed = json.loads(file.read_bytes())
    for path, users in observed["reads"].items():
        for user in users:
            reads[path] |= bits.get(user, 0)
    for path, prefixes in observed["shared_reads"].items():
        for prefix in prefixes:
            for test, bit in bits.items():
                if test.startswith(prefix + "::"):
                    reads[path] |= bit
profile["file_reads"] = {path: format(mask, "x") for path, mask in sorted(reads.items())}
output.write_bytes(gzip.compress(json.dumps(profile, separators=(",", ":")).encode(), mtime=0))
print(len(reads), "observed file dependencies")
