"""Select tests using observations from the pinned SQLGlot suite."""

import ast
import gzip
import json
import math
from pathlib import Path
import re

DATA = Path("/data")
MAP = Path(__file__).with_name("impact.json.gz")
FILE = re.compile(r"diff --git a/([^\s]+) b/([^\s]+)")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@.*")


def partition(tests):
    if not tests:
        return []
    ordered = sorted(tests, key=lambda test: (-test[1], test[0]))
    minimum = (math.inf, [])
    total = sum(duration for _, duration in ordered)
    for count in range(1, min(8, len(ordered)) + 1):
        lower = max(ordered[0][1], (total + count - 1) // count) + 2000 * count
        if lower >= minimum[0]:
            continue
        loads = [0] * count
        groups = [[] for _ in loads]
        for index, (number, duration) in enumerate(ordered):
            worker = index if index < count else loads.index(min(loads))
            groups[worker].append(number)
            loads[worker] += duration
        cost = max(loads) + 2000 * count
        if cost < minimum[0]:
            minimum = (cost, groups)
    return minimum[1]


def sections(patch):
    files = {}
    path = None
    for line in patch.removesuffix("\n").split("\n"):
        if line.startswith("diff --git "):
            match = FILE.fullmatch(line)
            if not match or match[1] != match[2] or match[1] in files:
                raise ValueError("unsupported file header")
            path = match[1]
            files[path] = []
        elif path is None:
            raise ValueError("missing file header")
        else:
            files[path].append(line)
    if not files:
        raise ValueError("empty patch")
    return files


def apply_section(path, lines, original):
    if lines and lines[0].startswith("index "):
        lines = lines[1:]
    if lines[:2] != [f"--- a/{path}", f"+++ b/{path}"]:
        raise ValueError("unsupported file change")
    lines = lines[2:]
    updated = []
    changed = set()
    inserted = set()
    cursor = 0
    index = 0
    while index < len(lines):
        header = HUNK.fullmatch(lines[index])
        if not header:
            raise ValueError("invalid hunk")
        old_count, new_count = (int(header[i] or "1") for i in (2, 3))
        start = int(header[1]) - bool(old_count)
        if not cursor <= start <= len(original):
            raise ValueError("hunk outside source")
        updated.extend(original[cursor:start])
        cursor = start
        index += 1
        old_seen = new_seen = 0
        while index < len(lines) and not lines[index].startswith("@@ "):
            entry = lines[index]
            tag, content = entry[:1], entry[1:]
            if tag in (" ", "-"):
                if cursor >= len(original) or original[cursor] != content:
                    raise ValueError("patch differs from pinned source")
                cursor += 1
                old_seen += 1
            if tag in (" ", "+"):
                updated.append(content)
                new_seen += 1
            if tag == "-":
                changed.add(cursor)
            elif tag == "+":
                inserted.add(cursor)
            elif tag != " ":
                raise ValueError("unsupported hunk line")
            index += 1
        if (old_seen, new_seen) != (old_count, new_count):
            raise ValueError("inconsistent hunk lengths")
    updated.extend(original[cursor:])
    if not changed and not inserted:
        raise ValueError("no textual changes")
    return "\n".join(updated) + "\n", changed, inserted


def module_structure(tree):
    """Keep definitions and import-time statements, and omit function bodies."""
    class StripBodies(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            node.body = []
            return node

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            if node.lineno < node.end_lineno:
                node.body = ast.Constant(None)
            return node

    return ast.dump(StripBodies().visit(tree))


def literal_shape(value, depth=0):
    kind = type(value)
    if kind in (bool, int, type(None)):
        return kind
    if kind is str and len(value) <= 120 and (not value or value.isprintable()):
        return kind
    if depth >= 4:
        raise ValueError("nested configuration value")
    if kind in (tuple, list) and len(value) <= 64:
        return kind, tuple(literal_shape(item, depth + 1) for item in value)
    if kind is dict and len(value) <= 64 and all(type(key) is str for key in value):
        return kind, tuple((key, literal_shape(item, depth + 1)) for key, item in value.items())
    raise ValueError("unrecognized configuration value")


def configuration_on_line(body, line):
    for definition in body:
        if not isinstance(definition, ast.ClassDef) or not definition.lineno <= line <= definition.end_lineno:
            continue
        for node in definition.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
            elif isinstance(node, ast.AnnAssign):
                target = node.target
            else:
                continue
            if isinstance(target, ast.Name) and node.value is not None and node.lineno <= line <= node.end_lineno:
                yield node, target.id
        yield from configuration_on_line(definition.body, line)


def changed_attribute(path, line, before, after, profile):
    if not path.startswith(("sqlglot/dialects/", "sqlglot/parsers/", "sqlglot/generators/")):
        return 0
    old_matches = list(configuration_on_line(before.body, line))
    new_matches = list(configuration_on_line(after.body, line))
    if len(old_matches) != 1 or len(new_matches) != 1:
        return 0
    (old, name), = old_matches
    (new, new_name), = new_matches
    readers = profile["scalar_attribute_readers"]
    if name != new_name or name not in readers:
        return 0
    try:
        if literal_shape(ast.literal_eval(old.value)) != literal_shape(ast.literal_eval(new.value)):
            return 0
    except (ValueError, TypeError):
        return 0
    previous = new.value
    try:
        new.value = old.value
        if ast.dump(before) == ast.dump(after):
            module = path.removesuffix(".py").replace("/", ".")
            owner = enclosing_class(before.body, line)
            if exact := profile.get("attribute_owners", {}).get(name, {}).get(f"{module}:{owner}"):
                return int(exact, 16)
            return int(readers[name], 16)
    finally:
        new.value = previous
    return 0


def expression_on_line(tree, line):
    matches = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            field = "test"
        elif isinstance(node, (ast.Assign, ast.Return)):
            field = "value"
        else:
            continue
        expression = getattr(node, field)
        if expression is not None and node.lineno <= line <= expression.end_lineno:
            matches.append((node, field, expression))
    return matches


def isolated_expression_change(before, after, line):
    old = expression_on_line(before, line)
    new = expression_on_line(after, line)
    if len(old) != 1 or len(new) != 1:
        return False
    _, old_field, old_value = old[0]
    node, field, value = new[0]
    if field != old_field:
        return False
    if any(isinstance(part, (ast.NamedExpr, ast.Yield, ast.YieldFrom, ast.Await,
                             ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp))
           for expression in (old_value, value) for part in ast.walk(expression)):
        return False
    try:
        setattr(node, field, old_value)
        if ast.dump(before) == ast.dump(after):
            return range(old[0][0].lineno, old_value.end_lineno + 1)
    finally:
        setattr(node, field, value)


def defaults_on_line(tree, line):
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(not isinstance(decorator, ast.Name) or decorator.id not in {"classmethod", "staticmethod"}
               for decorator in node.decorator_list):
            continue
        for defaults in (node.args.defaults, node.args.kw_defaults):
            for index, default in enumerate(defaults):
                if default is not None and default.lineno == default.end_lineno == line:
                    yield node, defaults, index


def default_value_readers(before, after, line, record, reflection):
    if reflection is None:
        return 0
    old = list(defaults_on_line(before, line))
    new = list(defaults_on_line(after, line))
    if len(old) != 1 or len(new) != 1:
        return 0
    function, old_values, index = old[0]
    _, new_values, new_index = new[0]
    try:
        original = ast.literal_eval(old_values[index])
        replacement = ast.literal_eval(new_values[new_index])
    except (TypeError, ValueError):
        return 0
    if type(original) not in (bool, int, str) or type(original) is not type(replacement):
        return 0
    saved = new_values[new_index]
    try:
        new_values[new_index] = old_values[index]
        if ast.dump(before) != ast.dump(after):
            return 0
    finally:
        new_values[new_index] = saved
    start = function.body[0].lineno
    if any(start <= number <= function.end_lineno for number in record["collection"]):
        return 0
    observed = 0
    for number in range(start, function.end_lineno + 1):
        if mask := record["lines"].get(str(number)):
            observed |= int(mask, 16)
    return (observed | int(reflection, 16)) if observed else 0


def enclosing_class(body, line, owner=()):
    for node in body:
        if isinstance(node, ast.ClassDef) and node.lineno <= line <= node.end_lineno:
            qualified = (*owner, node.name)
            return enclosing_class(node.body, line, qualified)
    return ".".join(owner)


def class_dict_entries(body, line, owner=()):
    for definition in body:
        if not isinstance(definition, ast.ClassDef):
            continue
        if not definition.lineno <= line <= definition.end_lineno:
            continue
        qualified = (*owner, definition.name)
        for node in definition.body:
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Dict)
            ):
                continue
            for index, (key, value) in enumerate(zip(node.value.keys, node.value.values)):
                if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                        and key.lineno <= line <= value.end_lineno):
                    yield ".".join(qualified), node.targets[0].id, key.value, node.value, index
        yield from class_dict_entries(definition.body, line, qualified)


def numeric_escape(value):
    try:
        fields = ast.literal_eval(value)
    except (TypeError, ValueError):
        return False
    if not (isinstance(fields, tuple) and len(fields) == 4
            and all(type(field) is int for field in fields)):
        return False
    radix, minimum, maximum, cap = fields
    return 2 <= radix <= 36 and 1 <= minimum <= maximum <= 16 and 0 <= cap <= 0x10FFFF


def show_factory(value):
    if not isinstance(value, ast.Call):
        return None
    if not (isinstance(value.func, ast.Name) and value.func.id == "_show_parser"
            and len(value.args) == len(value.keywords) == 1):
        return None
    item, = value.args
    switch, = value.keywords
    if (isinstance(item, ast.Constant) and isinstance(item.value, str)
            and switch.arg == "target" and isinstance(switch.value, ast.Constant)
            and type(switch.value.value) is bool):
        return item.value
    return None


def class_config_change(path, line, before, after, profile):
    old_entries = {entry[:3]: entry[3:] for entry in class_dict_entries(before.body, line)}
    new_entries = {entry[:3]: entry[3:] for entry in class_dict_entries(after.body, line)}
    if old_entries.keys() != new_entries.keys():
        return 0
    updates = []
    for key, (old, old_index) in old_entries.items():
        new, new_index = new_entries[key]
        if ast.dump(old.values[old_index]) != ast.dump(new.values[new_index]):
            updates.append((key, old.values[old_index], new, new_index))
    if len(updates) != 1:
        return 0
    (owner, attribute, _), old_value, new, new_index = updates[0]
    new_value = new.values[new_index]
    if attribute == "arg_types" and path.startswith("sqlglot/expressions/"):
        valid = all(isinstance(node, ast.Constant) and type(node.value) is bool
                    for node in (old_value, new_value))
    elif attribute == "NUMERIC_ESCAPES" and path.startswith("sqlglot/dialects/"):
        valid = numeric_escape(old_value) and numeric_escape(new_value)
    elif attribute == "SHOW_PARSERS" and path.startswith("sqlglot/parsers/"):
        valid = show_factory(old_value) is not None and show_factory(new_value) is not None
    else:
        return 0
    if not valid:
        return 0
    module = path.removesuffix(".py").replace("/", ".")
    observed = profile["class_users"].get(f"{module}:{owner}")
    if not observed:
        return 0
    try:
        new.values[new_index] = old_value
        if ast.dump(before) == ast.dump(after):
            return int(observed, 16) | int(profile["subprocess_users"], 16)
    finally:
        new.values[new_index] = new_value
    return 0


def expression_attribute(node):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "exp":
        return node.attr
    return None


def return_type_on_line(tree, line):
    for statement in tree.body:
        if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "EXPRESSION_METADATA"
                and isinstance(statement.value, ast.Dict)):
            continue
        for key, entry in zip(statement.value.keys, statement.value.values):
            name = expression_attribute(key)
            if not name or not isinstance(entry, ast.Dict):
                continue
            for index, (field, value) in enumerate(zip(entry.keys, entry.values)):
                if (isinstance(field, ast.Constant) and field.value == "returns"
                        and value.lineno == value.end_lineno == line
                        and isinstance(value, ast.Attribute) and expression_attribute(value.value) == "DType"):
                    yield name, entry.values, index


def typing_config_readers(before, after, line, profile):
    old = list(return_type_on_line(before, line))
    new = list(return_type_on_line(after, line))
    if len(old) != 1 or len(new) != 1:
        return 0
    (name, old_values, index), = old
    (new_name, values, new_index), = new
    if name != new_name or not all(value.attr in profile["sql_type_names"]
                                  for value in (old_values[index], values[new_index])):
        return 0
    observed = 0
    for key, mask in profile["class_users"].items():
        if key.startswith("sqlglot.expressions.") and key.partition(":")[2] == name:
            observed |= int(mask, 16)
    saved = values[new_index]
    try:
        values[new_index] = old_values[index]
        if observed and ast.dump(before) == ast.dump(after):
            return (observed & int(profile["annotation_readers"], 16)) | int(profile["metadata_inspection"], 16)
        return 0
    finally:
        values[new_index] = saved


def file_users(path, profile, cache):
    if path not in cache:
        coverage = profile["files"].get(path, {})
        mask = 0
        for value in coverage.get("lines", {}).values():
            if value:
                mask |= int(value, 16)
        cache[path] = mask
    return cache[path]


def fixture_metadata(source):
    """Mirror the fixture reader's splitting without executing SQL."""
    statements = "\n".join(
        line for line in source.splitlines() if line and not line.startswith("--")
    ).split(";")
    metadata = []
    for statement in statements[:-1:2]:
        lines = statement.strip().split("\n")
        headers = []
        for line in lines:
            if not line.startswith("#"):
                break
            if ":" not in line:
                return None
            headers.append(line)
        if len(headers) == len(lines):
            return None
        metadata.append(tuple(headers))
    return len(statements), metadata


def choose(patch, profile, file_cache):
    selected = 0
    nearby = 0
    for path, section in sections(patch).items():
        source = profile["sources"][path]
        updated, changed, inserted = apply_section(
            path, section, source.removesuffix("\n").split("\n")
        )
        if path in profile["fixtures"]:
            selected |= int(profile["fixtures"][path], 16)
            cached = profile["cached_fixture_readers"].get(path)
            old_metadata = fixture_metadata(source) if cached else None
            if old_metadata is not None and old_metadata == fixture_metadata(updated):
                selected |= int(cached, 16)
            else:
                selected |= int(profile["file_reads"].get(path, "0"), 16)
            continue

        selected |= int(profile["file_reads"].get(path, "0"), 16)
        selected |= int(profile["subprocess_users"], 16)
        nearby |= file_users(path, profile, file_cache)
        before = ast.parse(source, filename=path, type_comments=True)
        after = ast.parse(updated, filename=path, type_comments=True)
        compile(after, path, "exec")
        if ast.dump(before) == ast.dump(after):
            # Position-only edits can matter to introspection, but ordinary
            # comments do not alter the parsed program or its type directives.
            continue
        one_line = (
            len(changed) == 1
            and changed == inserted
            and source.count("\n") == updated.count("\n")
        )
        if one_line:
            line = next(iter(changed))
            readers = changed_attribute(path, line, before, after, profile)
            readers |= class_config_change(path, line, before, after, profile)
            if path.startswith("sqlglot/typing/"):
                readers |= typing_config_readers(before, after, line, profile)
            if path.startswith("sqlglot/"):
                readers |= default_value_readers(
                    before, after, line, profile["files"][path], profile["default_reflection_readers"]
                )
            if readers:
                selected |= readers
                continue
        isolated = one_line and isolated_expression_change(before, after, next(iter(changed)))
        if path.startswith("tests/") or module_structure(before) != module_structure(after):
            raise ValueError("test code or module-level behavior changed")
        coverage = profile["files"][path]
        scopes = coverage["scopes"]
        # Insertions use the immediately preceding old line. Replacements
        # also retain the original deletion coordinates.
        locations = changed | inserted
        scope_mask = 0
        for line in locations:
            candidates = [
                (definition, start, end)
                for definition, start, end in scopes
                if start <= line <= end
            ]
            if not candidates:
                raise ValueError("change outside a measured function body")
            # An edit near a nested definition can affect its enclosing function
            # even when the nested function itself was never called.
            _, start, end = max(candidates, key=lambda scope: scope[2] - scope[0])
            if any(start <= number <= end for number in coverage["collection"]):
                raise ValueError("function runs during test collection")
            if isolated:
                reached = 0
                for position in isolated:
                    if value := coverage["lines"].get(str(position)):
                        reached |= int(value, 16)
                if reached:
                    scope_mask |= reached
                    continue
            measured = 0
            for number in range(start, end + 1):
                value = coverage["lines"].get(str(number))
                if value:
                    measured |= int(value, 16)
            if not measured:
                owner = enclosing_class(before.body, line)
                module = path.removesuffix(".py").replace("/", ".")
                class_mask = profile["class_users"].get(f"{module}:{owner}")
                if not class_mask:
                    raise ValueError("scope has no measured tests")
                measured = int(class_mask, 16)
            scope_mask |= measured
        selected |= scope_mask
    return selected, nearby


def worker_cost(workers, durations):
    return 2000 * len(workers) + max(
        (sum(durations[number] for number in group) for group in workers), default=0
    )


def reserve_workers(primary, candidates, durations):
    workers = partition(primary)
    if not candidates:
        return workers
    # The original selection stays mandatory. Add tests that fit the
    # existing simulated cost before spending more CI time.
    ceiling = worker_cost(workers, durations)
    ordered = sorted(candidates, key=lambda item: (item[1], item[0]))
    low, high = 1, len(ordered)
    while low <= high:
        count = (low + high) // 2
        preferred = partition(primary + ordered[:count])
        if worker_cost(preferred, durations) <= ceiling:
            workers = preferred
            low = count + 1
        else:
            high = count - 1
    return workers


def main(data=DATA, mapping=MAP):
    tests = json.loads((data / "tests.json").read_text(encoding="utf-8"))["tests"]
    profile = json.loads(gzip.decompress(mapping.read_bytes()))
    bit_by_id = {name: 1 << index for index, name in enumerate(profile["ids"])}
    known = []
    unknown = []
    all_tests = []
    for test in tests:
        entry = (test["number"], math.floor(test["seconds"] * 1000 + 0.5))
        all_tests.append(entry)
        if test["id"] in bit_by_id:
            known.append((bit_by_id[test["id"]], entry))
        else:
            unknown.append(entry)
    fallback = partition(all_tests)
    durations = dict(all_tests)
    file_cache = {}
    for path in sorted((data / "commits").glob("*.patch")):
        try:
            mask, nearby = choose(path.read_text(encoding="utf-8"), profile, file_cache)
        except (LookupError, ValueError, SyntaxError, RecursionError):
            workers = fallback
        else:
            primary = unknown + [test for bit, test in known if mask & bit]
            extra = nearby & ~mask
            candidates = [test for bit, test in known if extra & bit]
            workers = reserve_workers(primary, candidates, durations)
        print(json.dumps({"commit": path.stem, "workers": workers}, separators=(",", ":")))


if __name__ == "__main__":
    main()
