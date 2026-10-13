from collections.abc import Callable
from datetime import datetime
from itertools import cycle
from pathlib import Path
import sys
from threading import Event, Thread

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal, Vertical
from textual.events import (
    Click,
    DescendantFocus,
    Enter,
    MouseScrollDown,
    MouseScrollUp,
    Resize,
)
from textual.timer import Timer
from textual.widgets import Button, Footer, Static

from .config import ConfigurationError, default_config_path, load_commands
from .models import CommandDefinition
from .runner import CommandExecutor, CommandResult
from .state import AppState, default_state_path, load_state, save_state


class CommandInfoPanel(Vertical):
    def __init__(
        self, command: CommandDefinition, on_close: Callable[[], None]
    ) -> None:
        super().__init__(id="command-details")
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
            yield Static("F1, Esc, Enter, or Close to return", classes="help-hint")
            yield Button("Close", id="command-info-close", classes="close-button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "command-info-close":
            self.on_close()
            event.stop()


class CommandGrid(Horizontal):
    """A horizontally scrolling command grid controlled by the mouse wheel."""

    def _on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if event.ctrl or event.shift:
            super()._on_mouse_scroll_up(event)
        elif self._scroll_left_for_pointer(animate=False):
            event.stop()

    def _on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if event.ctrl or event.shift:
            super()._on_mouse_scroll_down(event)
        elif self._scroll_right_for_pointer(animate=False):
            event.stop()


class TerminalRunnerApp(App[None]):
    CSS_PATH = "app.tcss"
    APP_NAME = "TerminalRunner"
    TITLE = APP_NAME
    BINDINGS = [
        Binding("ctrl+d", "open_terminal", "terminal"),
        Binding("ctrl+q", "quit", "quit"),
        Binding("f1", "show_command", "command info"),
        Binding("escape", "close_command_info", show=False),
        Binding("tab", "select_next", show=False, priority=True),
        Binding("shift+tab", "select_previous", show=False, priority=True),
        Binding("left", "select_left", show=False),
        Binding("right", "select_right", show=False),
        Binding("up", "select_previous", show=False),
        Binding("down", "select_next", show=False),
        # Text terminals send characters, not physical key codes. These are the
        # Russian-layout equivalents of the visible QWERTY shortcuts.
        Binding("ctrl+в", "open_terminal", show=False),
        Binding("ctrl+й", "quit", show=False),
    ]

    def __init__(
        self, config_path: Path | None = None, state_path: Path | None = None
    ) -> None:
        super().__init__()
        bindings = self._bindings.key_to_bindings
        terminal_binding = bindings.pop("ctrl+d")
        self._bindings.key_to_bindings = {"ctrl+d": terminal_binding, **bindings}
        self.config_path = config_path or default_config_path()
        self.state_path = state_path or default_state_path()
        self.app_state = load_state(self.state_path)
        if self.app_state.theme in self.available_themes:
            self.theme = self.app_state.theme
        self.executor = CommandExecutor()
        self.commands: tuple[CommandDefinition, ...] = ()
        self.selected_index: int | None = None
        self.command_columns = 0
        self.command_rows = 0
        self.command_layout_ready = False
        self._theme_restore_timer: Timer | None = None
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

        with Vertical(id="body"):
            yield Static("Commands", classes="panel-title")
            yield CommandGrid(id="command-list")
            yield CommandInfoPanel(self.commands[0], self.action_close_command_info)
        with Vertical(id="command-summary"):
            with Vertical(id="command-summary-content"):
                with Horizontal(classes="command-summary-row"):
                    yield Static("Description", classes="command-summary-label")
                    yield Static("", id="command-summary-description")
                with Horizontal(classes="command-summary-row"):
                    yield Static("$", classes="command-summary-label command-prompt")
                    yield Static("", id="command-summary-command")
        with Horizontal(id="status-bar"):
            with Vertical(id="status"):
                yield Static("", id="status-spacer")
                with Horizontal(id="status-line"):
                    yield Static("  ", id="status-message")
                    yield Static("", id="status-space")
                    yield Static("", id="status-time")
        yield Footer(compact=True)

    async def on_mount(self) -> None:
        self._set_window_title(self.APP_NAME)
        if self.configuration_error:
            return
        self.query_one(CommandInfoPanel).display = False
        await self._layout_commands(self._command_rows_for_height(self.size.height))
        self._update_command_summary()
        self.command_layout_ready = True

    def on_unmount(self) -> None:
        if self._theme_restore_timer is not None:
            self._theme_restore_timer.stop()
        self._save_state()

    async def on_resize(self, event: Resize) -> None:
        if not self.configuration_error and self.command_layout_ready:
            await self._layout_commands(
                self._command_rows_for_height(event.size.height)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        command_index = self._command_index_for_button(event.button)
        if command_index is None:
            return
        self.action_close_command_info()
        self._select_index(command_index)
        self.action_run_selected()

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        if isinstance(event.widget, Button):
            command_index = self._command_index_for_button(event.widget)
            if command_index is not None:
                self._select_index(command_index)

    def _watch_theme(self, theme_name: str) -> None:
        super()._watch_theme(theme_name)
        if getattr(self, "command_layout_ready", False):
            # Theme commands run while their modal palette is being dismissed.
            # Wait for that screen to leave the stack before restoring the list.
            self._theme_restore_timer = self.set_timer(
                0.05, self._restore_command_focus
            )

    def _restore_command_focus(self) -> None:
        if self.configuration_error:
            return
        try:
            command_info = self.query_one(CommandInfoPanel)
            command_list = self.query_one("#command-list", CommandGrid)
        except NoMatches:
            return
        if command_info.display:
            return
        command_list.display = True
        command_list.styles.visibility = "visible"
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).focus()

    def on_enter(self, event: Enter) -> None:
        if isinstance(event.node, Button):
            command_index = self._command_index_for_button(event.node)
            if command_index is not None:
                self._select_index(command_index)

    def on_click(self, event: Click) -> None:
        if self.configuration_error or self._command_info_is_open():
            return
        if isinstance(event.widget, (Button, Footer)):
            return
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).focus()

    def action_run_selected(self) -> None:
        if self.configuration_error or self._command_info_is_open():
            return
        command = self._selected_command()
        if command is None or command.is_separator:
            return
        started_at = datetime.now()
        self._set_status("⏳", command.description)
        self._set_window_title(f"⠋ {self.APP_NAME}")
        spinner_stop = Event()
        spinner = Thread(
            target=self._spin_window_title,
            args=(spinner_stop,),
            daemon=True,
        )
        spinner.start()
        try:
            with self.suspend():
                result = self.executor.run_in_terminal(command)
        finally:
            spinner_stop.set()
            spinner.join()
        self._finish_command(
            result,
            started_at,
            datetime.now(),
            command.description,
        )

    def action_open_terminal(self) -> None:
        with self.suspend():
            result = self.executor.open_terminal()
        if result.error is not None:
            self._finish_command(result)
        else:
            self._set_window_title(self.APP_NAME)

    def action_show_command(self) -> None:
        if self._command_info_is_open():
            self.action_close_command_info()
            return
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
            self.query_one("#command-list", CommandGrid).display = False
            panel.display = True
            panel.query_one("#command-info-close", Button).focus()

    def _save_state(self) -> None:
        save_state(self.state_path, AppState(theme=self.theme))

    async def _layout_commands(self, command_rows: int) -> None:
        command_list = self.query_one("#command-list", CommandGrid)
        if command_rows == self.command_rows:
            return

        self.command_rows = command_rows
        self.command_columns = -(-len(self.commands) // self.command_rows)
        command_list.scroll_to(x=0, animate=False, immediate=True)
        columns: list[Vertical] = []
        for column_index in range(self.command_columns):
            first_index = column_index * self.command_rows
            buttons = tuple(
                Button(
                    command.title,
                    id=f"command-{index}",
                    classes="command-button command-separator"
                    if command.is_separator
                    else "command-button",
                    tooltip=command.title,
                    disabled=command.is_separator,
                )
                for index, command in enumerate(
                    self.commands[first_index : first_index + self.command_rows],
                    start=first_index,
                )
            )
            columns.append(Vertical(*buttons, classes="command-column"))
        async with command_list.batch():
            await command_list.remove_children()
            await command_list.mount_all(columns)
        if self.selected_index is not None:
            selected_button = self.query_one(
                f"#command-{self.selected_index}", Button
            )
            selected_button.add_class("is-selected")
            if not self._command_info_is_open():
                selected_button.focus()

    @staticmethod
    def _command_rows_for_height(screen_height: int) -> int:
        return max(screen_height - 13, 1)

    def action_close_command_info(self) -> None:
        if self.configuration_error:
            return
        self.query_one("#command-list", CommandGrid).display = True
        self.query_one("#command-summary", Vertical).display = True
        self.query_one(CommandInfoPanel).display = False
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).focus()

    def action_select_previous(self) -> None:
        if not self._command_info_is_open():
            self._select_adjacent_command(-1)

    def action_select_next(self) -> None:
        if not self._command_info_is_open():
            self._select_adjacent_command(1)

    def action_select_left(self) -> None:
        if not self._command_info_is_open():
            self._select_horizontal_command(-1)

    def action_select_right(self) -> None:
        if not self._command_info_is_open():
            self._select_horizontal_command(1)

    def _finish_command(
        self,
        result: CommandResult,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        description: str | None = None,
    ) -> None:
        result_marker = "❌" if self._result_is_error(result) else "✅"
        message = f"{result_marker} View command output in the terminal."
        tooltip = description
        if started_at is not None and finished_at is not None:
            duration = str(finished_at - started_at).split(".", maxsplit=1)[0]
            timing_tooltip = (
                f"Started {started_at:%H:%M:%S} | "
                f"Finished {finished_at:%H:%M:%S} | "
                f"Duration {duration}"
            )
            message = f"🕒 {finished_at:%H:%M:%S}\n{message}"
            tooltip = timing_tooltip
        status_class = (
            "status-error" if self._result_is_error(result) else "status-success"
        )
        self._set_status(
            message,
            tooltip,
            status_class,
        )
        self._set_window_title(f"{result_marker} {self.APP_NAME}")

    def _select_index(self, index: int) -> None:
        if self.commands[index].is_separator:
            return
        if self.selected_index is not None:
            self.query_one(f"#command-{self.selected_index}", Button).remove_class(
                "is-selected"
            )
        self.selected_index = index
        self.query_one(f"#command-{index}", Button).add_class("is-selected")
        self._update_command_summary()

    def _update_command_summary(self) -> None:
        command = self._selected_command()
        if command is None:
            return
        description = self.query_one("#command-summary-description", Static)
        description.update(command.description)
        description.tooltip = command.description
        command_text = self.query_one("#command-summary-command", Static)
        command_text.update(command.display_command)
        command_text.tooltip = command.display_command

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
            or self.command_columns <= 1
            or self.command_rows <= 0
            or self.selected_index is None
        ):
            return
        current_column = self.selected_index // self.command_rows
        current_row = self.selected_index % self.command_rows
        for column_offset in range(1, self.command_columns):
            target_column = (
                current_column + direction * column_offset
            ) % self.command_columns
            target_column_start = target_column * self.command_rows
            target_column_end = min(
                target_column_start + self.command_rows,
                len(self.commands),
            )
            target_index = min(
                target_column_start + current_row,
                target_column_end - 1,
            )
            for candidate_index in range(target_index, target_column_start - 1, -1):
                if not self.commands[candidate_index].is_separator:
                    self._select_index(candidate_index)
                    self.query_one(f"#command-{candidate_index}", Button).focus()
                    return
            for candidate_index in range(target_index + 1, target_column_end):
                if not self.commands[candidate_index].is_separator:
                    self._select_index(candidate_index)
                    self.query_one(f"#command-{candidate_index}", Button).focus()
                    return

    def _set_window_title(self, title: str) -> None:
        self.title = title
        self._set_console_title(title)

    @staticmethod
    def _set_console_title(title: str) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        except OSError:
            pass

    def _spin_window_title(self, stop_event: Event) -> None:
        for frame in cycle(("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")):
            self._set_console_title(f"{frame} {self.APP_NAME}")
            if stop_event.wait(0.1):
                return

    def _set_status(
        self,
        message: str,
        tooltip: str | None = None,
        status_class: str | None = None,
    ) -> None:
        time, separator, status_message = message.partition("\n")
        if not separator:
            status_message = time
            time = ""
        status_time = self.query_one("#status-time", Static)
        status_time.update(time)
        status_time.tooltip = tooltip
        status = self.query_one("#status-message", Static)
        status.update(status_message)
        status.tooltip = tooltip
        status.remove_class("status-success")
        status.remove_class("status-error")
        if status_class is not None:
            status.add_class(status_class)
        self.query_one("#status-line", Horizontal).display = bool(status_message)

    def _selected_command(self) -> CommandDefinition | None:
        if self.selected_index is None:
            return None
        return self.commands[self.selected_index]

    def _command_info_is_open(self) -> bool:
        return (
            not self.configuration_error
            and self.query_one(CommandInfoPanel).display
        )

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
        except ValueError:
            return None
        if not 0 <= index < len(self.commands) or self.commands[index].is_separator:
            return None
        return index

    @staticmethod
    def _result_is_error(result: CommandResult) -> bool:
        return (
            result.error is not None
            or result.exit_code not in (0, None)
        )
