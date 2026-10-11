import socket

import pytest

BLOCKED = "Network access is disabled in tests"


def test_socket_connect_is_blocked():
    with socket.socket() as s, pytest.raises(RuntimeError, match=BLOCKED):
        s.connect(("192.0.2.1", 80))  # TEST-NET-1, never routable


def test_create_connection_is_blocked():
    with pytest.raises(RuntimeError, match=BLOCKED):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)
