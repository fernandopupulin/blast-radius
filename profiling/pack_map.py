"""Package measured dependencies and pinned source for the offline selector."""
import ast
import gzip
import json
from pathlib import Path

import coverage

root = Path.cwd()
profile_dir = Path("/profile")
profile = json.loads(gzip.decompress((profile_dir / "impact.json.gz").read_bytes()))
collection = coverage.CoverageData(basename=str(profile_dir / "collection.coverage"))
collection.read()
paths = set(profile["files"]) | set(profile["fixtures"])
profile["sources"] = {}
for file in sorted(paths):
    path = root / file
    if path.is_file():
        try:
            profile["sources"][file] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Binary fixtures fall back to the full suite at selection time.
            continue

for path, record in profile["files"].items():
    parsed = ast.parse(profile["sources"][path])
    scopes = [
        [node.lineno, node.body[0].lineno, node.end_lineno]
        for node in ast.walk(parsed)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    scopes.extend(
        [node.lineno, node.lineno + 1, node.end_lineno]
        for node in ast.walk(parsed)
        if isinstance(node, ast.Lambda) and node.lineno < node.end_lineno
    )
    record["scopes"] = sorted(scopes)
    record["collection"] = sorted(collection.lines(str(root / path)) or ())

packed = json.dumps(profile, separators=(",", ":")).encode()
target = profile_dir / "packed.json.gz"
target.write_bytes(gzip.compress(packed, mtime=0))
print(f"{len(paths)} mapped paths, {target.stat().st_size} bytes")
