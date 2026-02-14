"""ADB transport and process orchestration helpers."""

from __future__ import annotations

import os
import subprocess
from typing import Optional


class AdbError(RuntimeError):
    """Raised when an adb command fails."""


class Adb:
    """Small subprocess wrapper for adb commands."""

    def __init__(
        self,
        adb_exe: str = "adb",
        adb_server_port: Optional[int] = None,
        timeout: float = 20.0,
    ) -> None:
        self.adb_exe = adb_exe
        self.adb_server_port = adb_server_port
        self.timeout = timeout

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.adb_server_port is not None:
            env["ADB_SERVER_PORT"] = str(self.adb_server_port)
        return env

    def run(
        self,
        serial: Optional[str],
        *args: str,
        check: bool = True,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = [self.adb_exe]
        if serial:
            cmd.extend(["-s", serial])
        cmd.extend(args)

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=self._env(),
            timeout=self.timeout if timeout is None else float(timeout),
            check=False,
        )

        if check and proc.returncode != 0:
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            raise AdbError(
                f"adb failed (exit {proc.returncode}): {' '.join(cmd)}"
                f"\nstdout: {stdout}\nstderr: {stderr}"
            )

        return proc

    def shell(self, serial: str, cmd: str, timeout: Optional[float] = None) -> str:
        return self.run(serial, "shell", cmd, timeout=timeout).stdout.strip()

    def push(self, serial: str, local: str, remote: str) -> subprocess.CompletedProcess[str]:
        return self.run(serial, "push", local, remote)

    def forward(self, serial: str, host_port: int, abstract_name: str) -> subprocess.CompletedProcess[str]:
        return self.run(serial, "forward", f"tcp:{host_port}", f"localabstract:{abstract_name}")

    def remove_forward(self, serial: str, host_port: int) -> subprocess.CompletedProcess[str]:
        return self.run(serial, "forward", "--remove", f"tcp:{host_port}", check=False)
