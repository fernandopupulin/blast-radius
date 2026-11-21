"""Attach observed test-context file coverage from fresh Python interpreters."""

from collections import defaultdict
import gzip
import json
from pathlib import Path, PurePosixPath
import sqlite3
import sys


def main(mapping, children, output):
    profile = json.loads(gzip.decompress(Path(mapping).read_bytes()))
    subprocesses = int(profile["subprocess_users"], 16)
    contexts = {
        test: 1 << index for index, test in enumerate(profile["ids"]) if subprocesses & (1 << index)
    }
    observed = defaultdict(set)
    for path in Path(children).glob("coverage.*"):
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as database:
            for context, filename in database.execute("""
                SELECT context.context, file.path FROM line_bits
                JOIN context ON line_bits.context_id = context.id
                JOIN file ON line_bits.file_id = file.id
            """):
                if context in contexts and filename.startswith("/src/"):
                    observed[context].add(PurePosixPath(filename).relative_to("/src").as_posix())
    files = defaultdict(int)
    traced = 0
    for test, paths in observed.items():
        if "sqlglot/__init__.py" in paths:
            bit = contexts[test]
            traced |= bit
            paths.add(test.partition("::")[0])
            for path in paths:
                files[path] |= bit
    profile["subprocess_traced"] = f"{traced:x}"
    profile["subprocess_files"] = {path: f"{mask:x}" for path, mask in sorted(files.items())}
    data = json.dumps(profile, separators=(",", ":")).encode()
    Path(output).write_bytes(gzip.compress(data, mtime=0))
    print(f"Traced {traced.bit_count()} subprocess tests and {len(files)} distinct files.")


if __name__ == "__main__":
    main(*sys.argv[1:])
