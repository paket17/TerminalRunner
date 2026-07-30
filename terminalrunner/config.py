import ctypes
import os
from pathlib import Path
import shlex
import sys

import yaml

from .models import CommandDefinition


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
    allowed_fields = {"title", "description", "executable", "timeout_seconds", "shell"}
    unknown_fields = entry.keys() - allowed_fields
    if unknown_fields:
        unknown_field_names = ", ".join(sorted(unknown_fields))
        raise ConfigurationError(
            f"Command #{index} has unknown fields: {unknown_field_names}"
        )

    required = ("title",)
    fields: dict[str, str] = {}
    missing: list[str] = []
    for name in required:
        value = entry.get(name)
        if not isinstance(value, str) or not value.strip():
            missing.append(name)
        else:
            fields[name] = value
    if missing:
        raise ConfigurationError(
            f"Command #{index} is missing fields: {', '.join(missing)}"
        )

    description = entry.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ConfigurationError(
            f"description for command '{fields['title']}' must be a string."
        )

    executable = entry.get("executable")
    if executable is None:
        if set(entry) != {"title"}:
            raise ConfigurationError(
                f"Separator '{fields['title']}' must contain only a title."
            )
        return CommandDefinition(
            title=fields["title"],
            description=description,
            executable="",
            arguments=(),
            timeout_seconds=0,
            is_separator=True,
        )
    if not isinstance(executable, str) or not executable.strip():
        raise ConfigurationError(
            f"Command '{fields['title']}' has an empty executable."
        )
    fields["executable"] = executable

    timeout = entry.get("timeout_seconds", 3600)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ConfigurationError(
            "timeout_seconds for command "
            f"'{fields['title']}' must be a positive number."
        )

    shell = entry.get("shell", "&&" in fields["executable"])
    if not isinstance(shell, bool):
        raise ConfigurationError(
            f"shell for command '{fields['title']}' must be true or false."
        )
    if shell:
        return CommandDefinition(
            title=fields["title"],
            description=description,
            executable="",
            arguments=(),
            timeout_seconds=timeout,
            shell_command=fields["executable"],
        )

    try:
        command_parts = _split_direct_command(fields["executable"])
    except ValueError as error:
        raise ConfigurationError(
            f"Invalid executable for command '{fields['title']}': {error}"
        ) from error
    if not command_parts:
        raise ConfigurationError(
            f"Command '{fields['title']}' has an empty executable."
        )
    return CommandDefinition(
        title=fields["title"],
        description=description,
        executable=command_parts[0],
        arguments=tuple(command_parts[1:]),
        timeout_seconds=timeout,
    )


def _split_direct_command(command: str) -> list[str]:
    if sys.platform != "win32":
        return shlex.split(command)

    argument_count = ctypes.c_int()
    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
    arguments = command_line_to_argv(command, ctypes.byref(argument_count))
    if not arguments:
        raise ValueError("Unable to parse Windows command line.")
    try:
        return [arguments[index] for index in range(argument_count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(arguments)
