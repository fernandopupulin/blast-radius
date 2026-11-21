"""Pack observed inputs and attribute reads from the unmodified suite."""

from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys


def main(mapping, observations, owner_observations, output):
    profile = json.loads(gzip.decompress(Path(mapping).read_bytes()))
    bits = {test: 1 << index for index, test in enumerate(profile["ids"])}
    attributes = defaultdict(lambda: defaultdict(int))
    literals = defaultdict(int)
    table_reads = defaultdict(int)
    registered = set()
    blocked = set()
    paths = sorted(Path(observations).glob("*.json.gz"))
    if len(paths) < 2:
        raise ValueError("Missing baseline subprocess profiles")
    for path in paths:
        data = json.loads(gzip.decompress(path.read_bytes()))
        for item in data["outside"]:
            if item.startswith(("A", "L", "G", "T")):
                blocked.add(item.partition("|")[0] if item.startswith("L") else item)
        registered.update(item for item in data["registered"] if item.startswith(("G", "T")))
        for test, sites in data["tests"].items():
            for item in sites:
                if item.startswith("A"):
                    name, _, owner = item[1:].partition("|")
                    attributes[name][owner] |= bits[test]
                elif item.startswith("L"):
                    literals[item] |= bits[test]
                elif item.startswith(("G", "T")):
                    table_reads[item] |= bits[test]

    exact_sites = {(name, owner) for name, owners in attributes.items() for owner in owners}
    previous = sorted(Path(owner_observations).glob("*.json"))
    if not previous:
        raise ValueError("Missing baseline descriptor reads")
    for path in previous:
        data = json.loads(path.read_bytes())
        for name, owners in data["attribute_reads"].items():
            for owner, tests in owners.items():
                for test in tests:
                    attributes[name][owner] |= bits.get(test, 0)
        for name, owners in data["shared_attribute_reads"].items():
            for owner, scopes in owners.items():
                for scope in scopes:
                    for test, bit in bits.items():
                        if not scope or test.startswith(scope + "::"):
                            attributes[name][owner] |= bit

    replay = defaultdict(list)
    for item, mask in sorted(literals.items()):
        site, _, value = item.partition("|")
        if site not in blocked:
            replay[site[1:]].append((json.loads(value), f"{mask:x}"))
    profile["literal_replay"] = dict(replay)
    profile["exact_table_reads"] = {
        site: f"{table_reads[site]:x}" for site in sorted(registered) if site not in blocked
    }
    profile["exact_attribute_owners"] = {}
    for name, owners in sorted(attributes.items()):
        if f"A{name}|?" in blocked:
            continue
        fallback = owners.get("?", 0) | int(profile["unbound_attribute_readers"].get(name, "0"), 16)
        profile["exact_attribute_owners"][name] = {
            owner: f"{(mask | fallback):x}" for owner, mask in sorted(owners.items())
            if owner != "?" and (name, owner) in exact_sites and f"A{name}|{owner}" not in blocked
        }
    packed = json.dumps(profile, separators=(",", ":")).encode()
    Path(output).write_bytes(gzip.compress(packed, mtime=0))
    print(f"{len(replay)} comparison operand sites, {sum(map(len, profile['exact_attribute_owners'].values()))} "
          f"attribute owners, and {len(profile['exact_table_reads'])} dispatch entries")


if __name__ == "__main__":
    main(*sys.argv[1:])
