from concurrent.futures import ProcessPoolExecutor
import os

import class_observer
import pytest
import shared_fixture_observer
import attribute_observer

submit = ProcessPoolExecutor.submit


def with_context(pool, function, /, *args, **kwargs):
    return submit(pool, class_observer.run_task, class_observer.active, function, args, kwargs)


class Events:
    def pytest_collection_finish(self, session):
        shared_fixture_observer.install(session.items, lambda: class_observer.active)

    @pytest.hookimpl(wrapper=True)
    def pytest_fixture_setup(self, fixturedef, request):
        previous = attribute_observer.shared_scope
        if fixturedef.scope != "function":
            attribute_observer.shared_scope = (
                request.node.nodeid if fixturedef.scope in {"class", "module"} else ""
            )
        try:
            return (yield)
        finally:
            attribute_observer.shared_scope = previous

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
