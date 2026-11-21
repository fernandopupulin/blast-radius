import ast
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

root, base, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))


def integer_attribute(node):
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not isinstance(target, ast.Name):
        return None
    try:
        value = ast.literal_eval(node.value)
    except (ValueError, TypeError):
        return None
    return target.id if type(value) is int else None


names = set()
for path in (root / "sqlglot" / "dialects").glob("*.py"):
    tree = ast.parse(path.read_bytes())
    for definition in tree.body:
        if isinstance(definition, ast.ClassDef):
            names.update(name for node in definition.body if (name := integer_attribute(node)))

observed = defaultdict(int)
uncertain = set()
for directory in ("sqlglot", "tests"):
    for path in root.joinpath(directory).rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        record = profile["files"].get(rel)
        tree = ast.parse(path.read_bytes())
        for node in ast.walk(tree):
            # Literal name lookup or imports may bypass the tracked attribute reads.
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                uncertain.add(node.value)
            elif isinstance(node, ast.alias) and node.name in names:
                uncertain.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names:
                uncertain.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in names:
                name = node.attr
                if not isinstance(node.ctx, ast.Load) or not record:
                    uncertain.add(name)
                    continue
                lines = [str(n) for n in range(node.lineno, node.end_lineno + 1)]
                scopes = [s for s in record["scopes"] if s[1] <= node.lineno <= s[2]]
                if not scopes or any(node.lineno <= n <= node.end_lineno for n in record["collection"]):
                    uncertain.add(name)
                    continue
                mask = 0
                for line in lines:
                    value = record["lines"].get(line)
                    if value:
                        mask |= int(value, 16)
                if not mask:
                    uncertain.add(name)
                observed[name] |= mask

profile["integer_attribute_readers"] = {
    name: format(mask, "x")
    for name, mask in sorted(observed.items())
    if mask and name not in uncertain
}
output.write_bytes(gzip.compress(json.dumps(profile, separators=(",", ":")).encode(), mtime=0))
print("Eligible attributes and test counts",
      {name: int(mask, 16).bit_count() for name, mask in profile["integer_attribute_readers"].items()})
