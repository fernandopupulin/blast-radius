import ast
from collections import defaultdict
import gzip
import json
from pathlib import Path
import sys

root, base, output = map(Path, sys.argv[1:])
profile = json.loads(gzip.decompress(base.read_bytes()))


def literal_attribute(node):
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign):
        target = node.target
    else:
        return None
    if not isinstance(target, ast.Name):
        return None
    try:
        value = ast.literal_eval(node.value)
    except (ValueError, TypeError):
        return None
    return target.id if type(value) in (bool, int, str, tuple, list, dict) else None


names = set()
for package in ("dialects", "parsers", "generators"):
    for path in (root / "sqlglot" / package).glob("*.py"):
        tree = ast.parse(path.read_bytes())
        for definition in ast.walk(tree):
            if isinstance(definition, ast.ClassDef):
                names.update(name for node in definition.body if (name := literal_attribute(node)))

observed = defaultdict(int)
unbound = defaultdict(int)
uncertain = set()
reflection = 0
reflection_at_collection = False
annotation_reads = 0
metadata_inspection = 0
for directory in ("sqlglot", "tests"):
    for path in root.joinpath(directory).rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        record = profile["files"].get(rel)
        tree = ast.parse(path.read_bytes())
        parent = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if record and (
                isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
                and node.attr in {"expression_metadata", "EXPRESSION_METADATA"}
                or isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                and node.id == "EXPRESSION_METADATA"
            ):
                mask = 0
                for line in range(node.lineno, node.end_lineno + 1):
                    if value := record["lines"].get(str(line)):
                        mask |= int(value, 16)
                if directory == "tests":
                    metadata_inspection |= mask
                elif isinstance(node, ast.Attribute) and node.attr == "expression_metadata":
                    annotation_reads |= mask
            if isinstance(node, ast.Attribute) and (
                node.attr in {"__defaults__", "__kwdefaults__", "getfullargspec"}
                or (node.attr == "signature" and isinstance(node.value, ast.Name)
                    and node.value.id == "inspect")
            ):
                call = parent.get(node)
                use = parent.get(call)
                # These forms only access the declared parameter names.
                if (isinstance(call, ast.Call) and call.func is node
                        and isinstance(use, ast.Attribute)
                        and use.attr in {"args", "parameters"}):
                    consumer = parent.get(use)
                    if use.attr == "args" or (
                        isinstance(consumer, ast.Call) and isinstance(consumer.func, ast.Name)
                        and consumer.func.id == "enumerate" and consumer.args == [use]
                    ):
                        continue
                if not record or node.lineno in record["collection"]:
                    reflection_at_collection = True
                elif value := record["lines"].get(str(node.lineno)):
                    reflection |= int(value, 16)
            # Literal name lookup or imports may bypass the tracked attribute reads.
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names:
                uncertain.add(node.value)
            elif isinstance(node, ast.alias) and node.name in names:
                uncertain.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in names:
                uncertain.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in names:
                name = node.attr
                if not isinstance(node.ctx, ast.Load) or not record:
                    uncertain.add(name)
                    continue
                lines = [str(n) for n in range(node.lineno, node.end_lineno + 1)]
                scopes = [s for s in record["scopes"] if s[1] <= node.lineno <= s[2]]
                if not scopes or any(node.lineno <= n <= node.end_lineno for n in record["collection"]):
                    uncertain.add(name)
                    continue
                mask = 0
                for line in lines:
                    value = record["lines"].get(line)
                    if value:
                        mask |= int(value, 16)
                if not mask:
                    uncertain.add(name)
                observed[name] |= mask
                if not isinstance(node.value, ast.Name) or node.value.id != "self":
                    unbound[name] |= mask

profile.pop("integer_attribute_readers", None)
profile["scalar_attribute_readers"] = {
    name: format(mask, "x")
    for name, mask in sorted(observed.items())
    if mask and name not in uncertain
}
profile["default_reflection_readers"] = None if reflection_at_collection else format(reflection, "x")
profile["annotation_readers"] = format(annotation_reads, "x")
profile["metadata_inspection"] = format(metadata_inspection, "x")
profile["unbound_attribute_readers"] = {
    name: format(unbound[name], "x") for name in profile["scalar_attribute_readers"]
}
dtype_tree = ast.parse((root / "sqlglot/expressions/datatypes.py").read_bytes())
dtype_class = next(node for node in dtype_tree.body if isinstance(node, ast.ClassDef) and node.name == "DType")
profile["sql_type_names"] = sorted({
    target.id
    for node in dtype_class.body if isinstance(node, ast.Assign)
    for target in node.targets if isinstance(target, ast.Name) and target.id.isupper()
})
output.write_bytes(gzip.compress(json.dumps(profile, separators=(",", ":")).encode(), mtime=0))
print("Eligible attributes and test counts",
      {name: int(mask, 16).bit_count() for name, mask in profile["scalar_attribute_readers"].items()})
