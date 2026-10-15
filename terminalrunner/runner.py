import shutil
import signal
import subprocess
import sys
import textwrap
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
        first_failure: CommandResult | None = None
        for command_step in command.commands:
            if command_step.display_command:
                print(command_step.display_command, flush=True)
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
                failure = CommandResult(
                    error=f"Unable to start '{command_step.display_command}': {error}"
                )
                if not command.ignore_errors:
                    return failure
                if first_failure is None:
                    first_failure = failure
                continue
            if completed_process.returncode != 0:
                failure = CommandResult(exit_code=completed_process.returncode)
                if not command.ignore_errors:
                    return failure
                if first_failure is None:
                    first_failure = failure
        return first_failure or CommandResult(exit_code=0)

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
            pwsh_path = (
                shutil.which("pwsh.exe")
                or shutil.which("pwsh")
                or shutil.which("powershell.exe")
                or shutil.which("powershell")
            )
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
        # PSReadLine bug #1393: Set-PSReadLineKeyHandler resolves key chords
        # against the console layout active at shell startup (via Win32 ToUnicodeEx).
        # When started in a Russian layout, Ctrl+D maps to 'Ctrl+в', so switching to
        # English later causes Ctrl+D to be ignored. Conversely, starting in English
        # breaks Ctrl+D when switched to Russian.
        #
        # Because PSReadLine lacks a public API to bind raw virtual keys (VK_D),
        # we register the handler normally, then duplicate it across both Latin
        # and Cyrillic chords directly in PSReadLine's internal dispatch table.
        return textwrap.dedent(
            """
            Import-Module PSReadLine -ErrorAction SilentlyContinue;
            Set-PSReadLineKeyHandler -Chord Ctrl+d -ScriptBlock {
                [Environment]::Exit(0)
            };
            try {
                $flags = [Reflection.BindingFlags]'NonPublic,Static,Instance';
                $engine = [Microsoft.PowerShell.PSConsoleReadLine];
                $inst = $engine.GetField('_singleton', $flags).GetValue($null);
                $table = $inst.GetType().GetField(
                    '_dispatchTable', $flags
                ).GetValue($inst);
                $keyType = $engine.Assembly.GetType('Microsoft.PowerShell.PSKeyInfo');
                $ctor = $keyType.GetConstructor($flags, $null, @([string]), $null);
                $action = ($table.Values |
                    Where-Object { $_.BriefDescription -eq 'CustomAction' })[0];
                foreach ($chord in @('Ctrl+d', 'Ctrl+в', 'Ctrl+D', 'Ctrl+В')) {
                    $table[$ctor.Invoke(@($chord))] = $action
                }
            } catch {}
            """
        ).strip()
