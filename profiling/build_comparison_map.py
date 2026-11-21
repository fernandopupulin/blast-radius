"""Add comparison operand type observations from the pinned suite."""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

base, observations, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))
types = defaultdict(set)
for path in sorted(observations.glob("*.json")):
    for site, pairs in json.loads(path.read_bytes()).items():
        types[site].update(tuple(pair) for pair in pairs)
assert types, "No operand types observed"
profile["comparison_operand_types"] = {
    site: sorted(pairs) for site, pairs in sorted(types.items())
}
payload = json.dumps(profile, separators=(",", ":")).encode()
output.write_bytes(gzip.compress(payload, mtime=0))
print(len(types), "comparison sites with observed operand type domains")
