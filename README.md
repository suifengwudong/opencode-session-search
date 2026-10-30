# ses

Search OpenCode sessions across every project from the terminal.

OpenCode's built-in `/sessions` view only lists sessions in the current project. `ses` reads the local OpenCode database and searches session titles and user prompts across all projects, then shows the session id and how to resume it.

## Requirements

- OpenCode v2.1.4 or newer (`session_v2` schema)
- Python 3.11+

## Install

```powershell
uv tool install git+https://github.com/suifengwudong/opencode-session-search
```

or:

```powershell
pipx install git+https://github.com/suifengwudong/opencode-session-search
```

If `ses` is not on PATH, run `uv tool update-shell` and open a new terminal. The OpenCode plugin uses the absolute path, so it works either way.

From a clone, `python ses.py` and `ses.cmd` work without installing anything.

## OpenCode plugin

The plugin registers a `session_search` tool and a `/ses` command. It calls the `ses` CLI, so the installation script installs both.

Windows:

```powershell
git clone https://github.com/suifengwudong/opencode-session-search
cd opencode-session-search
./install.ps1
opencode reload
```

macOS and Linux:

```bash
git clone https://github.com/suifengwudong/opencode-session-search
cd opencode-session-search
./install.sh
opencode reload
```

Then ask the agent "Find the session where we discussed X", or run `/ses X`. The plugin is optional; the CLI works on its own.

## Usage

```powershell
ses                          # 20 most recent top-level sessions
ses benchmark                # every keyword must match
ses parser -d work --since 30d
ses 图表 配色                 # non-ASCII keywords work
ses retry logic -a           # include assistant replies
ses old-topic --all-time     # search the whole history
ses show ses_1a2b3c4d5e6f    # prompts from both ends of a session
ses benchmark --json
```

```
2026-08-14 09:20  Vector search benchmark
                  F:/work/search · ses_1a2b3c4d5e6f
                  …compare HNSW and IVF on the same corpus…
```

Resume a result with:

```powershell
opencode -s ses_1a2b3c4d5e6f
```

## Options

| Option | Meaning |
| --- | --- |
| `-n, --limit N` | maximum results, default 20 |
| `-d, --dir TEXT` | only sessions whose directory contains `TEXT` |
| `--since TIME` | start time: `30d`, `12h`, `2w`, `2026-09-01`, or an ISO timestamp; default is 90 days ago |
| `--until TIME` | end time, same formats as `--since` |
| `--all-time` | search the whole history instead of the last 90 days |
| `-a, --assistant` | also search assistant text (slower) |
| `--all` | show child sessions individually instead of rolling them up to the parent |
| `--include-current` | include the session running the command |
| `--json` | print JSON |
| `--no-color` | disable ANSI colors |
| `--db PATH` | path to `opencode.db` |

`ses show ID [-n N]` prints the session metadata, its first and last `N` prompts, and the resume command. `ID` may be a unique prefix.

## Compacting stored payloads

Images and PDFs read by tools are stored base64-encoded in `session_message` and `part`, which makes every assistant search scan gigabytes. `ses compact` replaces those payloads with a short `removed-base64:<size>` marker and keeps the surrounding JSON intact. Attachments sent in user prompts are left alone: OpenCode validates their `data` field against `Prompt.Base64`, so replacing it makes the whole message fail with `Session.MessageDecodeError`.

```powershell
ses compact --dry-run        # report what would be removed
ses compact                  # rewrite the payloads
ses compact --vacuum         # rewrite, then rebuild the database file
```

Run `--vacuum` with OpenCode closed: SQLite needs exclusive access to rebuild the file. The command is idempotent, so a second run reports `0 payloads`.

## How it works

- Reads `~/.local/share/opencode/opencode.db` through a read-only SQLite connection. Override the path with `OPENCODE_DB` or `--db`.
- Limits every search to the last 90 days unless `--since` or `--all-time` is given.
- Matches session titles and the `text` field of user messages.
- With `-a`, also matches `text` parts of assistant messages. Reasoning and tool payloads are not searched.
- Subagent sessions are attributed to their parent session, so a hit always points at a resumable conversation.
- The current session (`OPENCODE_SESSION_ID`) is skipped by default.
- Time filters compare against message timestamps; a session with no keyword filters on its last update time.
- `ses compact` rewrites tool payloads stored in `session_message` and `part`, skipping user messages; it is the only command that opens the database read-write.

Exit code is `0` when something matched and `1` when nothing did, which makes the command usable in scripts.

## Development

```powershell
python -m pytest
```

## License

MIT
