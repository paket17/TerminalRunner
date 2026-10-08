import subprocess
import signal
import unittest
from unittest.mock import Mock, call, patch

from terminalrunner.models import CommandDefinition, CommandStep
from terminalrunner.runner import CommandExecutor


class CommandExecutorTests(unittest.TestCase):
    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch("terminalrunner.runner.shutil.which", return_value=r"D:\Tools\do.bat")
    def test_runs_batch_file_from_path_through_cmd(self, which: Mock) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(CommandStep(argv=("do", "all", "local-up")),),
        )

        self.assertEqual(
            CommandExecutor._build_process_arguments(command.commands[0].argv),
            [
                "cmd.exe",
                "/d",
                "/s",
                "/c",
                "call",
                r"D:\Tools\do.bat",
                "all",
                "local-up",
            ],
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch(
        "terminalrunner.runner.shutil.which",
        side_effect=[
            r"D:\Programs\Microsoft VS Code\bin\code",
            r"D:\Programs\Microsoft VS Code\bin\code.cmd",
        ],
    )
    def test_prefers_cmd_wrapper_for_extensionless_windows_command(
        self, which: Mock
    ) -> None:
        command = CommandDefinition(
            title="Open config",
            description="Open config",
            commands=(CommandStep(argv=("code", r"D:\Projects\config.yml")),),
        )

        self.assertEqual(
            CommandExecutor._build_process_arguments(command.commands[0].argv),
            [
                "cmd.exe",
                "/d",
                "/s",
                "/c",
                "call",
                r"D:\Programs\Microsoft VS Code\bin\code.cmd",
                r"D:\Projects\config.yml",
            ],
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch("terminalrunner.runner.shutil.which", return_value=r"D:\Tools\do.cmd")
    def test_rejects_cmd_metacharacters_in_batch_file_arguments(
        self, which: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(CommandStep(argv=("do", "safe&echo injected")),),
        )

        with self.assertRaisesRegex(ValueError, "CMD metacharacters"):
            CommandExecutor._build_process_arguments(command.commands[0].argv)

    @patch("terminalrunner.runner.sys.platform", "win32")
    def test_builds_windows_shell_command(self) -> None:
        self.assertEqual(
            CommandExecutor._build_shell_process_arguments("echo %USERNAME%"),
            ["cmd.exe", "/d", "/s", "/c", "echo %USERNAME%"],
        )

    @patch("terminalrunner.runner.sys.platform", "linux")
    def test_builds_linux_shell_command(self) -> None:
        self.assertEqual(
            CommandExecutor._build_shell_process_arguments("echo $USER"),
            ["/bin/sh", "-c", "echo $USER"],
        )

    @patch.object(CommandExecutor, "_run_process")
    def test_runs_commands_in_order(self, run: Mock) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(argv=("do", "first")),
                CommandStep(argv=("do", "second")),
            ),
        )
        run.side_effect = [subprocess.CompletedProcess([], 0)] * 2

        with patch.object(
            CommandExecutor,
            "_build_process_arguments",
            side_effect=[["do", "first"], ["do", "second"]],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            run.call_args_list,
            [
                call(["do", "first"]),
                call(["do", "second"]),
            ],
        )

    @patch.object(CommandExecutor, "_run_process")
    def test_stops_after_a_failed_command(self, run: Mock) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(argv=("do", "first")),
                CommandStep(argv=("do", "second")),
            ),
        )
        run.return_value = subprocess.CompletedProcess([], 1)

        with patch.object(
            CommandExecutor,
            "_build_process_arguments",
            return_value=["do", "first"],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 1)
        run.assert_called_once_with(["do", "first"])

    @patch.object(CommandExecutor, "_run_process")
    def test_continues_after_a_failed_command_when_ignore_errors(
        self, run: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(argv=("do", "first")),
                CommandStep(argv=("do", "second")),
            ),
            ignore_errors=True,
        )
        run.side_effect = [
            subprocess.CompletedProcess([], 1),
            subprocess.CompletedProcess([], 0),
        ]

        with patch.object(
            CommandExecutor,
            "_build_process_arguments",
            side_effect=[["do", "first"], ["do", "second"]],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            run.call_args_list,
            [
                call(["do", "first"]),
                call(["do", "second"]),
            ],
        )

    @patch.object(CommandExecutor, "_run_process")
    def test_preserves_first_failure_when_multiple_fail_with_ignore_errors(
        self, run: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(argv=("do", "first")),
                CommandStep(argv=("do", "second")),
            ),
            ignore_errors=True,
        )
        run.side_effect = [
            subprocess.CompletedProcess([], 2),
            subprocess.CompletedProcess([], 3),
        ]

        with patch.object(
            CommandExecutor,
            "_build_process_arguments",
            side_effect=[["do", "first"], ["do", "second"]],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(
            run.call_args_list,
            [
                call(["do", "first"]),
                call(["do", "second"]),
            ],
        )

    @patch.object(CommandExecutor, "_run_process")
    def test_returns_success_when_ignore_errors_and_all_commands_succeed(
        self, run: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(argv=("do", "first")),
                CommandStep(argv=("do", "second")),
            ),
            ignore_errors=True,
        )
        run.side_effect = [
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0),
        ]

        with patch.object(
            CommandExecutor,
            "_build_process_arguments",
            side_effect=[["do", "first"], ["do", "second"]],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            run.call_args_list,
            [
                call(["do", "first"]),
                call(["do", "second"]),
            ],
        )

    @patch.object(CommandExecutor, "_run_process")
    def test_continues_when_command_fails_to_start_with_ignore_errors(
        self, run: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(argv=("invalid",)),
                CommandStep(argv=("do", "second")),
            ),
            ignore_errors=True,
        )
        run.side_effect = [
            OSError("file not found"),
            subprocess.CompletedProcess([], 0),
        ]

        with patch.object(
            CommandExecutor,
            "_build_process_arguments",
            side_effect=[["invalid"], ["do", "second"]],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.error, "Unable to start 'invalid': file not found")
        self.assertEqual(
            run.call_args_list,
            [
                call(["invalid"]),
                call(["do", "second"]),
            ],
        )

    @patch.object(CommandExecutor, "_run_process")
    def test_continues_after_failed_shell_command_when_ignore_errors(
        self, run: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(
                CommandStep(shell_command="exit 1"),
                CommandStep(shell_command="echo second"),
            ),
            ignore_errors=True,
        )
        run.side_effect = [
            subprocess.CompletedProcess([], 1),
            subprocess.CompletedProcess([], 0),
        ]

        with patch.object(
            CommandExecutor,
            "_build_shell_process_arguments",
            side_effect=[["sh", "-c", "exit 1"], ["sh", "-c", "echo second"]],
        ):
            result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 1)
        self.assertEqual(
            run.call_args_list,
            [
                call(["sh", "-c", "exit 1"]),
                call(["sh", "-c", "echo second"]),
            ],
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch(
        "terminalrunner.runner.shutil.which",
        return_value=None,
    )
    @patch.object(CommandExecutor, "_run_process")
    def test_runs_direct_windows_command_without_a_shell(
        self, run: Mock, which: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(CommandStep(argv=("tool", "argument with spaces")),),
        )
        run.return_value = subprocess.CompletedProcess([], 0)

        result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 0)
        run.assert_called_once_with(["tool", "argument with spaces"])

    @patch("terminalrunner.runner.subprocess.run", side_effect=KeyboardInterrupt)
    def test_returns_interrupt_exit_code_when_command_is_cancelled(
        self, run: Mock
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            commands=(CommandStep(argv=("tool",)),),
        )

        result = CommandExecutor().run_in_terminal(command)

        self.assertEqual(result.exit_code, 130)
        run.assert_called_once()

    @patch("terminalrunner.runner.subprocess.run", side_effect=KeyboardInterrupt)
    def test_returns_interrupt_exit_code_when_terminal_is_cancelled(
        self, run: Mock
    ) -> None:
        result = CommandExecutor().open_terminal()

        self.assertEqual(result.exit_code, 130)
        run.assert_called_once()

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch(
        "terminalrunner.runner.signal.signal", return_value=signal.default_int_handler
    )
    @patch("terminalrunner.runner.subprocess.run")
    def test_keeps_ctrl_c_for_windows_child_processes(
        self, run: Mock, set_signal_handler: Mock
    ) -> None:
        run.return_value = subprocess.CompletedProcess([], 0)

        result = CommandExecutor().open_terminal()

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(set_signal_handler.call_args_list[0].args[0], signal.SIGINT)
        self.assertEqual(
            set_signal_handler.call_args_list[1].args,
            (signal.SIGINT, signal.default_int_handler),
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch(
        "terminalrunner.runner.shutil.which",
        return_value=r"C:\Program Files\PowerShell\7\pwsh.exe",
    )
    @patch("terminalrunner.runner.subprocess.run")
    def test_opens_powershell_terminal(self, run: Mock, which: Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0)

        result = CommandExecutor().open_terminal()

        self.assertEqual(result.exit_code, 0)
        run.assert_called_once_with(
            [
                r"C:\Program Files\PowerShell\7\pwsh.exe",
                "-NoExit",
                "-Command",
                "Write-Host 'Press Ctrl+D or type exit to return to TerminalRunner.'; "
                f"{CommandExecutor._powershell_return_handler()}",
            ],
            check=False,
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch(
        "terminalrunner.runner.shutil.which",
        side_effect=lambda name: (
            r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe"
            if "powershell" in name
            else None
        ),
    )
    @patch("terminalrunner.runner.subprocess.run")
    def test_falls_back_to_windows_powershell(self, run: Mock, which: Mock) -> None:
        run.return_value = subprocess.CompletedProcess([], 0)

        result = CommandExecutor().open_terminal()

        self.assertEqual(result.exit_code, 0)
        run.assert_called_once_with(
            [
                r"C:\WINDOWS\System32\WindowsPowerShell\v1.0\powershell.exe",
                "-NoExit",
                "-Command",
                "Write-Host 'Press Ctrl+D or type exit to return to TerminalRunner.'; "
                f"{CommandExecutor._powershell_return_handler()}",
            ],
            check=False,
        )

    def test_powershell_return_handler_binds_latin_and_cyrillic_chords(self) -> None:
        handler = CommandExecutor._powershell_return_handler()
        self.assertIn("Ctrl+d", handler)
        self.assertIn("Ctrl+в", handler)
        self.assertIn("Ctrl+D", handler)
        self.assertIn("Ctrl+В", handler)

    @patch("terminalrunner.runner.sys.platform", "linux")
    def test_opens_linux_terminal_with_return_hint(self) -> None:
        self.assertEqual(
            CommandExecutor._build_terminal_process_arguments(),
            [
                "/bin/sh",
                "-c",
                "printf '%s\\n' 'Press Ctrl+D or type exit to return to "
                "TerminalRunner.'; "
                "exec /bin/sh -i",
            ],
        )
