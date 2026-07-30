import sys
import signal
import threading
import time
import unittest
from unittest.mock import Mock, patch

from terminalrunner.models import CommandDefinition
from terminalrunner.runner import CommandExecutor


class CommandExecutorTests(unittest.TestCase):
    def test_runs_command_and_returns_output(self) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            executable=sys.executable,
            arguments=("-c", "print('completed')"),
            timeout_seconds=5,
        )
        output: list[str] = []

        result = CommandExecutor().run(command, output.append)

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.error, None)
        self.assertIn("completed", "".join(output))

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch("terminalrunner.runner.shutil.which", return_value=r"D:\Tools\do.bat")
    def test_runs_batch_file_from_path_through_cmd(self, which: object) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            executable="do",
            arguments=("all", "local-up"),
            timeout_seconds=5,
        )

        self.assertEqual(
            CommandExecutor._build_process_arguments(command),
            ["cmd.exe", "/d", "/s", "/c", r"D:\Tools\do.bat", "all", "local-up"],
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    @patch("terminalrunner.runner.shutil.which", return_value=r"D:\Tools\do.cmd")
    def test_rejects_cmd_metacharacters_in_batch_file_arguments(
        self, which: object
    ) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            executable="do",
            arguments=("safe&echo injected",),
            timeout_seconds=5,
        )

        with self.assertRaisesRegex(ValueError, "CMD metacharacters"):
            CommandExecutor._build_process_arguments(command)

    @patch("terminalrunner.runner.sys.platform", "win32")
    def test_runs_chained_command_through_windows_shell(self) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            executable="do",
            arguments=("first", "&&", "do", "second"),
            timeout_seconds=5,
            shell_command="do first && do second",
        )

        self.assertEqual(
            CommandExecutor._build_process_arguments(command),
            ["cmd.exe", "/d", "/s", "/c", "do first && do second"],
        )

    @patch("terminalrunner.runner.sys.platform", "linux")
    def test_runs_chained_command_through_linux_shell(self) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            executable="do",
            arguments=("first", "&&", "do", "second"),
            timeout_seconds=5,
            shell_command="do first && do second",
        )

        self.assertEqual(
            CommandExecutor._build_process_arguments(command),
            ["/bin/sh", "-c", "do first && do second"],
        )

    @patch("terminalrunner.runner.sys.platform", "win32")
    def test_forces_windows_process_termination(self) -> None:
        class Process:
            def __init__(self) -> None:
                self.force: bool | None = None

            def terminate(self, force: bool = False) -> None:
                self.force = force

        process = Process()

        CommandExecutor._terminate(process)

        self.assertTrue(process.force)

    def test_cannot_cancel_when_idle(self) -> None:
        self.assertFalse(CommandExecutor().cancel())

    def test_ignores_input_race_when_process_exits(self) -> None:
        executor = CommandExecutor()
        executor._input_writer = Mock(side_effect=EOFError)

        self.assertFalse(executor.send_input("text"))

    @patch("terminalrunner.runner.sys.platform", "linux")
    @patch("terminalrunner.runner.os.killpg", create=True)
    def test_terminates_posix_process_group(self, killpg: Mock) -> None:
        class Process:
            pid = 123

        CommandExecutor._terminate(Process())

        killpg.assert_called_once_with(123, signal.SIGTERM)

    def test_escalates_termination_after_grace_period(self) -> None:
        executor = CommandExecutor()
        executor._termination_started_at = 1
        process = Mock()

        with patch.object(executor, "_kill") as kill:
            executor._escalate_termination_if_needed(process, 2)

        kill.assert_called_once_with(process)

    @unittest.skipIf(
        sys.platform == "win32", "pywinpty emits resource warnings during test teardown"
    )
    def test_sends_terminal_input_to_a_running_command(self) -> None:
        command = CommandDefinition(
            title="Test",
            description="Test command",
            executable=sys.executable,
            arguments=(
                "-c",
                "import sys; print('ready'); print(sys.stdin.readline().strip())",
            ),
            timeout_seconds=5,
        )
        executor = CommandExecutor()
        output: list[str] = []
        worker = threading.Thread(target=executor.run, args=(command, output.append))
        worker.start()

        deadline = time.monotonic() + 3
        while "ready" not in "".join(output) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(executor.send_input("answer\r"))
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertIn("answer", "".join(output))
