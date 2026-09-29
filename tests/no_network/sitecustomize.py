from __future__ import annotations

import os
import socket
import sys


class _DeniedSocket(socket.socket):
    def connect(self, address: object) -> None:
        sys.audit("socket.connect", self, address)
        raise AssertionError("The default MatchVet test suite forbids live network connections.")

    def connect_ex(self, address: object) -> int:
        sys.audit("socket.connect", self, address)
        raise AssertionError("The default MatchVet test suite forbids live network connections.")

    def sendto(self, *args: object, **kwargs: object) -> int:
        destination = args[-1] if args else kwargs.get("address")
        sys.audit("socket.sendto", self, destination)
        raise AssertionError("The default MatchVet test suite forbids live network connections.")


socket.socket = _DeniedSocket  # type: ignore[misc]

test_base_prefix = os.environ.get("MATCHVET_TEST_BASE_PREFIX")
if test_base_prefix is not None:
    sys.base_prefix = test_base_prefix
