"""Track class use while running the pinned suite, including pool tasks."""
import atexit
from collections import defaultdict
from functools import wraps
import json
import os
from pathlib import Path

active = os.environ.get("BLAST_CLASS_CONTEXT", "")
used = defaultdict(set)
subprocess_tests = set()
enabled = False


def audit(event, arguments):
    if event == "subprocess.Popen" and active:
        subprocess_tests.add(active)


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
    result = {"tests": contexts, "subprocess_tests": sorted(subprocess_tests)}
    Path(f"/profile/results/{os.getpid()}.json").write_text(json.dumps(result), encoding="utf-8")
