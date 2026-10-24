# TerminalRunner

[🇷🇺 Читать на русском](README.ru.md)

TerminalRunner is a cross-platform TUI launcher for running preconfigured commands in a standard terminal.
<img width="1100" height="620" alt="image" src="https://github.com/user-attachments/assets/d3ea13e9-3582-4be6-95bb-1e848a36278c" />


## Quick Start

Requires Python 3.11 or newer.

### Windows

```powershell
py -m pip install .
terminalrunner
```

### Linux

```bash
python3 -m pip install .
terminalrunner
```

On Linux, use Linux paths and commands in your `commands.yaml`.

## Usage

1. Launch `terminalrunner`.
2. Select a command using arrow keys, `Tab`, `Shift+Tab`, or the mouse.
3. Press `Enter` or click the command button to run it.
4. The application temporarily yields the screen to the terminal and returns once the command finishes. The status bar displays the result and execution duration; the command's output remains in the terminal.

### Keybindings

| Key | Action |
| --- | --- |
| `Enter` | Run selected command |
| `F1` | Open or close the command details popup |
| `Esc` | Close the command details popup |
| `Ctrl+D` | Open an interactive terminal shell |
| `Ctrl+Q` | Quit application |

`Ctrl+D` opens a separate interactive shell. In PowerShell and Linux `/bin/sh`, press `Ctrl+D` or type `exit` to return to TerminalRunner. If PowerShell 7 (`pwsh`) is unavailable on Windows, `cmd.exe` is launched; use `exit` to return.

In the `F1` info view, the command list is replaced with full details, while the bottom pane displaying the description and command remains visible.

## Custom Commands

Create a `commands.yaml` in the current working directory, specify it via `TERMINALRUNNER_CONFIG`, or edit `commands.yaml` located next to the EXE. The bundled catalog contains test and platform examples and is intended only as a structural reference.

### Catalog Format

The catalog contains a non-empty `commands` list. Each entry may only include the following fields:

| Parameter | Required | Description |
| --- | --- | --- |
| `title` | Yes | Title displayed in the command list. |
| `description` | No | Explanation of the command. Displayed in the UI and opened in full via `F1`. Defaults to an empty string. |
| `commands` | Yes, except for separators | Non-empty list of commands. Each command is a non-empty list of strings: the program name followed by its arguments. |
| `ignore_errors` | No | Continue executing all commands in the list even if individual steps fail. Defaults to `false`. |

Sequential execution example:

```yaml
commands:
  # Entries containing only `title` create separators in the list and cannot be run
  - title: Checks

  - title: Check Project
    description: Runs checks in sequence and stops at the first failure.
    commands:
      - [ruff, check, .]
      - [mypy]
      - [python3, -m, unittest, discover, -v]
```

An entry containing only a `title` creates a non-executable separator. Unknown fields and separators with extra fields are rejected. For arguments that resemble YAML literals (`true`, `null`, `001`, dates), wrap them in quotes to ensure they are passed as strings.

### Command Execution and Security

The catalog is not interpreted in its entirety as shell script. By default, each command is passed to the operating system as a prepared argument list: arguments containing spaces stay intact as a single string `[tool, "Hello world"]`, and literal quotes are passed as part of the string `[tool, '"exact value"']`.

#### Step Types in `commands`

1. **Direct Executable Invocations (`.exe` / binaries):**
   ```yaml
   - [py, --version]
   - [git, status]
   ```
   The program is launched directly by the operating system without an intermediate shell interpreter (no `cmd.exe` or `/bin/sh`). Arguments undergo no shell interpretation.

2. **PowerShell Scripts (`.ps1`):**
   ```yaml
   - [./deploy.ps1, -Environment, prod]
   ```
   On Windows, files with the `.ps1` extension are automatically executed via `powershell.exe -NoProfile -File ...`.

3. **Windows Batch Files (`.bat`, `.cmd`):**
   ```yaml
   - [build.bat, --release]
   ```
   Automatically executed via `cmd.exe /d /s /c call ...`, since Windows does not run batch files directly as native binaries. For batch file arguments, CMD metacharacters (`&`, `|`, `<`, `>`, `(`, `)`, `^`, `%`, `!`, `"`) are disallowed for security reasons.

4. **Shell Commands (`shell:`):**
   ```yaml
   - shell: 'echo Windows user: %USERNAME%'
   - shell: 'echo Linux user: $USER'
   ```
   Executed via the system shell: on Windows via `cmd.exe /d /s /c "..."`, on Linux via `/bin/sh -c "..."`. Use `shell:` when you need:
   - Built-in shell commands (`echo`, `dir`, `copy`, `cd` — which do not have `.exe` files);
   - Environment variables (`%VAR%` on Windows, `$VAR` on Linux);
   - Pipes (`|`), redirections (`>`, `<`), and chaining operators (`&&`, `&`).

#### Running PowerShell Cmdlets and Commands

Because the `shell:` directive on Windows uses `cmd.exe`, PowerShell cmdlets and syntax (such as `throw`, `Write-Host`, `Get-ChildItem`) will not work inside `shell:`. To invoke PowerShell, launch it directly as an argument list:
```yaml
- [powershell, -NoProfile, -Command, 'Write-Host "Hello from PowerShell"']
# or via PowerShell 7 (pwsh):
- [pwsh, -NoProfile, -Command, 'throw "Error"']
```

#### Multiline Commands

1. **Recommended Approach — Separate steps in `commands`:**
   Split the sequence into multiple items under `commands:`. Each step runs independently, output is streamed sequentially to the terminal, and each exit code is tracked:
   ```yaml
   commands:
     - shell: 'echo Step 1'
     - shell: 'echo Step 2'
   ```

2. **Joining long lines using the YAML folded scalar (`>`):**
   If you need to write a long shell command across multiple lines in the configuration file:
   ```yaml
   commands:
     - shell: >
         git fetch origin &&
         git checkout main &&
         git pull --rebase
   ```
   The `>` symbol folds newlines into spaces, forming a single valid command for `cmd.exe` or `/bin/sh`.

3. **Multiline PowerShell block via `|`:**
   ```yaml
   commands:
     - [pwsh, -NoProfile, -Command, |
         $user = $env:USERNAME
         Write-Host "Current user: $user"
       ]
   ```

#### Execution Order and `ignore_errors`

Commands execute sequentially and stop immediately after the first error. If you need to run all steps regardless of intermediate failures, set `ignore_errors: true`:

```yaml
- title: Build and Checks
  description: Runs all checks even if the linter finds errors.
  ignore_errors: true
  commands:
    - [ruff, check, .]
    - [mypy]
    - [python, -m, unittest, discover]
```

When `ignore_errors: true`:
- All steps in `commands` will be executed to completion;
- If at least one step fails, the final status in TerminalRunner will show **❌** with the exit code of the first failing command;
- Cancelling with `Ctrl+C` still aborts the entire process immediately.

## Building the Windows EXE

On Windows, run from the repository root:

```bat
build-exe.bat
```

You can also double-click `build-exe.bat` in File Explorer. The script will install dev dependencies, remove existing `build/` and `dist/` directories, build the application using PyInstaller, and produce `dist\TerminalRunner.exe` along with `dist\commands.yaml`. Edit `dist\commands.yaml` to modify the command catalog without rebuilding.

## Configuration and Development

### Configuration Resolution Order

Configuration is loaded in the following order:

1. Path specified in the `TERMINALRUNNER_CONFIG` environment variable.
2. `commands.yaml` located next to the built EXE.
3. `commands.yaml` in the current working directory.
4. Bundled fallback catalog at `terminalrunner/commands.yaml`.

Example running with a custom catalog:

```powershell
$env:TERMINALRUNNER_CONFIG = "D:\Repos\TerminalRunner\commands.yaml"
terminalrunner
```

### Application State

The selected theme is saved on exit.

- Windows: `%LOCALAPPDATA%\TerminalRunner\state.json`
- Linux: `$XDG_STATE_HOME/terminalrunner/state.json` or `~/.local/state/terminalrunner/state.json`
- `TERMINALRUNNER_STATE` sets a custom path for the state file.

### Local Checks

```powershell
py -m pip install -e ".[dev]"
ruff check .
mypy
py -m unittest discover -v
py -m build --wheel
```
