"""Observe consumers of SQL pairs cached during unittest class setup."""
import ast
from collections import defaultdict
from functools import wraps
import inspect
import textwrap

consumers = defaultdict(lambda: defaultdict(set))
installed = set()


def cached_pairs(cls):
    setup = getattr(cls, "setUpClass", None)
    if not setup or setup.__module__ != cls.__module__:
        return {}
    namespace = getattr(getattr(setup, "__func__", setup), "__globals__", {})
    factory = namespace.get("load_sql_fixture_pairs")
    if getattr(factory, "__module__", "") != "tests.helpers" or "list" in namespace:
        return {}
    try:
        function = ast.parse(textwrap.dedent(inspect.getsource(setup))).body[0]
        module = ast.parse(inspect.getsource(inspect.getmodule(cls)))
    except (OSError, SyntaxError, TypeError):
        return {}
    owner = function.args.args[0].arg
    result = {}
    for node in function.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == owner and isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name) and value.func.id == "list"
                and len(value.args) == 1 and not value.keywords):
            continue
        call = value.args[0]
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                and call.func.id == "load_sql_fixture_pairs"
                and len(call.args) == 1 and not call.keywords):
            continue
        path = call.args[0]
        if not (isinstance(path, ast.Constant) and isinstance(path.value, str)):
            continue
        field = target.attr
        if any(
            (isinstance(ref, ast.Constant) and ref.value == field)
            or (isinstance(ref, ast.Attribute) and isinstance(ref.ctx, ast.Load)
                and ref.attr == field and
                (not isinstance(ref.value, ast.Name) or ref.value.id != "self"))
            for ref in ast.walk(module)
        ):
            continue
        result[field] = "tests/fixtures/" + path.value
    return result


def install(items, active):
    for item in items:
        cls = item.cls
        if cls is None or cls in installed:
            continue
        installed.add(cls)
        fields = cached_pairs(cls)
        if not fields:
            continue
        owner = item.nodeid.rsplit("::", 1)[0]
        instrument(cls, fields, owner, active)


def instrument(cls, fields, owner, active):
    original = cls.__getattribute__

    @wraps(original)
    def read(self, name):
        if path := fields.get(name):
            if test := active():
                consumers[path][owner].add(test)
        return original(self, name)

    cls.__getattribute__ = read
