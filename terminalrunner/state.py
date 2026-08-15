import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppState:
    theme: str | None = None


def default_state_path() -> Path:
    configured_path = os.environ.get("TERMINALRUNNER_STATE")
    if configured_path:
        return Path(configured_path)
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "TerminalRunner"
            / "state.json"
        )
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "terminalrunner" / "state.json"
    return Path.home() / ".local" / "state" / "terminalrunner" / "state.json"


def load_state(path: Path) -> AppState:
    try:
        with path.open(encoding="utf-8") as state_file:
            data = json.load(state_file)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return AppState()
    if not isinstance(data, dict):
        return AppState()

    theme = data.get("theme")
    return AppState(theme=theme if isinstance(theme, str) else None)


def save_state(path: Path, state: AppState) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as state_file:
            temporary_path = Path(state_file.name)
            json.dump(
                {
                    "theme": state.theme,
                },
                state_file,
                ensure_ascii=True,
                indent=2,
            )
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
