"""Record truth domains at conditional operands in the pinned suite."""

import ast
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from functools import lru_cache
from importlib.machinery import PathFinder, SourceFileLoader
from multiprocessing.util import Finalize
import operator
import os
from pathlib import Path
import sys

import pytest

ROOT = Path.cwd()
PROBE = "__blast_radius_branch_profile__"
VALUE_PROBE = "__blast_radius_branch_value_profile__"
COMPARE_PROBE = "__blast_radius_order_profile__"
REGISTER = "__blast_radius_register_table__"
LOOKUP_ESCAPE = "__blast_radius_lookup_escape__"
LOOKUP_PARSER = "__blast_radius_lookup_parser__"
LOOKUP_DISPATCH = "__blast_radius_lookup_dispatch__"
DEFAULT_PROBE = "__blast_radius_bound_default__"
ATTRIBUTE_PROBE = "__blast_radius_attribute_profile__"
LITERAL_PROBE = "__blast_radius_literal_profile__"
ATTRIBUTE_NAMES = frozenset(json.loads(Path("/profile/attributes.json").read_bytes())) if os.environ.get("BLAST_AMBITIOUS") else frozenset()
literal_values = {}
COMPARE_OPERATORS = {
    ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
}
COMPARE_FUNCTIONS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
    "==": operator.eq, "!=": operator.ne,
}
active = set()
per_test = {}
outside = set()
non_boolean = set()
registered = set()
numeric_tables = {}
parser_functions = {}
dispatch_entries = {}
test_context = ""
submit = ProcessPoolExecutor.submit
child_pid = None


def observe(site, operand, value):
    truth = bool(value)
    active.add((site, operand * 2 + int(truth)))
    return truth


def observe_value(site, operand, value):
    if type(value) is bool:
        active.add((site, operand * 2 + int(value)))
    else:
        non_boolean.add(site)
    return value


def compare(site, operation, left, right):
    kind = type(left)
    if kind is type(right) and (
        kind is int or kind is bool or kind is str or kind is bytes or kind is float
    ):
        if left < right:
            active.add((site, 0))
        elif left > right:
            active.add((site, 1))
        elif left == right:
            active.add((site, 2))
        else:
            active.add((site, 3))
    else:
        active.add((site, 4))
    return COMPARE_FUNCTIONS[operation](left, right)


def register(owner, name, keys, table):
    if name in ("TRANSFORMS", "EXPRESSION_METADATA"):
        prefix = "G" if name == "TRANSFORMS" else "T"
        explicit = set(keys)
        for key, value in table.items():
            if isinstance(key, type) and key.__name__ in explicit:
                site = f"{prefix}{owner}|{key.__name__}"
                registered.add(site)
                entry = dispatch_entries.setdefault(id(value), (value, set()))
                entry[1].add(site)
        return table
    registered.add(owner)
    if name == "NUMERIC_ESCAPES":
        numeric_tables[id(table)] = (table, owner)
    else:
        for key in keys:
            value = table[key]
            item = parser_functions.setdefault(id(value), (value, set()))
            item[1].add(f"{owner}:{key}")
    return table


def lookup_escape(table, key):
    value = table.get(key)
    if value is not None and (entry := numeric_tables.get(id(table))):
        active.add((f"{entry[1]}:{key}", 0))
    return value


def lookup_parser(table, key):
    value = table[key]
    if entry := parser_functions.get(id(value)):
        active.update((site, 0) for site in entry[1])
    return value


def lookup_dispatch(table, key, *, indexed=False):
    value = table[key] if indexed else table.get(key)
    if entry := dispatch_entries.get(id(value)):
        active.update((site, 0) for site in entry[1])
    return value


def observe_default(site, bound, default):
    explicit_difference = type(bound) is not type(default) or bound != default
    active.add((site, int(explicit_difference)))


@lru_cache(maxsize=32768)
def lookup_owner(cls, name):
    for base in type.__getattribute__(cls, "__mro__"):
        namespace = type.__getattribute__(base, "__dict__")
        if name in namespace:
            return f"{base.__module__}:{base.__qualname__}"
    return "?"


def observe_attribute(receiver, name):
    value = getattr(receiver, name)
    kind = type(receiver)
    cls = receiver if issubclass(kind, type) else kind
    owner = "?" if kind is super else lookup_owner(cls, name)
    active.add((f"A{name}|{owner}", 0))
    return value


def compare_literal(site, operation, constant_side, left, right):
    value = right if constant_side == "left" else left
    kind = type(value)
    if site not in non_boolean:
        if value is None or kind is bool or (kind is int and value.bit_length() <= 64) or (
            kind is str and len(value) <= 80
        ):
            registry = literal_values.setdefault(site, {})
            key = (kind, value)
            token = registry.get(key)
            if token is None and len(registry) < 128:
                token = site + "|" + json.dumps(value, ensure_ascii=True, separators=(",", ":"))
                registry[key] = token
            if token is not None:
                active.add((token, 0))
            else:
                non_boolean.add(site)
        else:
            non_boolean.add(site)
    return COMPARE_FUNCTIONS[operation](left, right)


def primitive_literal(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (type(None), bool, int, str)
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) is int)


class Instrument(ast.NodeTransformer):
    def __init__(self, path):
        self.path = path
        self.owner = []

    def visit_ClassDef(self, node):
        self.owner.append(node.name)
        self.generic_visit(node)
        for statement in node.body:
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
            elif isinstance(statement, ast.AnnAssign):
                target = statement.target
            else:
                continue
            if not (isinstance(target, ast.Name) and target.id in ("NUMERIC_ESCAPES", "SHOW_PARSERS", "TRANSFORMS")
                    and isinstance(statement.value, ast.Dict)):
                continue
            if target.id == "TRANSFORMS":
                if not ATTRIBUTE_NAMES:
                    continue
                keys = self.expression_keys(statement.value)
                owner = f"{self.path}:{'.'.join(self.owner)}:{target.id}"
            else:
                keys = tuple(key.value for key in statement.value.keys
                             if isinstance(key, ast.Constant) and type(key.value) is str)
                owner = f"R{self.path}:{'.'.join(self.owner)}:{target.id}"
            original = statement.value
            statement.value = self.wrap(REGISTER, original, ast.Constant(owner),
                                        ast.Constant(target.id), ast.Constant(keys), original)
        self.owner.pop()
        return node

    @staticmethod
    def expression_keys(table):
        return tuple(key.attr for key in table.keys if isinstance(key, ast.Attribute)
                     and isinstance(key.value, ast.Name) and key.value.id == "exp")

    @staticmethod
    def wrap(probe, node, *args):
        return ast.copy_location(ast.Call(
            func=ast.Name(id=probe, ctx=ast.Load()), args=list(args), keywords=[]
        ), node)

    def visit_Call(self, node):
        self.generic_visit(node)
        function = node.func
        if (self.path == "sqlglot/tokenizer_core.py" and isinstance(function, ast.Attribute)
                and function.attr == "get" and len(node.args) == 1 and not node.keywords
                and isinstance(function.value, ast.Attribute) and function.value.attr == "numeric_escapes"):
            return self.wrap(LOOKUP_ESCAPE, node, function.value, *node.args)
        if (ATTRIBUTE_NAMES and isinstance(function, ast.Attribute) and function.attr == "get"
                and len(node.args) == 1 and not node.keywords and isinstance(function.value, ast.Attribute)
                and function.value.attr in ("_dispatch", "TRANSFORMS", "expression_metadata")):
            return self.wrap(LOOKUP_DISPATCH, node, function.value, *node.args)
        return node

    def visit_Subscript(self, node):
        self.generic_visit(node)
        if (self.path == "sqlglot/parser.py" and isinstance(node.value, ast.Name)
                and node.value.id == "parsers" and isinstance(node.ctx, ast.Load)):
            return self.wrap(LOOKUP_PARSER, node, node.value, node.slice)
        if (ATTRIBUTE_NAMES and isinstance(node.value, ast.Attribute) and node.value.attr == "TRANSFORMS"
                and isinstance(node.ctx, ast.Load)):
            call = self.wrap(LOOKUP_DISPATCH, node, node.value, node.slice)
            call.keywords.append(ast.keyword(arg="indexed", value=ast.Constant(True)))
            return call
        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.ctx, ast.Load) and node.attr in ATTRIBUTE_NAMES:
            return self.wrap(ATTRIBUTE_PROBE, node, node.value, ast.Constant(node.attr))
        return node

    def visit_If(self, node):
        self.generic_visit(node)
        node.test = self.instrument(node.test, condition=True)
        return node

    visit_While = visit_If

    def visit_Return(self, node):
        self.generic_visit(node)
        node.value = self.instrument(node.value, condition=False)
        return node

    def visit_Assign(self, node):
        self.visit_Return(node)
        if len(node.targets) == 1:
            node.value = self.register_metadata(node.targets[0], node.value)
        return node

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        node.value = self.register_metadata(node.target, node.value)
        return node

    def register_metadata(self, target, value):
        if (ATTRIBUTE_NAMES and self.path.startswith("sqlglot/typing/") and isinstance(target, ast.Name)
                and target.id == "EXPRESSION_METADATA" and isinstance(value, ast.Dict)):
            return self.wrap(REGISTER, value, ast.Constant(self.path), ast.Constant(target.id),
                             ast.Constant(self.expression_keys(value)), value)
        return value

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if any(not isinstance(decorator, ast.Name) or decorator.id not in {"classmethod", "staticmethod"}
               for decorator in node.decorator_list):
            return node
        args = node.args
        positional = (*args.posonlyargs, *args.args)
        candidates = list(zip(positional[len(positional) - len(args.defaults):], args.defaults))
        candidates.extend(zip(args.kwonlyargs, args.kw_defaults))
        probes = []
        for argument, default in candidates:
            if default is None:
                continue
            try:
                baseline = ast.literal_eval(default)
            except (TypeError, ValueError):
                continue
            if type(baseline) not in (bool, int, str):
                continue
            site = f"D{self.path}:{node.lineno}:{node.col_offset}:{argument.arg}"
            probes.append(ast.Expr(self.wrap(DEFAULT_PROBE, node.body[0], ast.Constant(site),
                                            ast.Name(id=argument.arg, ctx=ast.Load()),
                                            ast.Constant(baseline))))
        start = 1 if ast.get_docstring(node) is not None else 0
        for probe in probes:
            ast.copy_location(probe, node.body[min(start, len(node.body) - 1)])
        node.body[start:start] = probes
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Compare(self, node):
        literals = [primitive_literal(node.left), primitive_literal(node.comparators[0])]
        self.generic_visit(node)
        if len(node.ops) != 1 or type(node.ops[0]) not in COMPARE_OPERATORS:
            return node
        site = f"C{self.path}:{node.lineno}:{node.col_offset}"
        if ATTRIBUTE_NAMES and sum(literals) == 1:
            return self.wrap(LITERAL_PROBE, node, ast.Constant("L" + site[1:]),
                             ast.Constant(COMPARE_OPERATORS[type(node.ops[0])]),
                             ast.Constant("left" if literals[0] else "right"),
                             node.left, node.comparators[0])
        return ast.copy_location(ast.Call(
            func=ast.Name(id=COMPARE_PROBE, ctx=ast.Load()),
            args=[ast.Constant(site), ast.Constant(COMPARE_OPERATORS[type(node.ops[0])]),
                  node.left, node.comparators[0]],
            keywords=[],
        ), node)

    def instrument(self, value, *, condition):
        if not isinstance(value, ast.BoolOp):
            return value
        site = f"{self.path}:{value.lineno}:{value.col_offset}"
        probe = PROBE if condition else VALUE_PROBE
        count = 0

        def instrument(expression):
            nonlocal count
            if isinstance(expression, ast.BoolOp):
                expression.values = [instrument(value) for value in expression.values]
                return expression
            if condition and isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
                expression.operand = instrument(expression.operand)
                return expression
            operand = count
            count += 1
            return ast.copy_location(ast.Call(
                func=ast.Name(id=probe, ctx=ast.Load()),
                args=[ast.Constant(site), ast.Constant(operand), expression],
                keywords=[],
            ), expression)

        return instrument(value)


class Loader(SourceFileLoader):
    def exec_module(self, module):
        module.__dict__[PROBE] = observe
        module.__dict__[VALUE_PROBE] = observe_value
        module.__dict__[COMPARE_PROBE] = compare
        module.__dict__[REGISTER] = register
        module.__dict__[LOOKUP_ESCAPE] = lookup_escape
        module.__dict__[LOOKUP_PARSER] = lookup_parser
        module.__dict__[LOOKUP_DISPATCH] = lookup_dispatch
        module.__dict__[DEFAULT_PROBE] = observe_default
        module.__dict__[ATTRIBUTE_PROBE] = observe_attribute
        module.__dict__[LITERAL_PROBE] = compare_literal
        return super().exec_module(module)

    def get_code(self, fullname):
        tree = ast.parse(self.get_data(self.path), filename=self.path)
        path = Path(self.path).relative_to(ROOT).as_posix()
        tree = Instrument(path).visit(tree)
        return compile(ast.fix_missing_locations(tree), self.path, "exec", dont_inherit=True)


class Finder:
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "sqlglot" and not fullname.startswith("sqlglot."):
            return None
        spec = PathFinder.find_spec(fullname, path, target)
        if (spec is not None and isinstance(spec.loader, SourceFileLoader)
                and Path(spec.origin).is_relative_to(ROOT)):
            spec.loader = Loader(fullname, spec.origin)
        return spec


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    global active, test_context
    active = set()
    test_context = item.nodeid
    try:
        return (yield)
    finally:
        update_test(test_context)
        active = outside
        test_context = ""


def update_test(context):
    vectors = per_test.setdefault(context, {})
    for site, bit in active:
        vectors[site] = vectors.get(site, 0) | 1 << bit


def run_task(context, function, args, kwargs):
    global active, child_pid
    if child_pid != os.getpid():
        child_pid = os.getpid()
        per_test.clear()
        Finalize(None, save, exitpriority=1)
    active = set()
    try:
        return function(*args, **kwargs)
    finally:
        update_test(context)
        active = outside


def submit_with_context(pool, function, /, *args, **kwargs):
    if not test_context:
        return submit(pool, function, *args, **kwargs)
    return submit(pool, run_task, test_context, function, args, kwargs)


def pytest_sessionfinish():
    save()


def save():
    path = Path(f"/profile/results/{os.getpid()}.json.gz")
    data = {"tests": per_test, "outside": sorted(non_boolean | {site for site, _ in outside}),
            "registered": sorted(registered)}
    path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))


def install():
    global active
    active = outside
    if not any(isinstance(finder, Finder) for finder in sys.meta_path):
        sys.meta_path.insert(0, Finder())


def main():
    install()
    ProcessPoolExecutor.submit = submit_with_context
    return pytest.main(["tests", "-q", "--tb=short"], plugins=[sys.modules[__name__]])
