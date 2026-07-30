from dataclasses import dataclass


@dataclass(frozen=True)
class CommandDefinition:
    """A command available from the launcher configuration."""

    title: str
    description: str
    executable: str
    arguments: tuple[str, ...]
    timeout_seconds: int
    shell_command: str | None = None
    is_separator: bool = False

    @property
    def display_command(self) -> str:
        if self.is_separator:
            return ""
        return self.shell_command or " ".join((self.executable, *self.arguments))
