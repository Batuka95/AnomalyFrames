"""High-level controller API for per-emulator gesture execution."""

from __future__ import annotations

import socket
import threading
import time
import re
from pathlib import Path
from typing import Optional

from .adb import Adb
from .easing import interpolate_steps
from .protocol import ProtocolError, UinputdClient

KEY_ENTER = 28
KEY_BACKSPACE = 14
KEY_SPACE = 57
KEY_MINUS = 12
KEY_LEFTSHIFT = 42

_LETTER_KEYCODES = {
    "a": 30, "b": 48, "c": 46, "d": 32, "e": 18, "f": 33, "g": 34,
    "h": 35, "i": 23, "j": 36, "k": 37, "l": 38, "m": 50, "n": 49,
    "o": 24, "p": 25, "q": 16, "r": 19, "s": 31, "t": 20, "u": 22,
    "v": 47, "w": 17, "x": 45, "y": 21, "z": 44,
}
_DIGIT_KEYCODES = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6,
    "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
}


class EmuController:
    """Coordinates adb + uinputd lifecycle for one emulator serial."""

    REMOTE_UINPUTD_PATH = "/data/local/tmp/uinputd"
    ABSTRACT_SOCKET_NAME = "uinputd"

    def __init__(self, serial: str, adb: Adb, host_port: int, bin_dir: str) -> None:
        self.serial = serial
        self.adb = adb
        self.host_port = int(host_port)
        self.bin_dir = Path(bin_dir)
        self._client: Optional[UinputdClient] = None
        self._hello: Optional[dict[str, int]] = None
        self._event_node: Optional[str] = None
        self._lock = threading.RLock()

    def _pick_local_binary(self) -> Path:
        try:
            abi_raw = self.adb.shell(self.serial, "getprop ro.product.cpu.abi", timeout=3.0).strip().lower()
        except Exception:
            abi_raw = ""
        candidates: list[Path] = []

        if "arm64" in abi_raw:
            candidates.append(self.bin_dir / "arm64-v8a" / "uinputd")
        if "x86_64" in abi_raw:
            candidates.append(self.bin_dir / "x86_64" / "uinputd")

        candidates.extend(
            [
                self.bin_dir / "x86_64" / "uinputd",
                self.bin_dir / "arm64-v8a" / "uinputd",
            ]
        )

        for path in candidates:
            if path.exists():
                return path

        checked = ", ".join(str(p) for p in candidates)
        raise FileNotFoundError(f"uinputd binary not found. Checked: {checked}")

    def _send_ok(self, cmd: str) -> str:
        if self._client is None:
            raise RuntimeError("uinputd client is not connected")
        response = self._client.request(cmd)
        if response == "OK" or response.startswith("OK "):
            return response
        raise ProtocolError(f"uinputd command failed: {cmd!r} -> {response!r}")

    def _connect_client(self, attempts: int = 40, delay_s: float = 0.1) -> dict[str, int]:
        last_exc: Optional[Exception] = None
        for _ in range(attempts):
            client = UinputdClient(self.host_port, timeout=2.0)
            try:
                client.connect()
                hello = client.hello()
                self._client = client
                return hello
            except (OSError, ProtocolError) as exc:
                last_exc = exc
                client.close()
                time.sleep(delay_s)

        raise RuntimeError(f"failed to connect to uinputd on tcp:{self.host_port}") from last_exc

    def _detect_event_node(self) -> Optional[str]:
        """
        Best-effort discovery of the uinputd event node for diagnostics.
        """
        try:
            out = self.adb.shell(
                self.serial,
                "toybox grep -ni -A12 -B2 uinputd-virtual-touchscreen /proc/bus/input/devices || true",
            )
        except Exception:
            return None

        match = re.search(r"\bevent\d+\b", out)
        return match.group(0) if match else None

    def ensure_daemon(self) -> dict[str, int]:
        with self._lock:
            if self._client is not None:
                try:
                    hello = self._client.hello()
                    self._hello = hello
                    return hello
                except Exception:
                    self._client.close()
                    self._client = None

            local_uinputd = self._pick_local_binary()
            self.adb.push(self.serial, str(local_uinputd), self.REMOTE_UINPUTD_PATH)
            self.adb.shell(self.serial, f"chmod 755 {self.REMOTE_UINPUTD_PATH}")
            self.adb.shell(
                self.serial,
                "toybox pkill -x uinputd >/dev/null 2>&1 || true",
            )

            self.adb.remove_forward(self.serial, self.host_port)
            self.adb.forward(self.serial, self.host_port, self.ABSTRACT_SOCKET_NAME)
            self.adb.shell(
                self.serial,
                f"toybox nohup {self.REMOTE_UINPUTD_PATH} --daemon > /data/local/tmp/uinputd.log 2>&1 &",
            )

            health = self.adb.shell(self.serial, "sleep 0.3; toybox pidof uinputd || echo NO_PID")
            if "NO_PID" in health.split():
                log_head = self.adb.shell(
                    self.serial,
                    "toybox head -n 120 /data/local/tmp/uinputd.log || true",
                )
                raise RuntimeError(f"uinputd failed to start. Log head:\n{log_head}")

            hello = self._connect_client()
            self._hello = hello
            self._event_node = self._detect_event_node()
            return hello

    def tap(self, x: int, y: int, down_ms: int = 70) -> None:
        with self._lock:
            self.ensure_daemon()
            self._send_ok(f"DOWN {int(x)} {int(y)}")
            time.sleep(max(0, int(down_ms)) / 1000.0)
            self._send_ok("UP")

    def drag(self, x0: int, y0: int, x1: int, y1: int, duration_ms: int = 350, steps: int = 24) -> None:
        with self._lock:
            self.ensure_daemon()
            points = interpolate_steps(int(x0), int(y0), int(x1), int(y1), int(steps))
            self._send_ok(f"DOWN {points[0][0]} {points[0][1]}")

            if len(points) > 1:
                interval_s = max(0, int(duration_ms)) / 1000.0 / (len(points) - 1)
                for x, y in points[1:]:
                    time.sleep(interval_s)
                    self._send_ok(f"MOVE {x} {y}")

            self._send_ok("UP")

    def key_event(self, key_code: int, value: int) -> None:
        with self._lock:
            self.ensure_daemon()
            self._send_ok(f"KEY {int(key_code)} {int(value)}")

    def key_tap(self, key_code: int, down_ms: int = 45) -> None:
        with self._lock:
            self.ensure_daemon()
            self._send_ok(f"KEY {int(key_code)} 1")
            time.sleep(max(0, int(down_ms)) / 1000.0)
            self._send_ok(f"KEY {int(key_code)} 0")

    @staticmethod
    def _char_to_key(char: str) -> tuple[int, bool]:
        if not char:
            raise ValueError("empty character")
        if char in _DIGIT_KEYCODES:
            return _DIGIT_KEYCODES[char], False
        if char in _LETTER_KEYCODES:
            return _LETTER_KEYCODES[char], False
        if char.lower() in _LETTER_KEYCODES and char.isalpha():
            return _LETTER_KEYCODES[char.lower()], True
        if char == "-":
            return KEY_MINUS, False
        if char == "_":
            return KEY_MINUS, True
        if char == " ":
            return KEY_SPACE, False
        raise ValueError(f"unsupported character for uinput typing: {char!r}")

    def type_text(
        self,
        text: str,
        *,
        key_down_ms: int = 38,
        inter_key_ms: int = 30,
    ) -> None:
        payload = str(text or "")
        if not payload:
            return

        with self._lock:
            self.ensure_daemon()
            for ch in payload:
                key_code, need_shift = self._char_to_key(ch)
                if need_shift:
                    self._send_ok(f"KEY {KEY_LEFTSHIFT} 1")
                self._send_ok(f"KEY {key_code} 1")
                time.sleep(max(0, int(key_down_ms)) / 1000.0)
                self._send_ok(f"KEY {key_code} 0")
                if need_shift:
                    self._send_ok(f"KEY {KEY_LEFTSHIFT} 0")
                time.sleep(max(0, int(inter_key_ms)) / 1000.0)

    def press_enter(self, down_ms: int = 45) -> None:
        self.key_tap(KEY_ENTER, down_ms=down_ms)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.request("QUIT")
                except Exception:
                    pass
                finally:
                    self._client.close()
                    self._client = None

            self.adb.remove_forward(self.serial, self.host_port)
            self._hello = None
