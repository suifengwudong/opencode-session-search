import json
import sqlite3
from datetime import datetime

import pytest

import ses

SCHEMA = """
CREATE TABLE session_v2 (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    title TEXT NOT NULL,
    directory TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    time_archived INTEGER,
    agent TEXT,
    model TEXT
);
CREATE TABLE session_message (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    type TEXT NOT NULL,
    seq INTEGER NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data TEXT NOT NULL
);
"""


def stamp(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def user(text, when):
    return json.dumps(
        {"time": {"created": when}, "text": text, "files": [], "agents": []}
    )


def assistant(parts, when):
    return json.dumps(
        {
            "agent": "build",
            "model": {"id": "m", "providerID": "p"},
            "content": parts,
            "time": {"created": when},
        }
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_current")
    path = tmp_path / "opencode.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)

    sessions = [
        (
            "ses_lit",
            None,
            "文献综述",
            "F:/notes",
            "2026-10-20T10:00:00",
            "2026-10-20T10:30:00",
            None,
        ),
        (
            "ses_lit_child",
            "ses_lit",
            "子任务",
            "F:/notes",
            "2026-10-20T10:15:00",
            "2026-10-20T10:25:00",
            None,
        ),
        (
            "ses_career",
            None,
            "work选择",
            "F:/life",
            "2026-10-20T10:50:00",
            "2026-10-20T11:10:00",
            None,
        ),
        (
            "ses_escape",
            None,
            "特殊字符",
            "F:/misc",
            "2026-10-20T11:20:00",
            "2026-10-20T11:35:00",
            None,
        ),
        (
            "ses_current",
            None,
            "当前会话",
            "F:/notes",
            "2026-10-20T11:38:00",
            "2026-10-20T11:45:00",
            None,
        ),
    ]
    for sid, parent, title, directory, created, updated, archived in sessions:
        con.execute(
            "INSERT INTO session_v2 (id, parent_id, title, directory, time_created, "
            "time_updated, time_archived, agent, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                parent,
                title,
                directory,
                stamp(created),
                stamp(updated),
                stamp(archived) if archived else None,
                "build",
                '{"id": "deepseek", "providerID": "deepseek"}',
            ),
        )

    messages = [
        (
            "m1",
            "ses_lit",
            "user",
            "2026-10-20T10:10:00",
            user("帮我用 mineru 解析这些 PDF", stamp("2026-10-20T10:10:00")),
        ),
        (
            "m2",
            "ses_lit",
            "assistant",
            "2026-10-20T10:11:00",
            assistant(
                [
                    {"type": "reasoning", "text": "chainofthought 只在推理里出现"},
                    {"type": "text", "text": "mineru 会把retry logic成 Markdown"},
                ],
                stamp("2026-10-20T10:11:00"),
            ),
        ),
        (
            "m3",
            "ses_lit_child",
            "user",
            "2026-10-20T10:20:00",
            user("跑一下benchmark策略回测", stamp("2026-10-20T10:20:00")),
        ),
        (
            "m4",
            "ses_career",
            "user",
            "2026-10-20T11:00:00",
            user("清华读博，运筹 + RL + benchmark", stamp("2026-10-20T11:00:00")),
        ),
        (
            "m5",
            "ses_escape",
            "user",
            "2026-10-20T11:30:00",
            user(
                r"进度 50%_done，准备提交到 C:\temp\out", stamp("2026-10-20T11:30:00")
            ),
        ),
        (
            "m6",
            "ses_current",
            "user",
            "2026-10-20T11:40:00",
            user("benchmark", stamp("2026-10-20T11:40:00")),
        ),
    ]
    for mid, sid, kind, when, data in messages:
        con.execute(
            "INSERT INTO session_message (id, session_id, type, seq, time_created, "
            "time_updated, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, sid, kind, 0, stamp(when), stamp(when), data),
        )

    con.commit()
    con.close()
    return path


def run(db, *args):
    return ses.main(["--db", str(db), *args])


def test_user_prompt_search(db, capsys):
    assert run(db, "mineru") == 0
    out = capsys.readouterr().out
    assert "文献综述" in out
    assert "ses_lit" in out


def test_reasoning_text_is_ignored(db, capsys):
    assert run(db, "chainofthought") == 1
    assert run(db, "chainofthought", "-a") == 1
    err = capsys.readouterr().err
    assert "no sessions found" in err
    assert "-a" in err


def test_assistant_text_needs_flag(db, capsys):
    assert run(db, "retry logic") == 1
    assert run(db, "retry logic", "-a") == 0
    out = capsys.readouterr().out
    assert "文献综述" in out


def test_child_rolls_up_to_root(db, capsys):
    assert run(db, "benchmark策略") == 0
    out = capsys.readouterr().out
    assert "文献综述" in out
    assert "子任务" not in out

    assert run(db, "benchmark策略", "--all") == 0
    out = capsys.readouterr().out
    assert "子任务" in out


def test_current_session_is_excluded(db, capsys):
    assert run(db, "benchmark") == 0
    out = capsys.readouterr().out
    assert "work选择" in out
    assert "当前会话" not in out

    assert run(db, "benchmark", "--include-current") == 0
    out = capsys.readouterr().out
    assert "当前会话" in out


def test_directory_filter(db, capsys):
    assert run(db, "benchmark", "-d", "F:\\life") == 0
    out = capsys.readouterr().out
    assert "work选择" in out
    assert "文献综述" not in out


def test_time_filter(db, capsys):
    assert run(db, "清华", "--since", "2026-10-20T10:30:00") == 0
    out = capsys.readouterr().out
    assert "work选择" in out

    assert run(db, "清华", "--since", "2026-10-20T11:30:00") == 1


def test_multiple_keywords_are_anded(db, capsys):
    assert run(db, "清华", "运筹") == 0
    assert run(db, "清华", "不存在的词") == 1


def test_like_wildcards_are_literal(db, capsys):
    assert run(db, "50%_done") == 0
    out = capsys.readouterr().out
    assert "特殊字符" in out

    assert run(db, "50x") == 1


def test_backslash_is_literal(db, capsys):
    assert run(db, r"C:\temp") == 0
    out = capsys.readouterr().out
    assert "特殊字符" in out


def test_title_match(db, capsys):
    assert run(db, "文献") == 0
    out = capsys.readouterr().out
    assert "文献综述" in out
    assert "title match" in out


def test_listing_without_keywords(db, capsys):
    assert run(db) == 0
    out = capsys.readouterr().out
    assert "文献综述" in out
    assert "work选择" in out
    assert "子任务" not in out
    assert "当前会话" not in out


def test_limit(db, capsys):
    assert run(db, "-n", "1") == 0
    out = capsys.readouterr().out
    assert out.count("ses_") == 1
    assert "特殊字符" in out


def test_json_output(db, capsys):
    assert run(db, "清华", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["id"] == "ses_career"
    assert payload[0]["matches"] == 1
    assert payload[0]["title_match"] is False


def test_show(db, capsys):
    assert ses.main(["show", "ses_career", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "work选择" in out
    assert "清华读博" in out
    assert "resume: opencode -s ses_career" in out


def test_show_rejects_ambiguous_prefix(db):
    with pytest.raises(SystemExit):
        ses.main(["show", "ses_", "--db", str(db)])


def test_show_rejects_unknown_id(db):
    with pytest.raises(SystemExit):
        ses.main(["show", "ses_missing", "--db", str(db)])
