import os
from pathlib import Path
import sys

import yaml

from .models import CommandDefinition, CommandStep


class ConfigurationError(ValueError):
    """The command catalog cannot be used."""


def default_config_path() -> Path:
    configured_path = os.environ.get("TERMINALRUNNER_CONFIG")
    if configured_path:
        return Path(configured_path)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "commands.yaml"
    current_directory_config = Path.cwd() / "commands.yaml"
    if current_directory_config.is_file():
        return current_directory_config
    return Path(__file__).with_name("commands.yaml")


def load_commands(path: Path) -> tuple[CommandDefinition, ...]:
    try:
        with path.open(encoding="utf-8") as config_file:
            data = yaml.safe_load(config_file)
    except OSError as error:
        raise ConfigurationError(
            f"Unable to read configuration {path}: {error}"
        ) from error
    except (UnicodeError, yaml.YAMLError) as error:
        raise ConfigurationError(f"Invalid YAML in {path}: {error}") from error

    entries = data.get("commands") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigurationError(
            "Configuration must contain a non-empty commands list."
        )

    commands: list[CommandDefinition] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigurationError(f"Command #{index} must be a YAML object.")
        command = _parse_command(entry, index)
        commands.append(command)
    return tuple(commands)


def _parse_command(entry: dict[str, object], index: int) -> CommandDefinition:
    allowed_fields = {"title", "description", "commands"}
    unknown_fields = entry.keys() - allowed_fields
    if unknown_fields:
        unknown_field_names = ", ".join(
            str(field) for field in sorted(unknown_fields, key=str)
        )
        raise ConfigurationError(
            f"Command #{index} has unknown fields: {unknown_field_names}"
        )

    title = entry.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ConfigurationError(f"Command #{index} is missing fields: title")

    description = entry.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ConfigurationError(
            f"description for command '{title}' must be a string."
        )

    commands = entry.get("commands")
    if commands is None:
        if set(entry) != {"title"}:
            raise ConfigurationError(
                f"Separator '{title}' must contain only a title."
            )
        return CommandDefinition(
            title=title,
            description=description,
            commands=(),
            is_separator=True,
        )
    if not isinstance(commands, list) or not commands:
        raise ConfigurationError(
            f"commands for command '{title}' must be a non-empty list."
        )

    command_steps: list[CommandStep] = []
    for command_index, command in enumerate(commands, start=1):
        if isinstance(command, dict):
            if set(command) != {"shell"}:
                raise ConfigurationError(
                    f"Shell command #{command_index} for '{title}' must contain "
                    "only shell."
                )
            shell_command = command["shell"]
            if not isinstance(shell_command, str) or not shell_command.strip():
                raise ConfigurationError(
                    f"shell for command #{command_index} for '{title}' must be "
                    "a non-empty string."
                )
            command_steps.append(CommandStep(shell_command=shell_command))
            continue
        if not isinstance(command, list) or not command:
            raise ConfigurationError(
                f"Command #{command_index} for '{title}' must be a non-empty list."
            )
        if not all(isinstance(argument, str) for argument in command):
            raise ConfigurationError(
                f"Command #{command_index} for '{title}' must contain only strings."
            )
        if not command[0].strip():
            raise ConfigurationError(
                f"Command #{command_index} for '{title}' has an empty executable."
            )
        command_steps.append(CommandStep(argv=tuple(command)))

    return CommandDefinition(
        title=title,
        description=description,
        commands=tuple(command_steps),
    )
