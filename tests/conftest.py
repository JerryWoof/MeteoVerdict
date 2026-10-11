"""Shared pytest configuration.

The test suite must never touch the network: all external data comes from
recorded fixtures under ``tests/fixtures``. This guard makes any attempt to open
an outbound connection fail loudly instead of silently depending on the
internet (which CI may or may not have).
"""

from __future__ import annotations

import socket

import pytest


class NetworkAccessError(RuntimeError):
    """Raised when a test tries to open a network connection."""


def _blocked(*args, **kwargs):
    raise NetworkAccessError("Network access is disabled in tests; use a recorded fixture instead.")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
