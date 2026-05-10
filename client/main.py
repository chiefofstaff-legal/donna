"""DONNA client CLI — v0.7.

Usage:
    python main.py                  # text REPL
    python main.py --voice          # voice mode (microphone → Whisper → router)
    python main.py --pipe           # stdin → stdout JSON, one transcript per line
    python main.py --history        # print today's logged time entries
    python main.py --export-today   # export today's entries (default: csv)
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass

from donna.config import load_config
from donna.models import ClarifyRequest, ParseError, Task, TimeEntry
from donna.router import Router

VERSION = "0.7"

BANNER_TEXT = (
    f"\n  DONNA v{VERSION} — speak your day, log it.\n"
    "  Type a time entry or delegation. 'exit' to quit.\n"
)

BANNER_VOICE = (
    f"\n  DONNA v{VERSION} — voice mode.\n"
    "  Press Enter to start recording. Press Enter again to stop.\n"
    "  Ctrl+C to quit.\n"
)


_SERIALISE_KIND = {
    TimeEntry: "timeentry",
    Task: "task",
    ClarifyRequest: "clarify",
}


def _serialise(result) -> dict:
    kind = _SERIALISE_KIND.get(type(result))
    if kind is not None:
        return {"kind": kind, **result.to_dict()}
    if is_dataclass(result):
        return asdict(result)
    return {"kind": "unknown", "value": str(result)}


def _format_time_entry(entry: TimeEntry) -> str:
    parts = [f"matter={entry.matter or '?'}", f"hours={entry.duration_hours or '?'}"]
    if entry.activity:
        parts.append(f"activity={entry.activity}")
    if entry.narrative:
        parts.append(f"narrative={entry.narrative!r}")
    parts.append(f"confidence={entry.confidence:.2f}")
    return "TIME ENTRY  " + " | ".join(parts)


def _format_task(task: Task) -> str:
    parts = [f"assignee={task.assignee or '?'}", f"task={task.task or '?'}"]
    if task.deadline:
        parts.append(f"deadline={task.deadline}")
    if task.matter:
        parts.append(f"matter={task.matter}")
    parts.append(f"priority={task.priority}")
    parts.append(f"confidence={task.confidence:.2f}")
    return "TASK        " + " | ".join(parts)


def _format_clarify(request: ClarifyRequest) -> str:
    return f"CLARIFY     {request.question}"


_FORMATTERS = {
    TimeEntry: _format_time_entry,
    Task: _format_task,
    ClarifyRequest: _format_clarify,
}


def _format(result) -> str:
    formatter = _FORMATTERS.get(type(result))
    return formatter(result) if formatter else str(result)


def _process(router: Router, line: str, as_json: bool) -> None:
    try:
        result = router.handle(line)
    except ParseError as exc:
        if as_json:
            print(json.dumps({"kind": "error", "message": str(exc)}))
        else:
            print(f"ERROR       {exc}")
        return
    if as_json:
        print(json.dumps(_serialise(result), default=str))
    else:
        print(_format(result))


def run_pipe(router: Router) -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        _process(router, line, as_json=True)
    return 0


def run_repl(router: Router) -> int:
    print(BANNER_TEXT)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            return 0
        _process(router, line, as_json=False)


def run_voice(config, tts_enabled: bool = True) -> int:
    from donna.models import ParseError as DonnaParseError
    from donna.store import TimeEntryStore
    from donna.voice_pipeline import VoicePipeline, VoicePipelineError

    print(BANNER_VOICE)
    store = TimeEntryStore(config.cache_db)
    pipeline = VoicePipeline.from_config(config, tts_enabled=tts_enabled)
    while True:
        try:
            input("  [Enter to record] ")
        except (EOFError, KeyboardInterrupt):
            print()
            pipeline.speak(store.daily_summary())
            return 0
        try:
            result = pipeline.run_once(prompt="  Recording… (press Enter to stop)")
        except VoicePipelineError as exc:
            print(f"PIPELINE    {exc}")
            continue
        except DonnaParseError as exc:
            print(f"ERROR       {exc}")
            continue
        print(_format(result))
        if config.webhook_url:
            from donna.webhook import post as _webhook_post
            _webhook_post(config.webhook_url, _serialise(result))


def _today_range():
    """Return (start, end) datetime for the current calendar day."""
    from datetime import datetime
    today = datetime.now()
    return (
        today.replace(hour=0, minute=0, second=0, microsecond=0),
        today.replace(hour=23, minute=59, second=59, microsecond=999999),
    )


def run_history(config) -> int:
    """Print today's time entries as a formatted table."""
    from donna.store import TimeEntryStore

    store = TimeEntryStore(config.cache_db)
    start, end = _today_range()
    entries = store.query(start, end)
    if not entries:
        print("No time logged today.")
        return 0
    print(f"\n{'Matter':<20} {'Hours':>6}  Activity")
    print("-" * 50)
    for e in entries:
        matter = (e.matter or "—")[:20]
        hours = f"{(e.duration_hours or 0):.2f}h"
        activity = e.activity or ""
        print(f"{matter:<20} {hours:>6}  {activity}")
    total = sum(e.duration_hours or 0 for e in entries)
    print("-" * 50)
    print(f"{'Total':<20} {total:.2f}h")
    return 0


def run_export_today(config, fmt: str = "csv") -> int:
    """Export today's time entries to stdout."""
    from donna.export import export_range
    from donna.store import TimeEntryStore

    store = TimeEntryStore(config.cache_db)
    start, end = _today_range()
    entries = store.query(start, end)
    print(export_range(entries, fmt=fmt))
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser. Modes are mutually exclusive; default is REPL."""
    parser = argparse.ArgumentParser(
        prog="donna",
        description="DONNA voice surface — delegation orchestration for legal practice.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--pipe", action="store_true",
        help="stdin → stdout JSON, one transcript per line",
    )
    mode.add_argument(
        "--voice", action="store_true",
        help="microphone → Whisper → router",
    )
    mode.add_argument(
        "--history", action="store_true",
        help="print today's logged time entries as a table",
    )
    mode.add_argument(
        "--export-today", action="store_true",
        help="export today's entries to stdout (--format csv|json)",
    )
    parser.add_argument(
        "--no-tts", dest="tts_enabled", action="store_false", default=True,
        help="disable spoken confirmation in voice mode",
    )
    parser.add_argument(
        "--format", choices=("csv", "json"), default="csv",
        help="export format for --export-today (default: csv)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        config = load_config()
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.pipe:
        return run_pipe(Router(config))
    if args.history:
        return run_history(config)
    if args.export_today:
        return run_export_today(config, fmt=args.format)
    if args.voice:
        return run_voice(config, tts_enabled=args.tts_enabled)
    return run_repl(Router(config))


if __name__ == "__main__":
    raise SystemExit(main())
