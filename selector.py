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


def conditional_lines(tree):
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and node.lineno == node.test.end_lineno
    }


def integer_class_assignment(tree, line):
    for definition in tree.body:
        if not isinstance(definition, ast.ClassDef):
            continue
        for node in definition.body:
            if (isinstance(node, ast.Assign) and node.lineno == node.end_lineno == line
                    and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                if type(value) is int:
                    return node
    return None


def changed_attribute(path, line, before, after, readers):
    if not path.startswith("sqlglot/dialects/"):
        return 0
    old = integer_class_assignment(before, line)
    new = integer_class_assignment(after, line)
    if old is None or new is None:
        return 0
    name = old.targets[0].id
    if name != new.targets[0].id or name not in readers:
        return 0
    previous = new.value
    try:
        new.value = old.value
        if ast.dump(before) == ast.dump(after):
            return int(readers[name], 16)
    finally:
        new.value = previous
    return 0


def choose(patch, profile):
    selected = 0
    for path, section in sections(patch).items():
        source = profile["sources"][path]
        updated, changed, inserted = apply_section(
            path, section, source.removesuffix("\n").split("\n")
        )
        if path in profile["fixtures"]:
            selected |= int(profile["fixtures"][path], 16)
            continue

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
            readers = changed_attribute(path, line, before, after, profile["integer_attribute_readers"])
            if readers:
                selected |= readers
                continue
        simple_change = changed if one_line and changed <= conditional_lines(before) & conditional_lines(after) else set()
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
            if line in simple_change:
                observed = coverage["lines"].get(str(line))
                if observed:
                    scope_mask |= int(observed, 16)
                    continue
            measured = 0
            for number in range(start, end + 1):
                value = coverage["lines"].get(str(number))
                if value:
                    measured |= int(value, 16)
            if not measured:
                raise ValueError("scope has no measured tests")
            scope_mask |= measured
        selected |= scope_mask
    return selected


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
    for path in sorted((data / "commits").glob("*.patch")):
        try:
            mask = choose(path.read_text(encoding="utf-8"), profile)
        except (LookupError, ValueError, SyntaxError, UnicodeError):
            workers = fallback
        else:
            workers = partition(unknown + [test for bit, test in known if mask & bit])
        print(json.dumps({"commit": path.stem, "workers": workers}, separators=(",", ":")))


if __name__ == "__main__":
    main()
