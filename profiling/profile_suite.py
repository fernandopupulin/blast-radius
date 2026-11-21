import ast
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
import os
from pathlib import Path
import sys

import coverage
import pytest
from sitecustomize import run_task

ROOT = Path.cwd()
FIXTURES = ROOT / "tests" / "fixtures"
fixture_users = defaultdict(set)
collected = set()
active = None
cov = coverage.Coverage(source=["sqlglot", "tests"], data_file=None)
submit = ProcessPoolExecutor.submit


def submit_with_context(pool, function, /, *args, **kwargs):
    return submit(pool, run_task, active or "", function, args, kwargs)


def track_fixture(event, arguments):
    if event != "open" or not isinstance(arguments[0], str):
        return
    path = Path(arguments[0])
    if "fixtures" not in path.parts:
        return
    if not path.is_absolute():
        path = ROOT / path
    if path.is_relative_to(FIXTURES):
        fixture_users[path.relative_to(ROOT).as_posix()].add(active)


class Profile:
    def pytest_collection_finish(self, session):
        collected.update(item.nodeid for item in session.items)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(self, item):
        global active
        active = item.nodeid
        os.environ["BLAST_TEST_CONTEXT"] = active
        cov.switch_context(active)
        try:
            return (yield)
        finally:
            os.environ.pop("BLAST_TEST_CONTEXT", None)
            active = None
            cov.switch_context("")


def encode(ids, index):
    mask = sum(1 << index[test] for test in set(ids) if test in index)
    return format(mask, "x") if mask else ""


def main():
    sys.addaudithook(track_fixture)
    ProcessPoolExecutor.submit = submit_with_context
    cov.start()
    try:
        status = pytest.main(["tests", "-q", "--tb=short"], plugins=[Profile()])
    finally:
        ProcessPoolExecutor.submit = submit
        cov.stop()
    if status:
        raise SystemExit(status)

    ids = sorted(collected)
    index = {test: i for i, test in enumerate(ids)}
    files = {}
    data = cov.get_data()
    for path in sorted(Path("/profile/children").glob("coverage.*")):
        child = coverage.CoverageData(basename=str(path))
        child.read()
        data.update(child)
    for name in sorted(data.measured_files()):
        path = Path(name)
        if not path.is_relative_to(ROOT):
            continue
        lines = data.contexts_by_lineno(name)
        scopes = [
            [min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno]
            for node in ast.walk(ast.parse(path.read_bytes()))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        files[path.relative_to(ROOT).as_posix()] = {
            "lines": {line: encode(tests, index) for line, tests in lines.items()},
            "scopes": sorted(scopes),
        }

    payload = {
        "ids": ids,
        "files": files,
        "fixtures": {
            path: encode(users, index)
            for path, users in sorted(fixture_users.items())
            if None not in users
        },
    }
    output = json.dumps(payload, separators=(",", ":")).encode()
    Path("/profile/impact.json.gz").write_bytes(gzip.compress(output, mtime=0))
    print(f"{len(ids)} tests, {len(files)} source files, {len(payload['fixtures'])} fixture paths")


if __name__ == "__main__":
    main()
