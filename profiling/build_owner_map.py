"""Pack the observed owner of runtime attribute reads on the pinned suite."""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

base, observations, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))
bits = {test: 1 << idx for idx, test in enumerate(profile["ids"])}
reads = defaultdict(lambda: defaultdict(int))
direct = defaultdict(int)
for path in sorted(observations.glob("*.json")):
    seen = json.loads(path.read_bytes())
    for name, owners in seen["attribute_reads"].items():
        for owner, tests in owners.items():
            for test in tests:
                bit = bits.get(test, 0)
                reads[name][owner] |= bit
                direct[name] |= bit
    for name, owners in seen["shared_attribute_reads"].items():
        for owner, scopes in owners.items():
            for scope in scopes:
                for test, bit in bits.items():
                    if not scope or test.startswith(scope + "::"):
                        reads[name][owner] |= bit

profile["attribute_owners"] = {}
for name, owners in sorted(reads.items()):
    if name not in profile["scalar_attribute_readers"]:
        continue
    unassigned = int(profile["scalar_attribute_readers"][name], 16) & ~direct[name]
    unassigned |= int(profile["unbound_attribute_readers"][name], 16)
    profile["attribute_owners"][name] = {
        owner: format(mask | unassigned, "x") for owner, mask in sorted(owners.items()) if mask
    }

payload = json.dumps(profile, separators=(",", ":")).encode()
output.write_bytes(gzip.compress(payload, mtime=0))
print(len(profile["attribute_owners"]), "attributes with observed owners")
