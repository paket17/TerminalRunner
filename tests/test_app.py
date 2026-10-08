import asyncio
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from terminalrunner.app import CommandInfoPanel, TerminalRunnerApp
from terminalrunner.models import CommandDefinition, CommandStep
from terminalrunner.runner import CommandResult
from textual.command import CommandPalette
from textual.events import MouseScrollDown
from textual.widgets import Button


CATALOG_PATH = Path(__file__).parents[1] / "terminalrunner" / "commands.yaml"


class TerminalRunnerAppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.state_path = Path(self.tempdir.name) / "state.json"
        self.state_path_patch = patch(
            "terminalrunner.app.default_state_path", return_value=self.state_path
        )
        self.state_path_patch.start()

    def tearDown(self) -> None:
        self.state_path_patch.stop()
        self.tempdir.cleanup()

    async def test_loads_the_configured_command_catalog(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            self.assertTrue(app.commands)
            self.assertEqual(app.title, "TerminalRunner")
            self.assertEqual(
                app.query_one("#status-message").render(), "  "
            )
            self.assertTrue(app.query_one("#command-1").has_class("is-selected"))
            self.assertEqual(
                app.query_one("#command-1", Button).tooltip, app.commands[1].title
            )
            await pilot.press("down")
            self.assertEqual(app.selected_index, 2)
            self.assertTrue(app.query_one("#command-2").has_class("is-selected"))
            self.assertFalse(app.query_one("#command-1").has_class("is-selected"))
            self.assertEqual(
                app.query_one("#command-summary-description").render(),
                app.commands[2].description,
            )
            self.assertEqual(
                app.query_one("#command-summary-description").tooltip,
                app.commands[2].description,
            )
            self.assertEqual(
                app.query_one("#command-summary-command").render(),
                app.commands[2].display_command,
            )
            self.assertEqual(
                app.query_one("#command-summary-command").tooltip,
                app.commands[2].display_command,
            )

    async def test_commands_fill_columns_from_top_to_bottom(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path, self.state_path)

        async with app.run_test(size=(80, 10)) as pilot:
            await pilot.pause()

            self.assertGreater(app.command_columns, 1)
            columns = list(app.query(".command-column"))
            self.assertEqual(len(columns), app.command_columns)
            self.assertEqual(
                [button.id for button in columns[0].query(Button)],
                [f"command-{index}" for index in range(app.command_rows)],
            )
            self.assertEqual(
                columns[1].query_one(Button).id,
                f"command-{app.command_rows}",
            )
            last_button = list(columns[0].query(Button))[-1]
            self.assertLessEqual(
                last_button.region.bottom,
                app.query_one("#command-list").region.bottom,
            )

    async def test_reflows_commands_when_the_window_is_resized(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test(size=(80, 15)) as pilot:
            await pilot.pause()
            initial_rows = app.command_rows

            await pilot.resize_terminal(80, 30)
            await pilot.pause()

            self.assertGreater(app.command_rows, initial_rows)
            self.assertEqual(
                app.command_columns,
                -(-len(app.commands) // app.command_rows),
            )

    async def test_resize_resets_command_list_scroll_target(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test(size=(50, 10)) as pilot:
            await pilot.pause()
            command_list = app.query_one("#command-list")
            command_list._on_mouse_scroll_down(
                MouseScrollDown(command_list, 0, 0, 0, 1, 0, False, False, False)
            )
            self.assertGreater(command_list.scroll_target_x, 0)

            await pilot.resize_terminal(50, 40)
            await pilot.pause()

            self.assertEqual(app.command_columns, 1)
            self.assertEqual(command_list.scroll_x, 0)
            self.assertEqual(command_list.scroll_target_x, 0)
            self.assertEqual(
                len(list(command_list.query(Button))),
                len(app.commands),
            )

    async def test_separator_cannot_be_selected_or_run(self) -> None:
        config_path = Path(self.tempdir.name) / "commands.yaml"
        config_path.write_text(
            """commands:
  - title: First command
    commands:
      - [echo, first]
  - title: Tools
  - title: Second command
    commands:
      - [echo, second]
""",
            encoding="utf-8",
        )
        app = TerminalRunnerApp(config_path, self.state_path)

        async with app.run_test() as pilot:
            separator = app.query_one("#command-1", Button)
            self.assertTrue(separator.disabled)

            await pilot.press("down")
            self.assertEqual(app.selected_index, 2)

    async def test_restores_theme(self) -> None:
        config_path = CATALOG_PATH
        state_path = self.state_path
        first_app = TerminalRunnerApp(config_path, state_path)
        theme = next(
            name for name in first_app.available_themes if name != first_app.theme
        )

        async with first_app.run_test():
            first_app.theme = theme

        second_app = TerminalRunnerApp(config_path, state_path)
        async with second_app.run_test():
            self.assertEqual(second_app.theme, theme)

    async def test_changing_theme_keeps_command_buttons_visible(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await asyncio.sleep(0.5)
            await pilot.press("ctrl+end", "enter")
            await asyncio.sleep(0.5)
            await pilot.press("ctrl+home", "enter")
            await asyncio.sleep(0.5)

            self.assertNotIsInstance(app.screen, CommandPalette)
            self.assertEqual(len(list(app.query(".command-button"))), len(app.commands))
            button = app.query_one("#command-1", Button)
            self.assertTrue(button.display)
            self.assertGreater(button.size.width, 0)
            self.assertGreater(button.size.height, 0)
            self.assertIs(app.focused, button)

    async def test_left_and_right_switch_columns(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path, self.state_path)

        async with app.run_test(size=(80, 10)) as pilot:
            await pilot.pause()
            self.assertGreater(app.command_columns, 1)

            await pilot.press("right")
            self.assertEqual(app.selected_index, 1 + app.command_rows)

            await pilot.press("left")
            self.assertEqual(app.selected_index, 1)

    async def test_left_and_right_wrap_between_columns(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            command_rows = app.command_rows
            app.commands = tuple(
                CommandDefinition(
                    title=f"Command {index}",
                    description="",
                    commands=(CommandStep(argv=("echo",)),),
                )
                for index in range(command_rows * 3)
            )
            app.selected_index = 1
            app.command_rows = 0
            await app._layout_commands(command_rows)

            await pilot.press("right", "right", "right")
            self.assertEqual(app.selected_index, 1)

            await pilot.press("left")
            self.assertEqual(app.selected_index, 1 + command_rows * 2)

    async def test_down_cycles_through_all_runnable_commands(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test() as pilot:
            await pilot.press(
                *(
                    "down"
                    for command in app.commands
                    if not command.is_separator
                )
            )

            self.assertEqual(app.selected_index, 1)

    async def test_command_summary_does_not_overlap_the_status_bar(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test(size=(80, 10)):
            command_line = app.query_one("#command-summary-command")
            status_bar = app.query_one("#status-bar")

            self.assertLessEqual(command_line.region.bottom, status_bar.region.y)

    async def test_left_and_right_select_command_above_separator(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            command_rows = app.command_rows
            app.commands = tuple(
                CommandDefinition(
                    title=f"Command {index}",
                    description="",
                    commands=(CommandStep(argv=("echo",)),),
                    is_separator=index == command_rows + 1,
                )
                for index in range(command_rows * 3)
            )
            app.selected_index = 1
            app.command_rows = 0
            await app._layout_commands(command_rows)

            await pilot.press("right")

            self.assertEqual(app.selected_index, command_rows)

    async def test_left_and_right_skip_separator_only_columns(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.pause()
            command_rows = app.command_rows
            app.commands = tuple(
                CommandDefinition(
                    title=f"Command {index}",
                    description="",
                    commands=(CommandStep(argv=("echo",)),),
                    is_separator=command_rows <= index < command_rows * 2,
                )
                for index in range(command_rows * 3)
            )
            app.selected_index = 1
            app.command_rows = 0
            await app._layout_commands(command_rows)

            await pilot.press("right")

            self.assertEqual(app.selected_index, command_rows * 2 + 1)

    def test_marks_command_failure(self) -> None:
        app = TerminalRunnerApp()
        app._set_status = Mock()

        app._finish_command(
            CommandResult(exit_code=1),
            datetime(2026, 8, 14, 9, 30),
            datetime(2026, 8, 14, 9, 31),
            "Full command description.",
        )

        app._set_status.assert_called_once_with(
            "🕒 09:31:00\n❌ View command output in the terminal.",
            "Started 09:30:00 | Finished 09:31:00 | Duration 0:01:00",
            "status-error",
        )

    async def test_marks_title_after_command_failure(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test():
            app._finish_command(CommandResult(exit_code=1))

            self.assertEqual(app.title, "❌ TerminalRunner")

    async def test_f1_shows_selected_command_information(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")

            panel = app.query_one(CommandInfoPanel)
            self.assertEqual(
                panel.query_one("#command-info-title").render(), app.commands[1].title
            )
            self.assertEqual(
                panel.query_one("#command-info-description").render(),
                app.commands[1].description,
            )
            self.assertEqual(
                panel.query_one("#command-info-command").render(),
                app.commands[1].display_command,
            )

    async def test_command_information_closes_from_its_button(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")
            await pilot.pause()
            await pilot.click("#command-info-close")
            await pilot.pause()

            self.assertFalse(app.query_one(CommandInfoPanel).display)

    async def test_command_information_closes_with_escape(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")
            await pilot.press("escape")

            self.assertFalse(app.query_one(CommandInfoPanel).display)

    async def test_command_information_blocks_navigation_and_closes_with_enter(
        self,
    ) -> None:
        app = TerminalRunnerApp(CATALOG_PATH)
        app.executor.run_in_terminal = Mock()

        async with app.run_test() as pilot:
            await pilot.press("f1")
            await pilot.press("down", "right")
            await pilot.click("#command-info-title")

            self.assertEqual(app.selected_index, 1)
            self.assertTrue(app.query_one(CommandInfoPanel).display)
            self.assertIs(app.focused, app.query_one("#command-info-close", Button))

            await pilot.press("enter")

            self.assertFalse(app.query_one(CommandInfoPanel).display)
            self.assertIs(app.focused, app.query_one("#command-1", Button))

        app.executor.run_in_terminal.assert_not_called()

    async def test_ctrl_d_opens_terminal_from_command_information(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH)
        app.executor.open_terminal = Mock(return_value=CommandResult(exit_code=0))

        async with app.run_test() as pilot:
            await pilot.press("f1")
            with patch.object(app, "suspend") as suspend:
                await pilot.press("ctrl+d")

        suspend.assert_called_once()
        app.executor.open_terminal.assert_called_once_with()

    async def test_f1_toggles_command_information(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH)

        async with app.run_test() as pilot:
            await pilot.press("f1")
            self.assertTrue(app.query_one(CommandInfoPanel).display)

            await pilot.press("f1")

            self.assertFalse(app.query_one(CommandInfoPanel).display)
            self.assertIs(app.focused, app.query_one("#command-1", Button))

    async def test_command_information_replaces_command_list_and_keeps_summary(
        self,
    ) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")
            self.assertFalse(app.query_one("#command-list").display)
            panel = app.query_one(CommandInfoPanel)
            summary = app.query_one("#command-summary")
            self.assertTrue(panel.display)
            self.assertTrue(summary.display)
            self.assertEqual(panel.region.bottom, summary.region.y)

    async def test_command_opens_a_terminal_and_returns_to_the_interface(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        def run_command(_: CommandDefinition) -> CommandResult:
            self.assertEqual(app.title, "⠋ TerminalRunner")
            return CommandResult(exit_code=0)

        app.executor.run_in_terminal = Mock(side_effect=run_command)

        async with app.run_test():
            with patch.object(app, "suspend") as suspend:
                app.action_run_selected()
            self.assertEqual(
                str(app.query_one("#status-time").render())[:2],
                "🕒 ",
            )
            selected_command = app._selected_command()
            assert selected_command is not None
            tooltip = str(app.query_one("#status-message").tooltip or "")
            self.assertIn("Started ", tooltip)
            self.assertIn("Finished ", tooltip)
            self.assertIn("Duration ", tooltip)
            self.assertNotIn(selected_command.description, tooltip)
            self.assertEqual(app.query_one("#status-time").tooltip, tooltip)
            self.assertEqual(app.title, "✅ TerminalRunner")

        suspend.assert_called_once()
        selected_command = app._selected_command()
        assert selected_command is not None
        app.executor.run_in_terminal.assert_called_once_with(selected_command)

    async def test_ctrl_d_opens_an_interactive_terminal(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH)
        app.executor.open_terminal = Mock(return_value=CommandResult(exit_code=0))

        async with app.run_test() as pilot:
            with patch.object(app, "suspend") as suspend:
                await pilot.press("ctrl+d")

        suspend.assert_called_once()
        app.executor.open_terminal.assert_called_once_with()

    async def test_ctrl_cyrillic_d_opens_an_interactive_terminal(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH)
        app.executor.open_terminal = Mock(return_value=CommandResult(exit_code=0))

        async with app.run_test() as pilot:
            with patch.object(app, "suspend") as suspend:
                await pilot.press("ctrl+в")

        suspend.assert_called_once()
        app.executor.open_terminal.assert_called_once_with()

    async def test_clicking_background_restores_command_navigation(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.click(".panel-title")
            self.assertIs(app.focused, app.query_one("#command-1", Button))
            await pilot.press("down")
            self.assertEqual(app.selected_index, 2)

    async def test_tab_cycles_only_through_commands(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("tab")
            self.assertEqual(app.selected_index, 2)
            self.assertIs(app.focused, app.query_one("#command-2", Button))

            await pilot.press("shift+tab")
            self.assertEqual(app.selected_index, 1)
            self.assertIs(app.focused, app.query_one("#command-1", Button))
