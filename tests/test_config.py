import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from terminalrunner.config import ConfigurationError, default_config_path, load_commands


class CommandConfigurationTests(unittest.TestCase):
    def test_frozen_application_uses_config_next_to_executable(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("terminalrunner.config.sys.frozen", True, create=True),
            patch(
                "terminalrunner.config.sys.executable", r"D:\Apps\TerminalRunner.exe"
            ),
        ):
            path = default_config_path()

        self.assertEqual(path, Path(r"D:\Apps\commands.yaml"))

    def test_environment_config_has_priority(self) -> None:
        with patch.dict(
            "os.environ", {"TERMINALRUNNER_CONFIG": "custom.yaml"}, clear=True
        ):
            self.assertEqual(default_config_path(), Path("custom.yaml"))

    def test_current_directory_config_overrides_packaged_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.touch()
            with (
                patch.dict("os.environ", {}, clear=True),
                patch("terminalrunner.config.Path.cwd", return_value=Path(directory)),
            ):
                self.assertEqual(default_config_path(), path)

    def test_uses_packaged_catalog_when_no_external_config_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict("os.environ", {}, clear=True),
                patch("terminalrunner.config.Path.cwd", return_value=Path(directory)),
            ):
                path = default_config_path()

        self.assertEqual(
            path, Path(__file__).parents[1] / "terminalrunner" / "commands.yaml"
        )

    def test_loads_command_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Hello
    description: Print a greeting
    executable: echo hello
    timeout_seconds: 5
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].display_command, "echo hello")
        self.assertIsNone(commands[0].shell_command)
        self.assertEqual(commands[0].timeout_seconds, 5)

    def test_allows_a_missing_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: No description
    executable: echo
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(commands[0].description, "")

    def test_allows_an_empty_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Empty description
    description:
    executable: echo
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(commands[0].description, "")

    def test_loads_a_title_only_entry_as_a_separator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Build tools
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertTrue(commands[0].is_separator)
        self.assertEqual(commands[0].display_command, "")

    def test_splits_quoted_arguments_in_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Greeting
    executable: echo \"hello world\"
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(commands[0].executable, "echo")
        self.assertEqual(commands[0].arguments, ("hello world",))

    def test_loads_folded_command_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Chained command
    executable: >-
      echo first
      && echo second
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(commands[0].display_command, "echo first && echo second")
        self.assertEqual(commands[0].shell_command, "echo first && echo second")

    def test_loads_explicit_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Pipeline
    executable: echo hello | grep hello
    shell: true
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(commands[0].shell_command, "echo hello | grep hello")

    def test_preserves_windows_path_separators(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Windows tool
    executable: C:\\Tools\\runner.exe --mode local
""",
                encoding="utf-8",
            )

            with patch("terminalrunner.config.sys.platform", "win32"):
                commands = load_commands(path)

        self.assertEqual(commands[0].executable, r"C:\Tools\runner.exe")

    def test_rejects_boolean_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid timeout
    executable: echo hello
    timeout_seconds: true
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigurationError, "timeout_seconds"):
                load_commands(path)

    def test_rejects_directory_as_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ConfigurationError, "Unable to read configuration"
            ):
                load_commands(Path(directory))

    def test_rejects_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Legacy directory
    executable: echo hello
    working_directory: .
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError, "unknown fields: working_directory"
            ):
                load_commands(path)

    def test_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid command
    executabl: echo hello
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError, "unknown fields: executabl"
            ):
                load_commands(path)

    def test_rejects_separator_with_command_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid separator
    description: This is not a separator
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError, "Separator 'Invalid separator'"
            ):
                load_commands(path)
