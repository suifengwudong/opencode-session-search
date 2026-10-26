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

From a clone, `python ses.py` and `ses.cmd` work without installing anything.

## Usage

```powershell
ses                          # 20 most recent top-level sessions
ses benchmark                # every keyword must match
ses parser -d work --since 30d
ses 图表 配色                 # non-ASCII keywords work
ses retry logic -a           # include assistant replies
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
| `--since TIME` | start time: `30d`, `12h`, `2w`, `2026-09-01`, or an ISO timestamp |
| `--until TIME` | end time, same formats as `--since` |
| `-a, --assistant` | also search assistant text (slower, about 6 seconds on a large database) |
| `--all` | show child sessions individually instead of rolling them up to the parent |
| `--include-current` | include the session running the command |
| `--json` | print JSON |
| `--no-color` | disable ANSI colors |
| `--db PATH` | path to `opencode.db` |

`ses show ID [-n N]` prints the session metadata, its first and last `N` prompts, and the resume command. `ID` may be a unique prefix.

## How it works

- Reads `~/.local/share/opencode/opencode.db` through a read-only SQLite connection. Override the path with `OPENCODE_DB` or `--db`.
- Matches session titles and the `text` field of user messages.
- With `-a`, also matches `text` parts of assistant messages. Reasoning and tool payloads are not searched.
- Subagent sessions are attributed to their parent session, so a hit always points at a resumable conversation.
- The current session (`OPENCODE_SESSION_ID`) is skipped by default.
- Time filters compare against message timestamps; a session with no keyword filters on its last update time.

Exit code is `0` when something matched and `1` when nothing did, which makes the command usable in scripts.

## Development

```powershell
python -m pytest
```

## License

MIT
