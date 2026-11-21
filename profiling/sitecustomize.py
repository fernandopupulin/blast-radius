"""Start recording when a process is spawned by a profiled test."""

import os
import coverage

if os.environ.get("BLAST_COMPARE_DISCOVER"):
    import comparison_observer

    comparison_observer.install()

if os.environ.get("BLAST_BRANCH_DISCOVER"):
    import branch_observer

    branch_observer.install()


def run_task(context, function, args, kwargs):
    """Attribute each task in a reusable worker to its submitting test."""
    tracer = coverage.Coverage.current()
    if tracer:
        tracer.switch_context(context)
    # The pool serializes the result after this function returns. Keep the
    # submitting test's context until the next task starts.
    return function(*args, **kwargs)

if context := os.environ.get("BLAST_TEST_CONTEXT"):
    import atexit

    cov = coverage.Coverage(
        source=["sqlglot", "tests"],
        data_file="/profile/children/coverage",
        data_suffix=True,
    )
    cov.start()
    cov.switch_context(context)

    @atexit.register
    def save_test_coverage():
        cov.stop()
        cov.save()
