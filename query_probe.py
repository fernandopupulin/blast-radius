"""Compare SQLGlot's optimizer output at the boundary of the executor."""

import enum
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import pickle
import signal
import sys


FIXTURE = "optimizer/tpc-ds/tpc-ds.sql"


def digest(root):
    from sqlglot import exp

    objects = [root]
    numbers = {id(root): 0}
    records = []

    def encode(value):
        kind = type(value)
        if kind is None.__class__ or kind is bool or kind is int or kind is str:
            return ["scalar", value]
        if kind is float:
            return ["float", value.hex()]
        if isinstance(value, enum.Enum):
            return ["member", kind.__module__, kind.__qualname__, value.name]
        index = numbers.get(id(value))
        if index is None:
            index = len(objects)
            numbers[id(value)] = index
            objects.append(value)
        return ["object", index]

    for item in objects:
        kind = type(item)
        if isinstance(item, exp.Expr):
            slots = {field for cls in kind.__mro__ for field in vars(cls).get("__slots__", ())}
            slots -= {"__weakref__", "__dict__"}
            if slots != {"args", "parent", "arg_key", "index", "comments", "_type", "_meta", "_hash"}:
                raise ValueError("Unknown expression storage")
            if getattr(item, "__dict__", None):
                raise ValueError("Unexpected expression attributes")
            records.append([kind.__module__, kind.__qualname__,
                            [(key, encode(getattr(item, key, None))) for key in sorted(slots)]])
        elif kind is dict:
            records.append(["dict", [(encode(key), encode(value)) for key, value in item.items()]])
        elif kind is list or kind is tuple:
            records.append([kind.__name__, [encode(value) for value in item]])
        else:
            raise ValueError("Unknown optimizer value")
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


class Overlay(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, root, path, source):
        self.path = root / path
        self.module = path.removesuffix(".py").replace("/", ".")
        self.source = source
        self.loaded = False

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.module:
            return importlib.util.spec_from_file_location(fullname, self.path, loader=self)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        self.loaded = True
        exec(compile(self.source, str(self.path), "exec", dont_inherit=True), vars(module))


def main():
    request = json.load(sys.stdin)
    signal.setitimer(signal.ITIMER_PROF, request["cpu_limit"])
    root = Path("/upstream")
    sys.path.insert(0, str(root))
    overlay = Overlay(root, request["path"], request["source"])
    sys.meta_path.insert(0, overlay)

    from sqlglot import parse_one
    from sqlglot.optimizer import optimize
    from sqlglot.schema import ensure_schema
    from tests.helpers import TPCDS_SCHEMA, load_sql_fixture_pairs

    queries = list(load_sql_fixture_pairs(FIXTURE))
    schema = ensure_schema(TPCDS_SCHEMA)
    for index, expected in request["queries"]:
        options, sql, _ = queries[index]
        if not options.get("execute"):
            return
        expression = pickle.loads(pickle.dumps(parse_one(sql)))
        result = optimize(expression, schema, leave_tables_isolated=True, dialect=None)
        if digest(result) != expected:
            return
    if overlay.loaded:
        print("verified", flush=True)


if __name__ == "__main__":
    main()
