import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .models import CommandDefinition


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None = None
    error: str | None = None


class CommandExecutor:
    """Runs configured commands in the user's interactive terminal."""

    def open_terminal(self) -> CommandResult:
        try:
            completed_process = self._run_process(
                self._build_terminal_process_arguments()
            )
        except KeyboardInterrupt:
            return CommandResult(exit_code=130)
        except OSError as error:
            return CommandResult(error=f"Unable to open terminal: {error}")
        return CommandResult(exit_code=completed_process.returncode)

    def run_in_terminal(self, command: CommandDefinition) -> CommandResult:
        for command_step in command.commands:
            try:
                if command_step.shell_command is not None:
                    process_arguments = self._build_shell_process_arguments(
                        command_step.shell_command
                    )
                else:
                    process_arguments = self._build_process_arguments(command_step.argv)
                completed_process = self._run_process(process_arguments)
            except KeyboardInterrupt:
                return CommandResult(exit_code=130)
            except (OSError, ValueError) as error:
                return CommandResult(
                    error=f"Unable to start '{command_step.display_command}': {error}"
                )
            if completed_process.returncode != 0:
                return CommandResult(exit_code=completed_process.returncode)
        return CommandResult(exit_code=0)

    @staticmethod
    def _build_process_arguments(command_arguments: tuple[str, ...]) -> list[str]:
        executable, *arguments = command_arguments
        executable_path = shutil.which(executable)
        if sys.platform == "win32" and executable_path is not None:
            suffix = Path(executable_path).suffix.lower()
            if not suffix:
                command_script = shutil.which(f"{executable}.cmd")
                if command_script is not None:
                    executable_path = command_script
                    suffix = ".cmd"
            if suffix in {".bat", ".cmd"}:
                if any(
                    any(character in argument for character in '&|<>()^%!"\r\n')
                    for argument in arguments
                ):
                    raise ValueError(
                        "Batch-file arguments cannot contain CMD metacharacters"
                    )
                return [
                    "cmd.exe",
                    "/d",
                    "/s",
                    "/c",
                    "call",
                    executable_path,
                    *arguments,
                ]
            if suffix == ".ps1":
                return [
                    "powershell.exe",
                    "-NoProfile",
                    "-File",
                    executable_path,
                    *arguments,
                ]

        return [executable, *arguments]

    @staticmethod
    def _build_shell_process_arguments(shell_command: str) -> list[str]:
        if sys.platform == "win32":
            return ["cmd.exe", "/d", "/s", "/c", shell_command]
        return ["/bin/sh", "-c", shell_command]

    @staticmethod
    def _run_process(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
        if sys.platform != "win32":
            return subprocess.run(arguments, check=False)

        previous_handler = signal.signal(signal.SIGINT, lambda _signal, _frame: None)
        try:
            return subprocess.run(arguments, check=False)
        finally:
            signal.signal(signal.SIGINT, previous_handler)

    @staticmethod
    def _build_terminal_process_arguments() -> list[str]:
        if sys.platform == "win32":
            pwsh_path = shutil.which("pwsh.exe") or shutil.which("pwsh")
            if pwsh_path is not None:
                return [
                    pwsh_path,
                    "-NoExit",
                    "-Command",
                    "Write-Host 'Press Ctrl+D or type exit to return to "
                    "TerminalRunner.'; "
                    f"{CommandExecutor._powershell_return_handler()}",
                ]
            return [
                "cmd.exe",
                "/d",
                "/k",
                "echo Type exit to return to TerminalRunner.",
            ]
        return [
            "/bin/sh",
            "-c",
            "printf '%s\\n' 'Press Ctrl+D or type exit to return to TerminalRunner.'; "
            "exec /bin/sh -i",
        ]

    @staticmethod
    def _powershell_return_handler() -> str:
        return (
            "Set-PSReadLineKeyHandler -Chord Ctrl+d -ScriptBlock { "
            "[System.Environment]::Exit(0) }"
        )
