import pytest

import oracle


@pytest.fixture
def rars():
    """The RARS oracle module; the test is skipped if java or the jar is missing."""
    if not oracle.available():
        pytest.skip("RARS oracle needs `java` in PATH and tests/devel/rars1_6.jar")
    return oracle
