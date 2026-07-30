import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch
from rich.text import Text
from terminalrunner.app import AnsiLog, CommandInfoPanel, TerminalRunnerApp
from textual.containers import Vertical
from terminalrunner.runner import CommandResult
from textual.geometry import Offset
from textual.selection import Selection
from textual.widgets import Button, Log, Static


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
            self.assertEqual(app.query_one("#status").render(), "TerminalRunner")
            self.assertEqual(app.query_one("#activity-indicator", Static).render(), " ")
            self.assertTrue(app.query_one("#command-0").has_class("is-selected"))
            self.assertEqual(
                app.query_one("#command-0", Button).tooltip, app.commands[0].title
            )
            await pilot.press("down")
            self.assertEqual(app.selected_index, 1)
            self.assertTrue(app.query_one("#command-1").has_class("is-selected"))
            self.assertFalse(app.query_one("#command-0").has_class("is-selected"))
            description = app.query_one("#description")
            self.assertEqual(
                description.render(),
                TerminalRunnerApp._description_preview(
                    app.commands[1].description, description.content_size.width
                ),
            )
            self.assertEqual(description.tooltip, app.commands[1].description)
            command_preview = app.query_one("#command-preview")
            self.assertEqual(
                command_preview.render(),
                TerminalRunnerApp._single_line_preview(
                    f"$ {app.commands[1].display_command}",
                    command_preview.content_size.width,
                ),
            )
            self.assertEqual(command_preview.tooltip, app.commands[1].display_command)

    async def test_limits_output_history(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)

        async with app.run_test():
            self.assertEqual(app.query_one("#output", Log).max_lines, 5_000)

    async def test_cancels_running_command_when_unmounted(self) -> None:
        app = TerminalRunnerApp(CATALOG_PATH, self.state_path)
        app.executor.cancel = Mock(return_value=True)

        async with app.run_test():
            pass

        app.executor.cancel.assert_called_once()

    async def test_f2_toggles_the_command_panel_width(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path, self.state_path)

        async with app.run_test() as pilot:
            sidebar = app.query_one("#sidebar", Vertical)
            self.assertFalse(sidebar.has_class("is-expanded"))

            await pilot.press("f2")
            self.assertTrue(sidebar.has_class("is-expanded"))
            self.assertEqual(
                app.active_bindings["f2"].binding.description, "toggle commands"
            )

            await pilot.press("f2")
            self.assertFalse(sidebar.has_class("is-expanded"))
            self.assertEqual(
                app.active_bindings["f2"].binding.description, "toggle commands"
            )

    async def test_separator_cannot_be_selected_or_run(self) -> None:
        config_path = Path(self.tempdir.name) / "commands.yaml"
        config_path.write_text(
            """commands:
  - title: First command
    executable: echo first
  - title: Tools
  - title: Second command
    executable: echo second
""",
            encoding="utf-8",
        )
        app = TerminalRunnerApp(config_path, self.state_path)

        async with app.run_test() as pilot:
            separator = app.query_one("#command-1", Button)
            self.assertTrue(separator.disabled)

            await pilot.press("down")
            self.assertEqual(app.selected_index, 2)

    async def test_restores_command_panel_and_theme(self) -> None:
        config_path = CATALOG_PATH
        state_path = self.state_path
        first_app = TerminalRunnerApp(config_path, state_path)
        theme = next(
            name for name in first_app.available_themes if name != first_app.theme
        )

        async with first_app.run_test() as pilot:
            first_app.theme = theme
            await pilot.press("f2")

        second_app = TerminalRunnerApp(config_path, state_path)
        async with second_app.run_test():
            self.assertEqual(second_app.theme, theme)
            self.assertTrue(
                second_app.query_one("#sidebar", Vertical).has_class("is-expanded")
            )
            self.assertEqual(
                second_app.active_bindings["f2"].binding.description, "toggle commands"
            )

    async def test_left_and_right_switch_columns_in_expanded_panel(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path, self.state_path)

        async with app.run_test() as pilot:
            await pilot.press("f2")
            await pilot.pause()
            rows = app.query_one("#command-list", Vertical).content_size.height
            self.assertLess(rows, len(app.commands))

            await pilot.press("right")
            self.assertEqual(app.selected_index, rows)

            await pilot.press("left")
            self.assertEqual(app.selected_index, 0)

    async def test_preserves_ansi_command_output(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test():
            output = app.query_one("#output", Log)
            with patch.object(output, "write") as write:
                app._write_output("\x1b[1t\x1b[31merror\x1b[0m")

        rendered = write.call_args.args[0]
        self.assertIsInstance(rendered, str)
        self.assertEqual(rendered, "\x1b[1t\x1b[31merror\x1b[0m")

    def test_ansi_log_parses_terminal_colors(self) -> None:
        text = Text.from_ansi("\x1b[31merror\x1b[0m")

        self.assertEqual(AnsiLog._process_line("\x1b[31merror\x1b[0m"), "error")
        self.assertTrue(text.spans)

    async def test_renders_ansi_color_in_command_output(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            output = app.query_one("#output", AnsiLog)
            output.write("\x1b[31merror\x1b[0m\n")
            await pilot.pause()

            style = output.render_line(0)._segments[0].style
            assert style is not None
            color = style.color
            assert color is not None
            self.assertEqual(color.name, "color(1)")

    async def test_output_focus_does_not_tint_its_background(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.click("#output")

            self.assertEqual(app.query_one("#output", Log).styles.background_tint.a, 0)

    async def test_does_not_scroll_output_when_viewing_older_lines(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test():
            output = app.query_one("#output", Log)
            with (
                patch.object(
                    type(output),
                    "is_vertical_scroll_end",
                    new_callable=PropertyMock,
                    return_value=False,
                ),
                patch.object(output, "write") as write,
            ):
                app._write_output("new output")

        self.assertFalse(write.call_args.kwargs["scroll_end"])

    def test_limits_description_preview_to_four_lines(self) -> None:
        preview = TerminalRunnerApp._description_preview(
            "one two three four five six seven", 5
        )

        self.assertEqual(preview, "one\ntwo\nthree\nfo...")

    def test_truncates_command_preview_to_one_line(self) -> None:
        preview = TerminalRunnerApp._single_line_preview(
            "$ executable --with-a-long-argument", 12
        )

        self.assertEqual(preview, "$ executa...")

    def test_writes_command_failure_to_output(self) -> None:
        app = TerminalRunnerApp()
        app._write_output = Mock()
        app._set_running_state = Mock()

        with patch.object(TerminalRunnerApp, "_timestamp", return_value="12:34:56"):
            app._finish_command(CommandResult(exit_code=1))

        app._write_output.assert_called_once_with(
            "\n[12:34:56] Command exited with code 1.\n\n"
        )
        app._set_running_state.assert_called_once_with(
            False, "Command exited with code 1."
        )

    async def test_updates_title_and_activity_indicator_while_running(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test():
            app._set_running_state(True, "Running: Test command")

            self.assertEqual(app.title, "TR | ⠋ Running: Test command")
            self.assertEqual(app.query_one("#activity-indicator", Static).render(), "⠋")

            app._set_running_state(False, "Command completed successfully.")

            self.assertEqual(app.title, "TerminalRunner")
            self.assertEqual(app.query_one("#activity-indicator", Static).render(), " ")

    async def test_shows_error_in_title_after_command_failure(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test():
            app._finish_command(CommandResult(exit_code=1))

            self.assertEqual(app.title, "TR | Command exited with code 1.")

    async def test_output_text_can_be_selected(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test():
            output = app.query_one("#output", Log)
            output.write("select this text\n")

            self.assertEqual(
                output.get_selection(
                    Selection.from_offsets(Offset(0, 0), Offset(6, 0))
                ),
                ("select", "\n"),
            )

    async def test_f1_shows_selected_command_information(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")

            panel = app.query_one(CommandInfoPanel)
            self.assertEqual(
                panel.query_one("#command-info-title").render(), app.commands[0].title
            )
            self.assertEqual(
                panel.query_one("#command-info-description").render(),
                app.commands[0].description,
            )
            self.assertEqual(
                panel.query_one("#command-info-command").render(),
                app.commands[0].display_command,
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
            self.assertTrue(app.query_one("#output", Log).display)

    async def test_command_information_closes_with_escape(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")
            await pilot.press("escape")

            self.assertFalse(app.query_one(CommandInfoPanel).display)
            self.assertTrue(app.query_one("#output", Log).display)

    async def test_command_information_does_not_block_command_buttons(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("f1")
            with patch.object(app, "action_run_selected") as run_selected:
                await pilot.click("#command-1")
                await pilot.pause()

            self.assertEqual(app.selected_index, 1)
            run_selected.assert_called_once()
            self.assertFalse(app.query_one(CommandInfoPanel).display)

    async def test_output_keeps_terminal_input_and_shortcuts_active(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)
        app.executor = Mock(is_running=True)
        app.executor.send_input.return_value = True

        async with app.run_test() as pilot:
            output = app.query_one("#output", Log)
            output.focus()
            await pilot.press("a")
            app.executor.send_input.assert_called_once_with("a")

            await pilot.press("ctrl+c")
            app.executor.send_input.assert_called_once_with("a")

            app.executor.is_running = False
            with patch.object(output, "clear") as clear:
                await pilot.press("ctrl+l")
                clear.assert_called_once()

    async def test_clicking_the_running_command_stops_it(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            app.command_running = True
            app.running_index = 0
            with patch.object(app, "action_stop") as stop:
                await pilot.click("#command-0")
                stop.assert_called_once()

    async def test_can_select_other_commands_while_a_command_is_running(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            app._set_running_state(True, "Running: Test command")

            await pilot.press("down")

            self.assertEqual(app.running_index, 0)
            self.assertEqual(app.selected_index, 1)
            self.assertTrue(app.query_one("#command-0", Button).has_class("is-running"))
            self.assertTrue(
                app.query_one("#command-1", Button).has_class("is-selected")
            )

    async def test_clicking_outside_output_restores_command_navigation(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            app.query_one("#output", Log).focus()
            await pilot.click("#description")
            self.assertIs(app.focused, app.query_one("#command-0", Button))
            await pilot.press("down")
            self.assertEqual(app.selected_index, 1)

    async def test_tab_cycles_only_through_commands(self) -> None:
        config_path = CATALOG_PATH
        app = TerminalRunnerApp(config_path)

        async with app.run_test() as pilot:
            await pilot.press("tab")
            self.assertEqual(app.selected_index, 1)
            self.assertIs(app.focused, app.query_one("#command-1", Button))

            await pilot.press("shift+tab")
            self.assertEqual(app.selected_index, 0)
            self.assertIs(app.focused, app.query_one("#command-0", Button))
