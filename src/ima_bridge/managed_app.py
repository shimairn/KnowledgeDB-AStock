from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from ima_bridge.config import Settings
from ima_bridge.errors import CaptureFailedError
from ima_bridge.utils import get_logger


class ManagedIMAApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = get_logger("ima_bridge.managed_app")

    def status(self) -> tuple[bool, str]:
        endpoint = self.settings.cdp_endpoint
        return self._cdp_ready(endpoint), endpoint

    def ensure_ready(self) -> str:
        endpoint = self.settings.cdp_endpoint
        if self._cdp_ready(endpoint):
            return endpoint

        executable = self._resolve_executable()
        if executable is None:
            raise CaptureFailedError("IMA_APP_EXECUTABLE is not set and auto-detection failed")

        self._launch(executable)
        deadline = time.monotonic() + self.settings.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._cdp_ready(endpoint):
                return endpoint
            time.sleep(0.5)
        raise CaptureFailedError("Managed ima app failed to expose CDP endpoint in time")

    def _resolve_executable(self) -> Path | None:
        if self.settings.app_executable:
            path = Path(self.settings.app_executable)
            if path.exists():
                return path
            raise CaptureFailedError(f"IMA_APP_EXECUTABLE does not exist: {path}")

        local_app_data = Path(os.getenv("LOCALAPPDATA", ""))
        program_files = Path(os.getenv("ProgramFiles", ""))
        candidates = [
            local_app_data / "ima.copilot" / "Application" / "ima.copilot.exe",
            local_app_data / "Programs" / "ima.copilot" / "ima.copilot.exe",
            local_app_data / "Programs" / "ima" / "ima.copilot.exe",
            local_app_data / "ima.copilot" / "ima.copilot.exe",
            program_files / "ima.copilot" / "ima.copilot.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _launch(self, executable: Path) -> None:
        profile_dir = str(self.settings.managed_profile_dir.resolve())
        args = [
            str(executable),
            f"--remote-debugging-port={self.settings.app_cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        self.logger.info("launching managed ima app: %s", args)

        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = 6
        subprocess.Popen(
            args,
            startupinfo=startup_info,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def _cdp_ready(self, endpoint: str) -> bool:
        url = f"{endpoint}/json/version"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return bool(payload.get("webSocketDebuggerUrl"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return False
