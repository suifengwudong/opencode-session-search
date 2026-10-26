import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
MAX_MS = 2**63 - 1
SNIPPET_WIDTH = 64
INDENT = " " * 18

USER_SQL = """
WITH rows AS (
    SELECT session_id, time_created, json_extract(data, '$.text') AS text
    FROM session_message
    WHERE type = 'user' AND time_created >= ? AND time_created < ?
)
SELECT session_id, time_created, text
FROM rows
WHERE {where}
"""

ASSISTANT_SQL = """
SELECT m.session_id, m.time_created, json_extract(j.value, '$.text') AS text
FROM session_message m, json_each(m.data, '$.content') j
WHERE m.type = 'assistant'
  AND m.time_created >= ? AND m.time_created < ?
  AND json_extract(j.value, '$.type') = 'text'
  AND {where}
"""


class Palette:
    def __init__(self, enabled):
        self.enabled = enabled

    def paint(self, text, code):
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def dim(self, text):
        return self.paint(text, "2")

    def bold(self, text):
        return self.paint(text, "1")


def resolve_db(value):
    if value:
        return Path(value)
    env = os.environ.get("OPENCODE_DB")
    return Path(env) if env else DEFAULT_DB


def connect(path):
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def parse_when(value, end=False):
    match = re.fullmatch(r"(\d+)([hdw])", value)
    if match:
        unit = {"h": 3600, "d": 86400, "w": 604800}[match.group(2)]
        seconds = int(match.group(1)) * unit
        return int((datetime.now().timestamp() - seconds) * 1000)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        moment = datetime.strptime(value, "%Y-%m-%d")
        if end:
            moment += timedelta(days=1)
        return int(moment.timestamp() * 1000)
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def fmt_time(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def like_pattern(keyword):
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def make_snippet(text, keywords, width=SNIPPET_WIDTH):
    flat = re.sub(r"\s+", " ", text or "").strip()
    if not flat:
        return ""
    lowered = flat.lower()
    positions = [lowered.find(keyword.lower()) for keyword in keywords]
    positions = [position for position in positions if position >= 0]
    if not positions:
        cut = flat[: width * 2]
        return cut + ("…" if len(flat) > len(cut) else "")
    position = min(positions)
    start = max(0, position - width)
    end = min(len(flat), position + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return f"{prefix}{flat[start:end]}{suffix}"


def shorten_path(path, limit=44):
    normalized = path.replace("\\", "/")
    if len(normalized) <= limit:
        return normalized
    parts = normalized.split("/")
    tail = parts[-1]
    for index in range(2, len(parts) + 1):
        candidate = "/".join(parts[-index:])
        if len(candidate) + 2 > limit:
            break
        tail = candidate
    return "…/" + tail


def load_sessions(con):
    rows = con.execute(
        "SELECT id, parent_id, title, directory, time_created, time_updated, "
        "time_archived, agent, model FROM session_v2"
    ).fetchall()
    return {row["id"]: dict(row) for row in rows}


def root_of(sessions, sid):
    seen = set()
    while sid not in seen:
        seen.add(sid)
        parent = sessions.get(sid, {}).get("parent_id")
        if not parent or parent not in sessions:
            return sid
        sid = parent
    return sid


def search(
    con,
    keywords,
    since_ms=0,
    until_ms=MAX_MS,
    directory=None,
    assistant=False,
    include_current=False,
    include_children=False,
    limit=20,
):
    sessions = load_sessions(con)
    current = os.environ.get("OPENCODE_SESSION_ID")
    needle = directory.replace("\\", "/").lower() if directory else None

    def keep(sid):
        if not include_current and sid == current:
            return False
        if (
            needle
            and needle not in sessions[sid]["directory"].replace("\\", "/").lower()
        ):
            return False
        return True

    def target_of(sid):
        return sid if include_children else root_of(sessions, sid)

    hits = {}

    def record(target, ts, text=None, title_hit=False):
        hit = hits.get(target)
        if hit is None:
            hit = hits[target] = {
                "id": target,
                "count": 0,
                "last": ts,
                "snippet": None,
                "snippet_ts": None,
                "title": False,
            }
        if title_hit:
            hit["title"] = True
            if ts > hit["last"]:
                hit["last"] = ts
            return
        hit["count"] += 1
        if ts > hit["last"]:
            hit["last"] = ts
        if text and (hit["snippet_ts"] is None or ts < hit["snippet_ts"]):
            hit["snippet"] = make_snippet(text, keywords)
            hit["snippet_ts"] = ts

    if not keywords:
        rows = [
            session
            for session in sessions.values()
            if (include_children or not session["parent_id"])
            and since_ms <= session["time_updated"] < until_ms
            and keep(session["id"])
        ]
        rows.sort(key=lambda session: session["time_updated"], reverse=True)
        if limit > 0:
            rows = rows[:limit]
        return [
            {
                "id": session["id"],
                "count": 0,
                "last": session["time_updated"],
                "snippet": None,
                "snippet_ts": None,
                "title": False,
            }
            for session in rows
        ], sessions

    patterns = [like_pattern(keyword) for keyword in keywords]
    where = " AND ".join(["text LIKE ? ESCAPE '\\'"] * len(keywords))

    for row in con.execute(
        USER_SQL.format(where=where), [since_ms, until_ms] + patterns
    ):
        target = target_of(row["session_id"])
        if target in sessions and keep(target):
            record(target, row["time_created"], row["text"])

    if assistant:
        for row in con.execute(
            ASSISTANT_SQL.format(where=where), [since_ms, until_ms] + patterns
        ):
            target = target_of(row["session_id"])
            if target in sessions and keep(target):
                record(target, row["time_created"], row["text"])

    title_where = " AND ".join(["title LIKE ? ESCAPE '\\'"] * len(keywords))
    for row in con.execute(
        f"SELECT id, time_updated FROM session_v2 WHERE {title_where}", patterns
    ):
        if not (since_ms <= row["time_updated"] < until_ms):
            continue
        target = target_of(row["id"])
        if target in sessions and keep(target):
            record(target, row["time_updated"], title_hit=True)

    result = sorted(hits.values(), key=lambda hit: hit["last"], reverse=True)
    if limit > 0:
        result = result[:limit]
    return result, sessions


def render(hits, sessions, palette):
    lines = []
    for hit in hits:
        session = sessions[hit["id"]]
        meta = f"{shorten_path(session['directory'])} · {hit['id']}"
        if hit["count"] > 1:
            meta += f" · {hit['count']} matches"
        if hit["title"] and not hit["count"]:
            meta += " · title match"
        if session["time_archived"]:
            meta += " · archived"
        lines.append(
            f"{palette.dim(fmt_time(hit['last']))}  {palette.bold(session['title'] or '(untitled)')}"
        )
        lines.append(INDENT + palette.dim(meta))
        if hit["snippet"]:
            lines.append(INDENT + hit["snippet"])
    return "\n".join(lines)


def find_session(con, prefix):
    rows = con.execute("SELECT id FROM session_v2").fetchall()
    matches = [row["id"] for row in rows if row["id"].startswith(prefix)]
    if not matches:
        sys.exit(f"no session matches {prefix}")
    if len(matches) > 1:
        sys.exit("ambiguous prefix: " + ", ".join(matches[:5]))
    return matches[0]


def show_session(con, prefix, prompt_count, palette):
    sid = find_session(con, prefix)
    session = con.execute("SELECT * FROM session_v2 WHERE id = ?", (sid,)).fetchone()
    counts = {
        row["type"]: row["count"]
        for row in con.execute(
            "SELECT type, count(*) AS count FROM session_message "
            "WHERE session_id = ? GROUP BY type",
            (sid,),
        )
    }
    total = sum(counts.values())
    model = json.loads(session["model"]) if session["model"] else {}
    model_label = "/".join(
        part for part in (model.get("providerID"), model.get("id")) if part
    )

    print(palette.bold(session["title"] or "(untitled)"))
    print(session["id"])
    print(session["directory"])
    line = f"{fmt_time(session['time_created'])} → {fmt_time(session['time_updated'])} · {total} messages"
    if session["agent"]:
        line += f" · {session['agent']}"
    if model_label:
        line += f" · {model_label}"
    if session["time_archived"]:
        line += " · archived"
    print(palette.dim(line))
    print()

    prompts = con.execute(
        "SELECT time_created, json_extract(data, '$.text') AS text "
        "FROM session_message WHERE session_id = ? AND type = 'user' ORDER BY seq",
        (sid,),
    ).fetchall()
    prompts = [prompt for prompt in prompts if prompt["text"]]

    if len(prompts) <= prompt_count * 2:
        shown = prompts
        gap = False
    else:
        shown = list(prompts[:prompt_count]) + list(prompts[-prompt_count:])
        gap = True

    for index, prompt in enumerate(shown):
        if gap and index == prompt_count:
            print(palette.dim("…"))
        text = re.sub(r"\s+", " ", prompt["text"]).strip()
        if len(text) > 160:
            text = text[:160] + "…"
        print(f"{palette.dim(fmt_time(prompt['time_created']))}  {text}")

    print()
    print(palette.dim(f"resume: opencode -s {sid}"))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ses",
        description="Search OpenCode sessions across every project.",
    )
    parser.add_argument(
        "keywords",
        nargs="*",
        help="words that must all appear in the title or a user prompt",
    )
    parser.add_argument(
        "-n", "--limit", type=int, default=20, help="maximum results (default 20)"
    )
    parser.add_argument(
        "-d", "--dir", dest="directory", help="only sessions under this directory"
    )
    parser.add_argument(
        "--since", help="start time: 30d, 12h, 2w, 2026-09-01, or an ISO timestamp"
    )
    parser.add_argument("--until", help="end time, same formats as --since")
    parser.add_argument(
        "-a",
        "--assistant",
        action="store_true",
        help="also search assistant replies (slower)",
    )
    parser.add_argument(
        "--all",
        dest="include_children",
        action="store_true",
        help="show child sessions individually",
    )
    parser.add_argument(
        "--include-current",
        action="store_true",
        help="include the session that is running this command",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--db", help="path to opencode.db")
    return parser


def build_show_parser():
    parser = argparse.ArgumentParser(
        prog="ses show",
        description="Show one session and its prompts.",
    )
    parser.add_argument("id", help="session id or unique prefix")
    parser.add_argument(
        "-n", "--prompts", type=int, default=3, help="prompts from each end (default 3)"
    )
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--db", help="path to opencode.db")
    return parser


def color_enabled(no_color):
    return sys.stdout.isatty() and not no_color and "NO_COLOR" not in os.environ


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "show":
        args = build_show_parser().parse_args(argv[1:])
        palette = Palette(color_enabled(args.no_color))
        con = connect(resolve_db(args.db))
        show_session(con, args.id, args.prompts, palette)
        return 0

    args = build_parser().parse_args(argv)
    palette = Palette(color_enabled(args.no_color))
    since_ms = parse_when(args.since) if args.since else 0
    until_ms = parse_when(args.until, end=True) if args.until else MAX_MS
    keywords = [keyword for keyword in args.keywords if keyword]

    con = connect(resolve_db(args.db))
    hits, sessions = search(
        con,
        keywords,
        since_ms=since_ms,
        until_ms=until_ms,
        directory=args.directory,
        assistant=args.assistant,
        include_current=args.include_current,
        include_children=args.include_children,
        limit=args.limit,
    )

    if args.json:
        payload = [
            {
                "id": hit["id"],
                "title": sessions[hit["id"]]["title"],
                "directory": sessions[hit["id"]]["directory"],
                "created": fmt_time(sessions[hit["id"]]["time_created"]),
                "updated": fmt_time(sessions[hit["id"]]["time_updated"]),
                "last_match": fmt_time(hit["last"]),
                "matches": hit["count"],
                "title_match": hit["title"],
                "snippet": hit["snippet"],
            }
            for hit in hits
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif hits:
        print(render(hits, sessions, palette))
        print()
        print(palette.dim("resume: opencode -s <id>   details: ses show <id>"))
    else:
        print("no sessions found", file=sys.stderr)
        if keywords and not args.assistant:
            print("hint: add -a to search assistant replies", file=sys.stderr)

    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
