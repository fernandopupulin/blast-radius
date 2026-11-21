"""Combine observed class usage with Python references from the pinned checkout."""
import ast
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

base, runs, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))
bits = {test: 1 << idx for idx, test in enumerate(profile["ids"])}
classes = defaultdict(int)
subprocesses = 0
for file in sorted(runs.glob("*.json")):
    data = json.loads(file.read_bytes())
    for test, symbols in data["tests"].items():
        for symbol in symbols:
            classes[symbol] |= bits.get(test, 0)
    for test in data["subprocess_tests"]:
        subprocesses |= bits.get(test, 0)
assert classes, "No class observations"

observed_names = {key.partition(":")[2].split(".")[0] for key in classes}
references = defaultdict(int)
for filename, record in profile["files"].items():
    source = profile["sources"][filename]
    tree = ast.parse(source, filename)
    identity_references = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            identity_references.update(key for key in node.keys if isinstance(key, (ast.Name, ast.Attribute)))
        elif isinstance(node, ast.arg) and isinstance(node.annotation, (ast.Name, ast.Attribute)):
            identity_references.add(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and isinstance(node.returns, (ast.Name, ast.Attribute)):
            identity_references.add(node.returns)
    for node in ast.walk(tree):
        # Merely storing a class as a key or annotating with it does not read
        # the configuration values on that class.
        if node in identity_references:
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            name = node.id
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            name = node.attr
        else:
            continue
        if name not in observed_names:
            continue
        for line in range(node.lineno, node.end_lineno + 1):
            value = record["lines"].get(str(line))
            if value:
                references[name] |= int(value, 16)

profile["class_users"] = {
    key: format(mask | references[key.partition(":")[2].split(".")[0]], "x")
    for key, mask in sorted(classes.items())
    if mask
}
profile["subprocess_users"] = format(subprocesses, "x")
output.write_bytes(gzip.compress(json.dumps(profile, separators=(",", ":")).encode(), mtime=0))
print(len(profile["class_users"]), "observed classes from", len(list(runs.glob("*.json"))), "processes")
