from datetime import datetime
from pathlib import Path
from collections.abc import Callable
import sys
import textwrap

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.events import Click, DescendantFocus, Enter, Key, Resize
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import Button, Footer, Log, Static
from rich.cells import cell_len
from rich.spinner import Spinner

from .config import ConfigurationError, default_config_path, load_commands
from .models import CommandDefinition
from .runner import CommandExecutor, CommandResult
from .state import AppState, default_state_path, load_state, save_state


class CommandInfoPanel(Vertical):
    def __init__(
        self, command: CommandDefinition, on_close: Callable[[], None]
    ) -> None:
        super().__init__()
        self.command = command
        self.on_close = on_close

    def compose(self) -> ComposeResult:
        with Vertical(id="command-info"):
            yield Static("COMMAND INFO", classes="panel-title")
            yield Static("TITLE", classes="info-label")
            yield Static(self.command.title, id="command-info-title")
            yield Static("DESCRIPTION", classes="info-label")
            yield Static(self.command.description, id="command-info-description")
            yield Static("COMMAND", classes="info-label")
            yield Static(self.command.display_command, id="command-info-command")
            yield Static("Esc or Close to return to output", classes="help-hint")
            yield Button("Close", id="command-info-close", classes="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "command-info-close":
            self.on_close()
            event.stop()

    def on_click(self, event: Click) -> None:
        if isinstance(event.widget, Button) and event.widget.id == "command-info-close":
            self.on_close()
            event.stop()


class AnsiLog(Log):
    """A Log that renders ANSI SGR sequences as Rich styles."""

    @classmethod
    def _process_line(cls, line: str) -> str:
        return Text.from_ansi(line.expandtabs()).plain

    def _render_line_strip(self, y: int, rich_style: Style) -> Strip:
        selection = self.text_selection
        if y in self._render_line_cache and selection is None:
            return self._render_line_cache[y]

        line_text = Text.from_ansi(self._lines[y].expandtabs())
        line_text.stylize_before(rich_style)

        if self.highlight:
            line_text = self.highlighter(line_text)
        if selection is not None:
            if (select_span := selection.get_span(y - self._clear_y)) is not None:
                start, end = select_span
                if end == -1:
                    end = len(line_text)
                line_text.stylize(
                    self.screen.get_component_rich_style("screen--selection"),
                    start,
                    end,
                )

        line = Strip(line_text.render(self.app.console), line_text.cell_len)
        if selection is not None:
            self._render_line_cache[y] = line
        return line

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = "\n".join(self._process_line(line) for line in self._lines)
        return selection.extract(text), "\n"


class TerminalRunnerApp(App[None]):
    CSS_PATH = "app.tcss"
    APP_NAME = "TerminalRunner"
    TITLE = APP_NAME
    SPINNER_NAME = "dots"
    SPINNER = Spinner(SPINNER_NAME)
    SPINNER_FRAMES = tuple(SPINNER.frames)
    SPINNER_INTERVAL = SPINNER.interval / 1_000
    SPINNER_WIDTH = max(cell_len(frame) for frame in SPINNER_FRAMES)
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit"),
        Binding("ctrl+r", "run_selected", "run"),
        Binding("ctrl+x", "stop", "stop", priority=True),
        Binding("ctrl+l", "clear_output", "clear"),
        Binding("f1", "show_command", "command info"),
        Binding("f2", "toggle_command_panel", "toggle commands"),
        Binding("escape", "close_command_info", show=False, priority=True),
        Binding("tab", "select_next", show=False, priority=True),
        Binding("shift+tab", "select_previous", show=False, priority=True),
        Binding("left", "select_left", show=False),
        Binding("right", "select_right", show=False),
        Binding("up", "select_previous", show=False),
        Binding("down", "select_next", show=False),
        # Text terminals send characters, not physical key codes. These are the
        # Russian-layout equivalents of the visible QWERTY shortcuts.
        Binding("ctrl+к", "run_selected", show=False),
        Binding("ctrl+ч", "stop", show=False),
        Binding("ctrl+д", "clear_output", show=False),
        Binding("ctrl+й", "quit", show=False),
    ]

    def __init__(
        self, config_path: Path | None = None, state_path: Path | None = None
    ) -> None:
        super().__init__()
        self.config_path = config_path or default_config_path()
        self.state_path = state_path or default_state_path()
        self.app_state = load_state(self.state_path)
        self.command_panel_expanded = self.app_state.command_panel_expanded
        if self.app_state.theme in self.available_themes:
            self.theme = self.app_state.theme
        self.executor = CommandExecutor()
        self.commands: tuple[CommandDefinition, ...] = ()
        self.selected_index: int | None = None
        self.running_index: int | None = None
        self.command_running = False
        self.status_message = self.APP_NAME
        self.spinner_frame_index = 0
        self.configuration_error: str | None = None
        try:
            self.commands = load_commands(self.config_path)
            self.selected_index = self._first_runnable_index()
        except ConfigurationError as error:
            self.configuration_error = str(error)

    def compose(self) -> ComposeResult:
        if self.configuration_error:
            yield Static(self.configuration_error, id="configuration-error")
            yield Footer(compact=True)
            return

        with Horizontal(id="body"):
            with Vertical(
                id="sidebar",
                classes="is-expanded" if self.command_panel_expanded else "",
            ):
                yield Static("COMMANDS", classes="panel-title")
                with Vertical(id="command-list"):
                    for index, command in enumerate(self.commands):
                        yield Button(
                            command.title,
                            id=f"command-{index}",
                            classes="command-button command-separator"
                            if command.is_separator
                            else "command-button",
                            tooltip=command.title,
                            disabled=command.is_separator,
                        )
                yield Static(id="description")
                yield Static(id="command-preview")
            with Vertical(id="details"):
                yield AnsiLog(id="output", max_lines=5_000)
                yield CommandInfoPanel(self.commands[0], self.action_close_command_info)
        with Horizontal(id="status-bar"):
            yield Static(" ", id="activity-indicator")
            yield Static("TerminalRunner", id="status")
        yield Footer(compact=True)

    def on_mount(self) -> None:
        self._set_window_title(self.APP_NAME)
        self.spinner_timer = self.set_interval(
            self.SPINNER_INTERVAL, self._advance_spinner
        )
        if self.configuration_error:
            return
        self.query_one(CommandInfoPanel).display = False
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).add_class(
                "is-selected"
            )
        self._show_selected_command()
        if self.command_panel_expanded:
            self.call_after_refresh(self._layout_expanded_commands)

    def on_unmount(self) -> None:
        self.executor.cancel()
        self.spinner_timer.pause()
        self._save_state()

    def on_resize(self, event: Resize) -> None:
        if not self.configuration_error:
            self._show_selected_command()
            if self.query_one("#sidebar", Vertical).has_class("is-expanded"):
                self.call_after_refresh(self._layout_expanded_commands)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "command-info-close":
            self.action_close_command_info()
            event.stop()
            return
        command_index = self._command_index_for_button(event.button)
        if command_index is None:
            return
        self.action_close_command_info()
        if self.command_running:
            if command_index == self.running_index:
                self.action_stop()
            else:
                self._select_index(command_index)
            return
        self._select_index(command_index)
        self.action_run_selected()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        if isinstance(event.widget, Button):
            command_index = self._command_index_for_button(event.widget)
            if command_index is not None:
                self._select_index(command_index)

    def on_enter(self, event: Enter) -> None:
        if isinstance(event.node, Button):
            command_index = self._command_index_for_button(event.node)
            if command_index is not None:
                self._select_index(command_index)

    def on_click(self, event: Click) -> None:
        if self.configuration_error:
            return
        if isinstance(event.widget, (Button, Footer, Log)):
            return
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).focus()

    def on_key(self, event: Key) -> None:
        if (
            self.focused is not self.query_one("#output", Log)
            or not self.executor.is_running
        ):
            return
        text = self._terminal_input_for_key(event)
        if text is not None and self.executor.send_input(text):
            event.stop()

    def action_run_selected(self) -> None:
        if self.configuration_error or self.command_running:
            return
        command = self._selected_command()
        if command is None or command.is_separator:
            return
        self._write_output(
            f"\n[{self._timestamp()}] Starting: $ {command.display_command}\n\n"
        )
        self._set_running_state(True, f"Running: {command.title}")
        self._run_command(command)

    def action_stop(self) -> None:
        if self.executor.cancel():
            self._set_status("Stopping command...")

    def action_clear_output(self) -> None:
        if not self.configuration_error:
            self.query_one("#output", Log).clear()

    def action_show_command(self) -> None:
        command = self._selected_command()
        if command is not None and not command.is_separator:
            panel = self.query_one(CommandInfoPanel)
            panel.query_one("#command-info-title", Static).update(command.title)
            panel.query_one("#command-info-description", Static).update(
                command.description
            )
            panel.query_one("#command-info-command", Static).update(
                command.display_command
            )
            self.query_one("#output", Log).display = False
            panel.display = True

    def action_toggle_command_panel(self) -> None:
        if self.configuration_error:
            return
        sidebar = self.query_one("#sidebar", Vertical)
        command_list = self.query_one("#command-list", Vertical)
        expanded = not sidebar.has_class("is-expanded")
        self.command_panel_expanded = expanded
        sidebar.set_class(expanded, "is-expanded")
        if expanded:
            self.call_after_refresh(self._layout_expanded_commands)
        else:
            command_list.styles.grid_size_columns = 1
            self._order_command_buttons(tuple(range(len(self.commands))))
        self._save_state()

    def _save_state(self) -> None:
        save_state(
            self.state_path,
            AppState(
                theme=self.theme, command_panel_expanded=self.command_panel_expanded
            ),
        )

    def _layout_expanded_commands(self) -> None:
        command_list = self.query_one("#command-list", Vertical)
        rows = max(command_list.content_size.height, 1)
        if len(self.commands) <= rows:
            command_list.styles.grid_size_columns = 1
            self._order_command_buttons(tuple(range(len(self.commands))))
            return
        command_list.styles.grid_size_columns = 2
        order = [
            index
            for row in range(rows)
            for index in (row, row + rows)
            if index < len(self.commands)
        ]
        order.extend(range(rows * 2, len(self.commands)))
        self._order_command_buttons(tuple(order))

    def _order_command_buttons(self, order: tuple[int, ...]) -> None:
        command_list = self.query_one("#command-list", Vertical)
        buttons = {
            index: self.query_one(f"#command-{index}", Button) for index in order
        }
        for position, index in enumerate(order):
            button = buttons[index]
            if command_list.children[position] is not button:
                command_list.move_child(button, before=command_list.children[position])

    def action_close_command_info(self) -> None:
        if self.configuration_error:
            return
        self.query_one("#output", Log).display = True
        self.query_one(CommandInfoPanel).display = False

    def action_select_previous(self) -> None:
        self._select_adjacent_command(-1)

    def action_select_next(self) -> None:
        self._select_adjacent_command(1)

    def action_select_left(self) -> None:
        self._select_horizontal_command(-1)

    def action_select_right(self) -> None:
        self._select_horizontal_command(1)

    @work(thread=True, exclusive=True)
    def _run_command(self, command: CommandDefinition) -> None:
        result = self.executor.run(command, self._write_output_from_worker)
        self.call_from_thread(self._finish_command, result)

    def _write_output_from_worker(self, text: str) -> None:
        self.call_from_thread(self._write_output, text)

    def _write_output(self, text: str) -> None:
        output = self.query_one("#output", Log)
        output.write(
            text,
            scroll_end=output.is_vertical_scroll_end,
        )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @staticmethod
    def _terminal_input_for_key(event: Key) -> str | None:
        if event.key == "ctrl+c":
            return None
        special_keys = {
            "enter": "\r",
            "tab": "\t",
            "backspace": "\x7f",
            "delete": "\x1b[3~",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "right": "\x1b[C",
            "left": "\x1b[D",
            "ctrl+d": "\x04",
            "ctrl+z": "\x1a",
        }
        return special_keys.get(event.key, event.character)

    def _finish_command(self, result: CommandResult) -> None:
        message = self._result_message(result)
        self._write_output(f"\n[{self._timestamp()}] {message}\n\n")
        self._set_running_state(False, message)
        if self._result_is_error(result):
            self._set_window_title(f"TR | {message}")

    def _select_index(self, index: int) -> None:
        if self.commands[index].is_separator:
            return
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).remove_class(
                "is-selected"
            )
        self.selected_index = index
        self.query_one(f"#command-{index}", Button).add_class("is-selected")
        self._show_selected_command()

    def _select_adjacent_command(self, direction: int) -> None:
        if not self.commands or self.selected_index is None:
            return
        current_index = self.selected_index
        for _ in range(len(self.commands)):
            current_index = (current_index + direction) % len(self.commands)
            if not self.commands[current_index].is_separator:
                self._select_index(current_index)
                break
        self.query_one(f"#command-{self.selected_index}", Button).focus()

    def _select_horizontal_command(self, direction: int) -> None:
        if (
            self.configuration_error
            or not self.command_panel_expanded
            or self.selected_index is None
        ):
            return
        rows = max(self.query_one("#command-list", Vertical).content_size.height, 1)
        target_index = self.selected_index + direction * rows
        if (
            0 <= target_index < len(self.commands)
            and not self.commands[target_index].is_separator
        ):
            self._select_index(target_index)
            self.query_one(f"#command-{target_index}", Button).focus()

    def _show_selected_command(self) -> None:
        command = self._selected_command()
        if command is None:
            return
        description = self.query_one("#description", Static)
        description.update(
            self._description_preview(
                command.description, description.content_size.width
            )
        )
        description.tooltip = command.description
        command_preview = self.query_one("#command-preview", Static)
        command_preview.update(
            self._single_line_preview(
                f"$ {command.display_command}", command_preview.content_size.width
            )
        )
        command_preview.tooltip = command.display_command

    @staticmethod
    def _description_preview(description: str, width: int) -> str:
        if width <= 0:
            return description
        lines = textwrap.wrap(
            description, width=width, break_long_words=True, break_on_hyphens=False
        )
        if len(lines) <= 4:
            return "\n".join(lines)
        return "\n".join([*lines[:3], f"{lines[3][: max(width - 3, 0)].rstrip()}..."])

    @staticmethod
    def _single_line_preview(text: str, width: int) -> str:
        if width <= 0 or len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return f"{text[: width - 3]}..."

    def _set_running_state(self, running: bool, status: str) -> None:
        self.command_running = running
        if running:
            self.running_index = self.selected_index
        if self.running_index is not None:
            button = self.query_one(f"#command-{self.running_index}", Button)
            button.set_class(running, "is-running")
        if not running:
            self.running_index = None
        if running:
            self.spinner_frame_index = 0
        self._update_spinner()
        self._set_window_title(
            self._status_window_title(status) if running else self.APP_NAME
        )
        self._set_status(status)

    def _set_window_title(self, title: str) -> None:
        self.title = title
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except OSError:
            pass

    def _set_status(self, message: str) -> None:
        self.status_message = message
        self.query_one("#status", Static).update(message)

    def _advance_spinner(self) -> None:
        if not self.command_running:
            return
        self.spinner_frame_index = (self.spinner_frame_index + 1) % len(
            self.SPINNER_FRAMES
        )
        self._update_spinner()
        self._set_window_title(self._status_window_title(self.status_message))

    def _update_spinner(self) -> None:
        frame = (
            self.SPINNER_FRAMES[self.spinner_frame_index]
            if self.command_running
            else ""
        )
        try:
            self.query_one("#activity-indicator", Static).update(
                frame.ljust(self.SPINNER_WIDTH)
            )
        except NoMatches:
            # A scheduled tick may run after the screen's children are removed.
            return

    def _status_window_title(self, status: str) -> str:
        return f"TR | {self.SPINNER_FRAMES[self.spinner_frame_index]} {status}"

    def _selected_command(self) -> CommandDefinition | None:
        if self.selected_index is None:
            return None
        return self.commands[self.selected_index]

    def _first_runnable_index(self) -> int | None:
        return next(
            (
                index
                for index, command in enumerate(self.commands)
                if not command.is_separator
            ),
            None,
        )

    def _command_index_for_button(self, button: Button) -> int | None:
        if button.id is None or not button.id.startswith("command-"):
            return None
        try:
            index = int(button.id.removeprefix("command-"))
        except (ValueError, IndexError):
            return None
        if not 0 <= index < len(self.commands) or self.commands[index].is_separator:
            return None
        return index

    @staticmethod
    def _result_message(result: CommandResult) -> str:
        if result.error:
            return result.error
        if result.cancelled:
            return "Command stopped by user."
        if result.timed_out:
            return "Command timed out."
        if result.exit_code == 0:
            return "Command completed successfully."
        return f"Command exited with code {result.exit_code}."

    @staticmethod
    def _result_is_error(result: CommandResult) -> bool:
        return (
            result.error is not None
            or result.timed_out
            or result.exit_code not in (0, None)
        )
