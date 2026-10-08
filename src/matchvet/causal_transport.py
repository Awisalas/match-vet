"""The private causal protocol's single transport attempt."""

from __future__ import annotations

import io
import socket
import time
from http.client import HTTPResponse
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from matchvet.causal_selection import _WitnessAttempt


def _remaining(attempt: _WitnessAttempt, deadline: float) -> float:
    from matchvet.causal_selection import _WitnessAttempt
    from matchvet.causal_witness import WitnessError

    _WitnessAttempt._check_transport(attempt)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WitnessError("Single TSA transport deadline expired.")
    return remaining


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock: socket.socket, attempt: _WitnessAttempt, deadline: float) -> None:
        self._sock = sock
        self._attempt = attempt
        self._deadline = deadline
        self._raw = sock.makefile("rb", buffering=0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int | None:
        self._sock.settimeout(_remaining(self._attempt, self._deadline))
        count = self._raw.readinto(buffer)
        _remaining(self._attempt, self._deadline)
        return count

    def close(self) -> None:
        self._raw.close()
        super().close()


class _ResponseSocket:
    def __init__(self, sock: socket.socket, attempt: _WitnessAttempt, deadline: float) -> None:
        self._sock = sock
        self._attempt = attempt
        self._deadline = deadline

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("Unsupported HTTP response stream.")
        return io.BufferedReader(_DeadlineReader(self._sock, self._attempt, self._deadline))


def _post(attempt: _WitnessAttempt) -> bytes:
    """Consume original authority before one request, with no redirect or retry."""
    from http.client import HTTPException, HTTPSConnection

    from matchvet.causal_selection import _WitnessAttempt
    from matchvet.causal_witness import WitnessError

    if type(attempt) is not _WitnessAttempt:
        raise RuntimeError("Only the original concrete witness attempt may dispatch.")
    request = _WitnessAttempt._start_transport(attempt)
    deadline = time.monotonic() + 30

    class Response(HTTPResponse):
        def __init__(
            self,
            sock: socket.socket,
            debuglevel: int = 0,
            method: str | None = None,
            url: str | None = None,
        ) -> None:
            super().__init__(
                cast(socket.socket, _ResponseSocket(sock, attempt, deadline)),
                debuglevel=debuglevel,
                method=method,
                url=url,
            )

    connection = HTTPSConnection("timestamp.sigstore.dev", timeout=10)
    connection.response_class = Response
    try:
        connection.connect()
        if connection.sock is None:
            raise WitnessError("TSA connection is unavailable.")
        connection.sock.settimeout(_remaining(attempt, deadline))
        # DNS/TLS may have blocked: recheck original ownership at dispatch.
        _remaining(attempt, deadline)
        connection.request(
            "POST",
            "/api/v1/timestamp",
            body=request,
            headers={
                "Content-Type": "application/timestamp-query",
                "Accept": "application/timestamp-reply",
            },
        )
        _remaining(attempt, deadline)
        response = connection.getresponse()
        _remaining(attempt, deadline)
        if (
            response.status != 200
            or response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            != "application/timestamp-reply"
        ):
            raise WitnessError("Single TSA transport attempt refused.")
        raw = bytearray()
        while not response.isclosed():
            _remaining(attempt, deadline)
            chunk = response.read1(65536)
            _remaining(attempt, deadline)
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > 1_048_576:
                raise WitnessError("TSA response exceeds the profile limit.")
        if not raw:
            raise WitnessError("TSA response is empty.")
        return bytes(raw)
    except (OSError, HTTPException) as error:
        raise WitnessError("Single TSA transport attempt failed.") from error
    finally:
        connection.close()
