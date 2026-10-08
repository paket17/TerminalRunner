import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from terminalrunner.config import ConfigurationError, default_config_path, load_commands
from terminalrunner.models import CommandStep


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
    commands:
      - [echo, hello]
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].display_command, "echo hello")
        self.assertEqual(commands[0].commands, (CommandStep(argv=("echo", "hello")),))

    def test_rejects_a_command_without_a_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - commands:
      - [echo, hello]
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError, "Command #1 is missing fields: title"
            ):
                load_commands(path)

    def test_allows_a_missing_description(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: No description
    commands:
      - [echo]
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
    commands:
      - [echo]
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

    def test_loads_commands_without_parsing_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Greeting
    commands:
      - [echo, hello world]
      - [pwd]
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(
            commands[0].commands,
            (CommandStep(argv=("echo", "hello world")), CommandStep(argv=("pwd",))),
        )
        self.assertEqual(commands[0].display_command, "echo hello world\npwd")

    def test_preserves_literal_quotes_in_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Search
    commands:
      - [rg, '"exact value"', .]
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(
            commands[0].commands,
            (CommandStep(argv=("rg", '"exact value"', ".")),),
        )

    def test_loads_a_shell_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Shell command
    commands:
      - shell: echo first && echo second
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertEqual(
            commands[0].commands,
            (CommandStep(shell_command="echo first && echo second"),),
        )

    def test_rejects_a_non_list_commands_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid command
    commands: echo hello
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigurationError, "must be a non-empty list"):
                load_commands(path)

    def test_rejects_a_command_with_non_string_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid command
    commands:
      - [tool, true]
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError, "must contain only strings"
            ):
                load_commands(path)

    def test_rejects_directory_as_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                ConfigurationError, "Unable to read configuration"
            ):
                load_commands(Path(directory))

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

    def test_rejects_non_string_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid command
    1: value
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError, "unknown fields: 1"
            ):
                load_commands(path)

    def test_rejects_a_whitespace_only_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid command
    commands:
      - ['   ']
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigurationError, "empty executable"):
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

    def test_loads_command_with_ignore_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Command with ignore_errors
    ignore_errors: true
    commands:
      - [echo, hello]
""",
                encoding="utf-8",
            )

            commands = load_commands(path)

        self.assertTrue(commands[0].ignore_errors)

    def test_rejects_non_boolean_ignore_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "commands.yaml"
            path.write_text(
                """commands:
  - title: Invalid command
    ignore_errors: "yes"
    commands:
      - [echo, hello]
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConfigurationError,
                "ignore_errors for command 'Invalid command' must be a boolean",
            ):
                load_commands(path)
