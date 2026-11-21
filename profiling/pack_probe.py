"""Package the pinned Python sources and the TPC-DS query definitions."""

import gzip
from pathlib import Path
import sys
import tarfile


def main(root, destination):
    root = Path(root)
    files = sorted(root.joinpath("sqlglot").rglob("*.py"))
    files.extend(root / path for path in (
        "tests/__init__.py",
        "tests/helpers.py",
        "tests/fixtures/optimizer/tpc-ds/tpc-ds.sql",
    ))
    with Path(destination).open("wb") as target, gzip.GzipFile(fileobj=target, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|") as archive:
            for path in files:
                info = archive.gettarinfo(str(path), path.relative_to(root).as_posix())
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as file:
                    archive.addfile(info, file)


if __name__ == "__main__":
    main(*sys.argv[1:])
