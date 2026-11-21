from concurrent.futures import ProcessPoolExecutor
import os

import class_observer
import pytest

submit = ProcessPoolExecutor.submit


def with_context(pool, function, /, *args, **kwargs):
    return submit(pool, class_observer.run_task, class_observer.active, function, args, kwargs)


class Events:
    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(self, item):
        class_observer.active = item.nodeid
        os.environ["BLAST_CLASS_CONTEXT"] = item.nodeid
        try:
            return (yield)
        finally:
            os.environ.pop("BLAST_CLASS_CONTEXT", None)
            class_observer.active = ""


if __name__ == "__main__":
    class_observer.enable()
    ProcessPoolExecutor.submit = with_context
    raise SystemExit(pytest.main(["tests", "-q", "--tb=short"], plugins=[Events()]))
