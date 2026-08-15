from dataclasses import dataclass


@dataclass(frozen=True)
class CommandStep:
    """One direct or shell command in a launcher entry."""

    argv: tuple[str, ...] = ()
    shell_command: str | None = None

    @property
    def display_command(self) -> str:
        return self.shell_command or " ".join(self.argv)


@dataclass(frozen=True)
class CommandDefinition:
    """A command available from the launcher configuration."""

    title: str
    description: str
    commands: tuple[CommandStep, ...]
    is_separator: bool = False

    @property
    def display_command(self) -> str:
        if self.is_separator:
            return ""
        return "\n".join(command.display_command for command in self.commands)
