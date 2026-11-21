"""Record truth domains at conditional operands in the pinned suite."""

import ast
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
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


class Instrument(ast.NodeTransformer):
    def __init__(self, path):
        self.path = path

    def visit_If(self, node):
        self.generic_visit(node)
        node.test = self.instrument(node.test, condition=True)
        return node

    visit_While = visit_If

    def visit_Return(self, node):
        self.generic_visit(node)
        node.value = self.instrument(node.value, condition=False)
        return node

    visit_Assign = visit_Return

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) != 1 or type(node.ops[0]) not in COMPARE_OPERATORS:
            return node
        site = f"C{self.path}:{node.lineno}:{node.col_offset}"
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
    data = {"tests": per_test, "outside": sorted(non_boolean | {site for site, _ in outside})}
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
