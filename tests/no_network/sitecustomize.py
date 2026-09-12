from __future__ import annotations

import socket
from typing import Never


def _deny_live_socket(*args: object, **kwargs: object) -> Never:
    del args, kwargs
    raise AssertionError("The default MatchVet test suite forbids live network sockets.")


socket.socket = _deny_live_socket  # type: ignore[assignment,misc]
