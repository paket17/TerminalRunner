import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from terminalrunner.state import AppState, load_state, save_state


class StateTests(unittest.TestCase):
    def test_round_trips_state(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            state = AppState(theme="textual-light", command_panel_expanded=True)

            save_state(path, state)

            self.assertEqual(load_state(path), state)

    def test_ignores_invalid_state(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(
                json.dumps({"theme": 3, "command_panel_expanded": "yes"}),
                encoding="utf-8",
            )

            self.assertEqual(load_state(path), AppState())

    def test_does_not_leave_a_temporary_file_after_saving(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"

            save_state(path, AppState())

            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
