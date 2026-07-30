import os
import queue
import signal
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, cast

from .models import CommandDefinition


class WindowsPtyProcess(Protocol):
    """The subset of pywinpty used by CommandExecutor."""

    @property
    def exitstatus(self) -> int | None: ...

    def isalive(self) -> bool: ...

    def terminate(self, force: bool = False) -> object: ...

    def wait(self) -> object: ...

    def close(self) -> None: ...


Process = WindowsPtyProcess | subprocess.Popen[bytes]
OutputReader = Callable[[], str]
InputWriter = Callable[[str], None]


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    error: str | None = None


class CommandExecutor:
    """Runs one configured command at a time and streams its combined output."""

    def __init__(self) -> None:
        self._process: Process | None = None
        self._input_writer: InputWriter | None = None
        self._master_fd: int | None = None
        self._cancel_requested = False
        self._run_active = False
        self._termination_started_at: float | None = None
        self._termination_escalated = False
        self._lock = threading.Lock()

    TERMINATION_GRACE_SECONDS = 1

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._is_running(self._process)

    def run(
        self, command: CommandDefinition, on_output: Callable[[str], None]
    ) -> CommandResult:
        with self._lock:
            self._cancel_requested = False
            self._run_active = True
            self._termination_started_at = None
            self._termination_escalated = False

        process: Process | None = None
        try:
            try:
                process, read_output, write_input = self._start_process(command)
            except (OSError, ValueError) as error:
                return CommandResult(
                    error=f"Unable to start '{command.display_command}': {error}"
                )

            with self._lock:
                self._process = process
                self._input_writer = write_input
                cancel_requested = self._cancel_requested
            if cancel_requested:
                self._request_termination(process)

            lines: queue.Queue[str] = queue.Queue(maxsize=256)
            reader = threading.Thread(
                target=self._read_output, args=(read_output, lines), daemon=True
            )
            reader.start()
            deadline = time.monotonic() + command.timeout_seconds
            timed_out = False

            while self._is_running(process):
                self._drain_output(lines, on_output)
                now = time.monotonic()
                if not timed_out and now >= deadline:
                    timed_out = True
                    self._request_termination(process)
                self._escalate_termination_if_needed(process, now)
                time.sleep(0.05)

            reader.join(timeout=1)
            self._drain_output(lines, on_output)
            with self._lock:
                cancelled = self._cancel_requested
            return CommandResult(
                self._exit_code(process), timed_out=timed_out, cancelled=cancelled
            )
        finally:
            if self._master_fd is not None:
                try:
                    os.close(self._master_fd)
                except OSError:
                    pass
                self._master_fd = None
            if process is not None:
                self._close_process(process)
            with self._lock:
                self._process = None
                self._input_writer = None
                self._run_active = False

    def cancel(self) -> bool:
        with self._lock:
            if not self._run_active:
                return False
            process = self._process
            self._cancel_requested = True
        if process is not None and self._is_running(process):
            self._request_termination(process)
        return True

    def send_input(self, text: str) -> bool:
        with self._lock:
            writer = self._input_writer
        if writer is None:
            return False
        try:
            writer(text)
        except (EOFError, OSError):
            return False
        return True

    def _start_process(
        self, command: CommandDefinition
    ) -> tuple[Process, OutputReader, InputWriter]:
        arguments = self._build_process_arguments(command)
        if sys.platform == "win32":
            from winpty import PtyProcess

            process = PtyProcess.spawn(arguments)

            def read_windows_output() -> str:
                return process.read()

            def write_windows_input(text: str) -> None:
                process.write(text)

            return process, read_windows_output, write_windows_input

        master_fd, slave_fd = os.openpty()
        try:
            process = subprocess.Popen(
                arguments,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        self._master_fd = master_fd

        def read_output() -> str:
            try:
                return os.read(master_fd, 4096).decode("utf-8", errors="replace")
            except OSError:
                return ""

        def write_input(text: str) -> None:
            os.write(master_fd, text.encode("utf-8"))

        return process, read_output, write_input

    @staticmethod
    def _is_running(process: Process) -> bool:
        if sys.platform == "win32":
            return cast(WindowsPtyProcess, process).isalive()
        return cast(subprocess.Popen[bytes], process).poll() is None

    @staticmethod
    def _terminate(process: Process) -> None:
        if sys.platform == "win32":
            cast(WindowsPtyProcess, process).terminate(force=True)
            return
        try:
            os.killpg(cast(subprocess.Popen[bytes], process).pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    @staticmethod
    def _kill(process: Process) -> None:
        if sys.platform == "win32":
            cast(WindowsPtyProcess, process).terminate(force=True)
            return
        try:
            os.killpg(cast(subprocess.Popen[bytes], process).pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _request_termination(self, process: Process) -> None:
        with self._lock:
            if self._termination_started_at is not None:
                return
            self._termination_started_at = time.monotonic()
        self._terminate(process)

    def _escalate_termination_if_needed(self, process: Process, now: float) -> None:
        with self._lock:
            should_kill = (
                self._termination_started_at is not None
                and not self._termination_escalated
                and now - self._termination_started_at >= self.TERMINATION_GRACE_SECONDS
            )
            if should_kill:
                self._termination_escalated = True
        if should_kill:
            self._kill(process)

    @staticmethod
    def _exit_code(process: Process) -> int | None:
        if sys.platform == "win32":
            windows_process = cast(WindowsPtyProcess, process)
            windows_process.wait()
            return windows_process.exitstatus
        return cast(subprocess.Popen[bytes], process).returncode

    @staticmethod
    def _close_process(process: Process) -> None:
        if sys.platform == "win32":
            cast(WindowsPtyProcess, process).close()

    @staticmethod
    def _build_process_arguments(command: CommandDefinition) -> list[str]:
        if command.shell_command is not None:
            if sys.platform == "win32":
                return ["cmd.exe", "/d", "/s", "/c", command.shell_command]
            return ["/bin/sh", "-c", command.shell_command]
        executable_path = shutil.which(command.executable)
        if sys.platform == "win32" and executable_path is not None:
            suffix = Path(executable_path).suffix.lower()
            if suffix in {".bat", ".cmd"}:
                if any(
                    any(character in argument for character in '&|<>()^%!"\r\n')
                    for argument in command.arguments
                ):
                    raise ValueError(
                        "Batch-file arguments cannot contain CMD metacharacters"
                    )
                return [
                    "cmd.exe",
                    "/d",
                    "/s",
                    "/c",
                    executable_path,
                    *command.arguments,
                ]
            if suffix == ".ps1":
                return [
                    "powershell.exe",
                    "-NoProfile",
                    "-File",
                    executable_path,
                    *command.arguments,
                ]

        return [command.executable, *command.arguments]

    @staticmethod
    def _read_output(read_output: Callable[[], str], lines: queue.Queue[str]) -> None:
        while True:
            try:
                text = read_output()
            except EOFError:
                return
            if not text:
                return
            lines.put(text)

    @staticmethod
    def _drain_output(
        lines: queue.Queue[str], on_output: Callable[[str], None]
    ) -> None:
        while True:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                return
            on_output(line)
