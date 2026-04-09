"""
Shared pytest configuration and fixtures.

The session-scoped `block_network` fixture enforces the no-network guarantee:
Phase 0 and Phase 1 (basic) must never make outbound network calls. Any
accidental socket use — including import-time side effects — will raise
immediately rather than silently succeeding or timing out.
"""
import os
import socket

import pytest

# Show INFO-level log output during test runs so algorithm flow is visible
# without per-iteration dump noise.  Callers can override via APP_CONSOLE_LEVEL.
os.environ.setdefault("APP_CONSOLE_LEVEL", "INFO")


@pytest.fixture(autouse=True, scope="session")
def block_network():
    """Block all network calls for the duration of the test suite.

    Monkey-patches socket.socket so any attempt to open a connection raises
    RuntimeError. This catches both direct socket usage and higher-level
    wrappers (urllib, requests, httpx, etc.) that ultimately call socket.socket.

    The fixture is autouse + session-scoped, so it runs once for every
    `pytest` invocation without any test needing to opt in.
    """
    _real = socket.socket

    def _deny(*args, **kwargs):
        raise RuntimeError(
            "Network call attempted — not allowed in client-side code. "
            f"socket args: {args!r}. "
            "Phase 0 and Phase 1 must never make outbound network calls."
        )

    socket.socket = _deny
    yield
    socket.socket = _real
