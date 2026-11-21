"""Run the pinned TPC-DS testcase and record its optimizer dependencies."""

from collections import defaultdict
from concurrent.futures import Future
import json
from pathlib import Path
import pickle
import sys
from unittest import TestSuite, TextTestRunner

from query_probe import digest


def main(output):
    root = Path.cwd().as_posix() + "/"
    active_query = None
    optimizer_active = False
    outside = defaultdict(set)
    lines = defaultdict(lambda: defaultdict(set))
    checkpoints = {}

    def observe(code, line):
        path = code.co_filename.removeprefix(root)
        if path.startswith("sqlglot/optimizer/"):
            if optimizer_active and active_query is not None:
                lines[path][line].add(active_query)
            else:
                outside[path].add(line)

    def capture(*args, **kwargs):
        nonlocal optimizer_active
        optimizer_active = True
        try:
            result = original_optimize(*args, **kwargs)
        finally:
            optimizer_active = False
        if active_query is not None:
            if active_query in checkpoints:
                raise ValueError("Unexpected optimizer call count")
            try:
                checkpoints[active_query] = digest(result)
            except ValueError:
                checkpoints[active_query] = None
        return result

    class InlinePool:
        def __init__(self, *, mp_context, initializer, initargs):
            self.initializer = initializer
            self.initargs = initargs
            self.index = 0

        def __enter__(self):
            self.initializer(*self.initargs)
            return self

        def __exit__(self, *_):
            return False

        def submit(self, function, *args):
            nonlocal active_query
            future = Future()
            active_query = self.index
            self.index += 1
            try:
                result = function(*pickle.loads(pickle.dumps(args)))
                future.set_result(pickle.loads(pickle.dumps(result)))
            except Exception as error:
                future.set_exception(error)
            finally:
                active_query = None
            return future

    sys.monitoring.use_tool_id(4, "query-reachability")
    sys.monitoring.register_callback(4, sys.monitoring.events.LINE, observe)
    sys.monitoring.set_events(4, sys.monitoring.events.LINE)

    from sqlglot import executor
    from tests import test_executor as upstream

    original_optimize = executor.optimize
    upstream.ProcessPoolExecutor = InlinePool
    executor.optimize = capture
    result = TextTestRunner(verbosity=2).run(TestSuite([upstream.TestExecutor("test_execute_tpcds")]))
    if not result.wasSuccessful() or result.testsRun != 1 or result.skipped or not checkpoints:
        raise SystemExit("Pinned TPC-DS testcase did not pass")
    data = {
        "lines": {path: {line: sorted(indices) for line, indices in sorted(mapping.items())}
                  for path, mapping in sorted(lines.items())},
        "outside": {path: sorted(values) for path, values in sorted(outside.items())},
        "checkpoints": checkpoints,
    }
    Path(output).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{len(checkpoints)} optimizer checkpoints, {sum(value is not None for value in checkpoints.values())} comparable")


if __name__ == "__main__":
    main(sys.argv[1])
