"""Map uses of local module literals on the pinned SQLGlot suite."""
import ast
from collections import defaultdict
import gzip
from importlib.util import resolve_name
import json
from pathlib import Path
import sys

root, base, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))
sources = {
    path.relative_to(root).as_posix(): ast.parse(path.read_bytes())
    for package in ("sqlglot", "tests")
    for path in (root / package).rglob("*.py")
}
symbols = defaultdict(set)
exported = set()
for path, tree in sources.items():
    package = path.removesuffix(".py").replace("/", ".").rpartition(".")[0]
    for statement in ast.walk(tree):
        if isinstance(statement, ast.ImportFrom) and any(alias.name == "*" for alias in statement.names):
            try:
                module = resolve_name("." * statement.level + (statement.module or ""), package)
            except (ImportError, ValueError):
                continue
            exported.add(module.replace(".", "/"))
for path, tree in sources.items():
    if not path.startswith("sqlglot/") or path not in profile["files"]:
        continue
    module_path = path.removesuffix(".py").removesuffix("/__init__")
    if module_path in exported or any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"globals", "vars"} and not node.args and not node.keywords
        for node in ast.walk(tree)
    ):
        continue
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if not isinstance(target, ast.Name) or not target.id.isupper() or node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
        if type(value) in (bool, int, str, tuple, list, dict, set):
            symbols[target.id].add(path)

unsafe = set()
local = defaultdict(int)
for path, tree in sources.items():
    record = profile["files"].get(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in symbols:
            unsafe.add(node.attr)
        elif isinstance(node, ast.alias) and node.name in symbols:
            unsafe.add(node.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in symbols:
            unsafe.add(node.value)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and path in symbols.get(node.id, ()):
            name = node.id
            if not record or not any(start <= node.lineno <= end for _, start, end in record["scopes"]):
                unsafe.add(name)
                continue
            if any(node.lineno <= pos <= node.end_lineno for pos in record["collection"]):
                unsafe.add(name)
                continue
            mask = 0
            for line in range(node.lineno, node.end_lineno + 1):
                if value := record["lines"].get(str(line)):
                    mask |= int(value, 16)
            if not mask:
                unsafe.add(name)
            local[(path, name)] |= mask

combined = defaultdict(dict)
for (path, name), mask in sorted(local.items()):
    if name not in unsafe and mask:
        combined[path][name] = format(mask, "x")
profile["module_literal_readers"] = combined
output.write_bytes(gzip.compress(json.dumps(profile,separators=(",",":")).encode(),mtime=0))
print(sum(map(len, combined.values())), "local module literals with mapped reads")
