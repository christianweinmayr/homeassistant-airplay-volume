"""Manage the cliairplay binary subprocess for AirPlay speaker control."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Platform mapping: (system, machine) -> binary suffix
_PLATFORM_MAP: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux-x86_64",
    ("Linux", "aarch64"): "linux-aarch64",
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x86_64",
}

# Process management constants
_STOP_TIMEOUT = 5  # seconds to wait for SIGTERM before SIGKILL
_RESTART_BACKOFF_BASE = 2  # base seconds for exponential backoff
_RESTART_BACKOFF_MAX = 60  # max backoff seconds
_MAX_RESTART_ATTEMPTS = 5  # max consecutive restart attempts before giving up
_COMMAND_TIMEOUT = 10  # seconds to wait for a command response


class BinaryNotFoundError(Exception):
    """Raised when the cliairplay binary is not found for the current platform."""


class CLIAirplayConnectionError(Exception):
    """Raised when communication with the speaker fails."""


class CLIAirplayAuthenticationError(Exception):
    """Raised when pairing fails or credentials are expired."""


def _get_binary_path() -> Path:
    """Detect the current platform and return the path to the cliairplay binary.

    Raises BinaryNotFoundError if the platform is unsupported or binary is missing.
    """
    system = platform.system()
    machine = platform.machine()

    platform_suffix = _PLATFORM_MAP.get((system, machine))
    if platform_suffix is None:
        raise BinaryNotFoundError(
            f"Unsupported platform: {system} {machine}. "
            f"Supported: {', '.join(f'{s}-{m}' for (s, m) in _PLATFORM_MAP)}"
        )

    bin_dir = Path(__file__).parent / "bin"
    binary_path = bin_dir / f"cliairplay-{platform_suffix}"

    if not binary_path.is_file():
        raise BinaryNotFoundError(
            f"cliairplay binary not found at {binary_path}. "
            f"Expected binary for platform {platform_suffix}."
        )

    return binary_path


class CLIAirplayManager:
    """Manage a cliairplay subprocess for a single AirPlay speaker."""

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        host: str,
        port: int,
        credentials: str | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            hass: Home Assistant instance.
            device_id: Unique device identifier (MAC address from mDNS).
            host: Speaker IP address.
            port: Speaker AirPlay port.
            credentials: HAP pairing credentials (base64 string), or None if not yet paired.
        """
        self.hass = hass
        self.device_id = device_id
        self.host = host
        self.port = port
        self.credentials = credentials

        self._binary_path: Path | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._restart_count: int = 0
        self._monitor_task: asyncio.Task[None] | None = None
        self._stopping: bool = False

    async def start(self) -> None:
        """Launch the cliairplay subprocess for this device.

        Raises BinaryNotFoundError if the binary cannot be found.
        """
        if self._process is not None and self._process.returncode is None:
            _LOGGER.debug(
                "cliairplay already running for %s (pid=%s)",
                self.device_id,
                self._process.pid,
            )
            return

        self._stopping = False

        if self._binary_path is None:
            self._binary_path = await self.hass.async_add_executor_job(
                _get_binary_path
            )
            # Ensure binary is executable
            await self.hass.async_add_executor_job(
                os.chmod, self._binary_path, 0o755
            )

        cmd = [
            str(self._binary_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        if self.credentials:
            cmd.extend(["--credentials", self.credentials])

        _LOGGER.debug(
            "Starting cliairplay for %s: %s",
            self.device_id,
            " ".join(cmd),
        )

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _LOGGER.info(
            "cliairplay started for %s (pid=%s)", self.device_id, self._process.pid
        )

        self._restart_count = 0
        self._monitor_task = asyncio.create_task(
            self._monitor_process(), name=f"cliairplay_monitor_{self.device_id}"
        )

    async def stop(self) -> None:
        """Gracefully stop the cliairplay subprocess."""
        self._stopping = True

        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        if self._process is None or self._process.returncode is not None:
            self._process = None
            return

        pid = self._process.pid
        _LOGGER.debug("Stopping cliairplay for %s (pid=%s)", self.device_id, pid)

        try:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=_STOP_TIMEOUT)
                _LOGGER.debug("cliairplay (pid=%s) terminated gracefully", pid)
            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "cliairplay (pid=%s) did not terminate in %ss, sending SIGKILL",
                    pid,
                    _STOP_TIMEOUT,
                )
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            _LOGGER.debug("cliairplay (pid=%s) already exited", pid)

        self._process = None

    async def restart(self) -> None:
        """Stop and restart the cliairplay subprocess."""
        await self.stop()
        await self.start()

    async def is_running(self) -> bool:
        """Check if the cliairplay process is alive."""
        return self._process is not None and self._process.returncode is None

    async def set_volume(self, volume: float) -> None:
        """Set the speaker volume.

        Args:
            volume: Volume level between 0.0 and 1.0.

        Raises CLIAirplayConnectionError on failure.
        """
        volume_int = int(round(volume * 100))
        volume_int = max(0, min(100, volume_int))
        await self._run_command("volume", "set", str(volume_int))

    async def get_volume(self) -> float:
        """Query the current volume level.

        Returns:
            Volume level between 0.0 and 1.0.

        Raises CLIAirplayConnectionError on failure.
        """
        result = await self._run_command("volume", "get")
        try:
            vol = int(result.strip())
            return max(0.0, min(1.0, vol / 100.0))
        except (ValueError, TypeError) as err:
            raise CLIAirplayConnectionError(
                f"Invalid volume response: {result}"
            ) from err

    async def get_muted(self) -> bool:
        """Query the current mute state.

        Returns:
            True if muted, False otherwise.

        Raises CLIAirplayConnectionError on failure.
        """
        result = await self._run_command("mute", "get")
        return result.strip().lower() in ("true", "1", "muted")

    async def set_muted(self, muted: bool) -> None:
        """Set the mute state.

        Args:
            muted: True to mute, False to unmute.

        Raises CLIAirplayConnectionError on failure.
        """
        await self._run_command("mute", "set", "on" if muted else "off")

    async def play_audio(self, url: str, content_type: str) -> None:
        """Stream audio to the speaker.

        Args:
            url: URL of the audio file to play.
            content_type: MIME type of the audio (e.g., audio/mpeg, audio/wav).

        Raises CLIAirplayConnectionError on failure.
        """
        await self._run_command(
            "play", url, "--content-type", content_type, timeout=30
        )

    async def pair(self, pin: str) -> dict[str, Any]:
        """Initiate HAP pairing with the speaker.

        Args:
            pin: The PIN displayed on the speaker or entered by the user.

        Returns:
            Dict with pairing credentials (at minimum a 'credentials' key).

        Raises CLIAirplayAuthenticationError on pairing failure.
        Raises CLIAirplayConnectionError on communication failure.
        """
        try:
            result = await self._run_command("pair", "--pin", pin, timeout=30)
        except CLIAirplayConnectionError as err:
            raise CLIAirplayAuthenticationError(
                f"Pairing failed for {self.device_id}: {err}"
            ) from err

        credentials = result.strip()
        if not credentials:
            raise CLIAirplayAuthenticationError(
                f"Pairing returned empty credentials for {self.device_id}"
            )

        self.credentials = credentials
        return {"credentials": credentials}

    async def _run_command(
        self, *args: str, timeout: int = _COMMAND_TIMEOUT
    ) -> str:
        """Execute a cliairplay command as a one-shot subprocess.

        This spawns a new subprocess per command. Future optimization may use
        a long-running daemon with a control socket instead.

        Args:
            *args: Command arguments to pass to cliairplay.
            timeout: Maximum seconds to wait for the command.

        Returns:
            The stdout output from the command.

        Raises CLIAirplayConnectionError on failure.
        """
        if self._binary_path is None:
            self._binary_path = await self.hass.async_add_executor_job(
                _get_binary_path
            )

        cmd = [
            str(self._binary_path),
            "--host",
            self.host,
            "--port",
            str(self.port),
        ]
        if self.credentials:
            cmd.extend(["--credentials", self.credentials])
        cmd.extend(args)

        _LOGGER.debug(
            "Running cliairplay command for %s: %s",
            self.device_id,
            " ".join(cmd),
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError as err:
            raise CLIAirplayConnectionError(
                f"Command timed out after {timeout}s for {self.device_id}: "
                f"{' '.join(args)}"
            ) from err
        except OSError as err:
            raise CLIAirplayConnectionError(
                f"Failed to execute cliairplay for {self.device_id}: {err}"
            ) from err

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if stderr_text:
            _LOGGER.debug(
                "cliairplay stderr for %s: %s", self.device_id, stderr_text
            )

        if proc.returncode != 0:
            raise CLIAirplayConnectionError(
                f"cliairplay command failed (exit code {proc.returncode}) "
                f"for {self.device_id}: {stderr_text or stdout_text}"
            )

        return stdout_text

    async def _monitor_process(self) -> None:
        """Monitor the long-running cliairplay process and auto-restart on crash."""
        while not self._stopping:
            if self._process is None:
                return

            returncode = await self._process.wait()

            if self._stopping:
                return

            _LOGGER.warning(
                "cliairplay for %s exited unexpectedly (code=%s)",
                self.device_id,
                returncode,
            )

            # Read any remaining stderr for diagnostics
            if self._process.stderr:
                try:
                    stderr_data = await self._process.stderr.read()
                    if stderr_data:
                        _LOGGER.debug(
                            "cliairplay final stderr for %s: %s",
                            self.device_id,
                            stderr_data.decode("utf-8", errors="replace"),
                        )
                except Exception:  # noqa: BLE001
                    pass

            self._process = None

            if self._restart_count >= _MAX_RESTART_ATTEMPTS:
                _LOGGER.error(
                    "cliairplay for %s has crashed %d times, giving up auto-restart",
                    self.device_id,
                    self._restart_count,
                )
                return

            backoff = min(
                _RESTART_BACKOFF_BASE * (2 ** self._restart_count),
                _RESTART_BACKOFF_MAX,
            )
            self._restart_count += 1

            _LOGGER.info(
                "Restarting cliairplay for %s in %ss (attempt %d/%d)",
                self.device_id,
                backoff,
                self._restart_count,
                _MAX_RESTART_ATTEMPTS,
            )

            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return

            if self._stopping:
                return

            try:
                await self.start()
            except BinaryNotFoundError:
                _LOGGER.error(
                    "Cannot restart cliairplay for %s: binary not found",
                    self.device_id,
                )
                return
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Failed to restart cliairplay for %s", self.device_id
                )

            # After start() creates a new monitor task, this one should exit
            return
