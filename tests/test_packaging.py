"""Dev-tooling guarantees the suite itself depends on."""


def test_pytest_timeout_is_active_with_a_global_timeout(pytestconfig):
    """A lock-nesting regression must fail a test, not hang the run.

    The manifest-lock contract deadlocks by design (see runs.py). Without a
    timeout that surfaces as a CI hang with no failing test; with one it is a
    crisp per-test failure naming the offending test.
    """

    assert pytestconfig.pluginmanager.hasplugin("timeout")
    assert pytestconfig.getoption("timeout") == 60
