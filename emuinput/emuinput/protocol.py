"""Socket protocol client for talking to uinputd."""

from __future__ import annotations

import socket
from typing import Optional


class ProtocolError(RuntimeError):
    """Raised when the line protocol is malformed or transport fails."""


class UinputdClient:
    """Line-based client for the uinputd control socket."""

    def __init__(self, port: int, timeout: float = 5.0) -> None:
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._reader = None
        self._writer = None

    def connect(self) -> None:
        if self._sock is not None:
            return
        self._sock = socket.create_connection(("127.0.0.1", self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)
        self._reader = self._sock.makefile("r", encoding="utf-8", newline="\n")
        self._writer = self._sock.makefile("w", encoding="utf-8", newline="\n")

    def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        if self._reader is not None:
            self._reader.close()
            self._reader = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def send_line(self, line: str) -> None:
        if self._writer is None:
            raise ProtocolError("client is not connected")
        self._writer.write(line + "\n")
        self._writer.flush()

    def recv_line(self) -> str:
        if self._reader is None:
            raise ProtocolError("client is not connected")
        line = self._reader.readline()
        if line == "":
            raise ProtocolError("socket closed by peer")
        return line.rstrip("\r\n")

    def request(self, line: str) -> str:
        self.send_line(line)
        return self.recv_line()

    def key(self, key_code: int, value: int) -> str:
        return self.request(f"KEY {int(key_code)} {int(value)}")

    def hello(self) -> dict[str, int]:
        response = self.request("HELLO")
        parts = response.split()
        if len(parts) != 5 or parts[0] != "OK":
            raise ProtocolError(f"invalid HELLO response: {response!r}")
        try:
            x_min = int(parts[1])
            x_max = int(parts[2])
            y_min = int(parts[3])
            y_max = int(parts[4])
        except ValueError as exc:
            raise ProtocolError(f"invalid HELLO numeric payload: {response!r}") from exc

        return {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
        }
