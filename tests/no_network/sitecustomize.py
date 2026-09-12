from __future__ import annotations

import socket
from typing import Never


class _DeniedSocket(socket.socket):
    def __new__(cls, *args: object, **kwargs: object) -> Never:
        del cls, args, kwargs
        raise AssertionError("The default MatchVet test suite forbids live network sockets.")


socket.socket = _DeniedSocket  # type: ignore[assignment,misc]
