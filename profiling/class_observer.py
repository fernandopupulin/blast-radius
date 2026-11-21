"""Track class use while running the pinned suite, including pool tasks."""
import atexit
from collections import defaultdict
from functools import wraps
import json
import os
import sys
from pathlib import Path
import shared_fixture_observer
import attribute_observer

active = os.environ.get("BLAST_CLASS_CONTEXT", "")
used = defaultdict(set)
subprocess_tests = set()
enabled = False
reads = defaultdict(set)
shared_reads = defaultdict(set)
ROOT = os.getcwd() + "/"


def audit(event, arguments):
    if not active:
        return
    if event == "subprocess.Popen":
        subprocess_tests.add(active)
    if event != "open" or not isinstance(arguments[0], str):
        return
    path = arguments[0]
    if path.startswith(ROOT):
        path = path[len(ROOT):]
    elif path.startswith("./"):
        path = path[2:]
    if path.startswith("tests/fixtures/"):
        reads[path].add(active)
        frame = sys._getframe(1)
        while frame is not None:
            function = frame.f_code.co_name
            if function in {"setUpClass", "setup_class"}:
                shared_reads[path].add(active.rsplit("::", 1)[0])
                break
            if function in {"setUpModule", "setup_module"}:
                shared_reads[path].add(active.split("::", 1)[0])
                break
            frame = frame.f_back
    elif path.startswith("sqlglot/") and path.endswith(".py"):
        frame = sys._getframe(1)
        for _ in range(8):
            if frame is None:
                break
            if frame.f_code.co_filename in ("<frozen importlib._bootstrap_external>",
                                             "<frozen importlib._bootstrap>"):
                return
            frame = frame.f_back
        reads[path].add(active)


def observe(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        used[active].add(type(self))
        return method(self, *args, **kwargs)
    return call


def enable():
    global enabled
    if enabled:
        return
    enabled = True
    import sys
    from sqlglot.dialects.dialect import Dialect
    from sqlglot.expressions.core import Expr
    from sqlglot.generator import Generator
    from sqlglot.parser import Parser
    from sqlglot.tokens import Tokenizer

    for cls in (Dialect, Expr, Parser, Generator, Tokenizer):
        cls.__init__ = observe(cls.__init__)
    attribute_observer.install((Dialect, Parser, Generator, Tokenizer), lambda: active)

    sys.addaudithook(audit)
    atexit.register(save)


def run_task(test, function, args, kwargs):
    global active
    active = test
    enable()
    return function(*args, **kwargs)


def save():
    contexts = {}
    for test, classes in used.items():
        if not test:
            continue
        symbols = {
            f"{parent.__module__}:{parent.__qualname__}"
            for cls in classes
            for parent in cls.__mro__
            if parent.__module__.startswith("sqlglot.")
        }
        contexts[test] = sorted(symbols)
    result = {
        "tests": contexts,
        "subprocess_tests": sorted(subprocess_tests),
        "reads": {key: sorted(value) for key, value in reads.items()},
        "shared_reads": {key: sorted(value) for key, value in shared_reads.items()},
        "cached_consumers": {
            key: {owner: sorted(tests) for owner, tests in owners.items()}
            for key, owners in shared_fixture_observer.consumers.items()
        },
        "attribute_reads": {
            name: {owner: sorted(tests) for owner, tests in owners.items()}
            for name, owners in attribute_observer.readers.items()
        },
        "shared_attribute_reads": {
            name: {owner: sorted(scopes) for owner, scopes in owners.items()}
            for name, owners in attribute_observer.shared_readers.items()
        },
    }
    Path(f"/profile/results/{os.getpid()}.json").write_text(json.dumps(result), encoding="utf-8")
