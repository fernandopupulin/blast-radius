"""Observe operand type domains while executing the unmodified SQLGlot suite."""
import ast
import atexit
import enum
from functools import lru_cache
from importlib.machinery import PathFinder, SourceFileLoader
import json
import operator
import os
from pathlib import Path
import sys

OPERATORS = {ast.Is: 0, ast.IsNot: 1, ast.Eq: 2, ast.NotEq: 3}
observed = {}
root = Path.cwd()
probe = "__blast_radius_comparison_profile__"


@lru_cache(maxsize=None)
def type_domain(kind, identity_methods, string_methods):
    if kind is bool:
        return "bool"
    if kind is type(None):
        return "none"
    if identity_methods:
        return "identity"
    if issubclass(kind, enum.Enum) and issubclass(kind, str):
        if string_methods:
            members = list(kind)
            if len({str.__str__(member) for member in members}) == len(members):
                return f"enum:{kind.__module__}:{kind.__qualname__}"
    return "other"


@lru_cache(maxsize=None)
def enum_members(kind):
    return frozenset(map(id, kind.__members__.values()))


def operand_domain(value, kind):
    equality, inequality = kind.__eq__, kind.__ne__
    domain = type_domain(
        kind,
        equality is object.__eq__ and inequality is object.__ne__,
        equality is str.__eq__ and inequality is str.__ne__,
    )
    if domain.startswith("enum:") and id(value) not in enum_members(kind):
        return "other"
    return domain


def compare(site, op, left, right):
    pairs = observed.get(site)
    left_type, right_type = type(left), type(right)
    pair = (operand_domain(left, left_type), operand_domain(right, right_type))
    if left_type is not right_type and pair[0] == pair[1] and pair[0].startswith("enum:"):
        pair = ("other", "other")
    if pairs is None:
        observed[site] = {pair}
    else:
        pairs.add(pair)
    if op == 0:
        return left is right
    if op == 1:
        return left is not right
    return operator.eq(left, right) if op == 2 else operator.ne(left, right)


class Instrument(ast.NodeTransformer):
    def __init__(self, path):
        self.path = path

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) != 1 or type(node.ops[0]) not in OPERATORS:
            return node
        site = f"{self.path}:{node.lineno}:{node.col_offset}"
        return ast.copy_location(ast.Call(
            func=ast.Attribute(value=ast.Name(id=probe, ctx=ast.Load()), attr="compare", ctx=ast.Load()),
            args=[ast.Constant(site), ast.Constant(OPERATORS[type(node.ops[0])]), node.left, node.comparators[0]],
            keywords=[],
        ), node)


class Loader(SourceFileLoader):
    def exec_module(self, module):
        module.__dict__[probe] = sys.modules[__name__]
        return super().exec_module(module)

    def get_code(self, fullname):
        source = self.get_data(self.path)
        tree = ast.parse(source, filename=self.path)
        relative = Path(self.path).relative_to(root).as_posix()
        instrumented = Instrument(relative).visit(tree)
        return compile(ast.fix_missing_locations(instrumented), self.path, "exec", dont_inherit=True)


class Finder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "sqlglot" and not fullname.startswith("sqlglot."):
            return None
        spec = PathFinder.find_spec(fullname, path, target)
        if (spec is not None and isinstance(spec.loader, SourceFileLoader)
                and Path(spec.origin).is_relative_to(root)):
            spec.loader = Loader(fullname, spec.origin)
        return spec


def save():
    domains = {site: sorted(pairs) for site, pairs in sorted(observed.items())}
    Path(f"/profile/results/{os.getpid()}.json").write_text(json.dumps(domains), encoding="utf-8")


def install():
    sys.meta_path.insert(0, Finder())
    atexit.register(save)
