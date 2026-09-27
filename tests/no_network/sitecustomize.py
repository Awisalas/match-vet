from __future__ import annotations

import os
import socket
import sys
from typing import Never


class _DeniedSocket(socket.socket):
    def __new__(cls, *args: object, **kwargs: object) -> Never:
        del cls, args, kwargs
        raise AssertionError("The default MatchVet test suite forbids live network sockets.")


socket.socket = _DeniedSocket  # type: ignore[assignment,misc]

test_base_prefix = os.environ.get("MATCHVET_TEST_BASE_PREFIX")
if test_base_prefix is not None:
    sys.base_prefix = test_base_prefix
