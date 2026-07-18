#!/usr/bin/env python3
"""Fetch and normalize public lawyer-directory records to canonical JSONL."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT_URL = "https://search-hamivakil.ir/"
ENDPOINT = ROOT_URL + "App/Handler/Lawyer.ashx?Method=mGetLawyerData"
USER_AGENT = "PersianLegalAssistantLawyerFetcher/1.0"
DEFAULT_DELAY_SECONDS = 8.0
POSSIBLE_RESULT_CAP = 300


@dataclass(frozen=True)
class Bar:
    id: str
    name: str


class SourceBlockedError(RuntimeError):
    """Raised when the source signals that collection must stop."""


class HtmlSourceResponseError(SourceBlockedError):
    """Raised when the JSON endpoint returns an HTML/session page."""


class SourceResponseError(RuntimeError):
    """Raised when a successful HTTP response has an unusable body."""


class EmptySourceResponseError(SourceResponseError):
    """Raised when a bar returns no response body after a successful request."""


def _skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_bars(path: Path | None = None) -> list[Bar]:
    source = path or (_skill_root() / "references" / "bars.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("bars.json must contain a JSON array")
    return [Bar(id=str(item["id"]), name=str(item["name"])) for item in data]


def resolve_bars(values: Sequence[str], *, all_bars: bool) -> list[Bar]:
    bars = load_bars()
    if all_bars:
        return bars
    by_key = {bar.id.casefold(): bar for bar in bars}
    by_key.update({bar.name.casefold(): bar for bar in bars})
    resolved: list[Bar] = []
    for value in values:
        try:
            bar = by_key[value.strip().casefold()]
        except KeyError as exc:
            choices = "، ".join(item.name for item in bars)
            raise ValueError(f"Unknown bar {value!r}. Available bars: {choices}") from exc
        if bar not in resolved:
            resolved.append(bar)
    if not resolved:
        raise ValueError("Select at least one --bar or use --all-bars")
    return resolved


def build_opener() -> urllib.request.OpenerDirector:
    cookies = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))


def bootstrap_session(opener: urllib.request.OpenerDirector, timeout: float) -> None:
    request = urllib.request.Request(
        ROOT_URL,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
        method="GET",
    )
    with opener.open(request, timeout=timeout) as response:
        response.read(1)


def reset_session(opener: urllib.request.OpenerDirector, timeout: float) -> None:
    """Clear the current cookie jar and bootstrap one fresh source session."""
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPCookieProcessor):
            handler.cookiejar.clear()
    bootstrap_session(opener, timeout)


def _payload(bar: Bar) -> bytes:
    return json.dumps(
        {
            "license": "",
            "name": "",
            "family": "",
            "nat": "",
            "mob": "",
            "oftel": "",
            "Bar": bar.id,
            "add": "",
            "deg": "",
            "pay": "",
        },
        ensure_ascii=False,
    ).encode("utf-8")


def decode_response(
    raw: bytes, bar: Bar, *, content_type: str
) -> list[dict[str, Any]]:
    body = raw.strip()
    response_description = (
        f"bar={bar.name!r}, content_type={content_type!r}, bytes={len(raw)}"
    )
    if not body:
        raise EmptySourceResponseError(
            f"Source returned an empty body ({response_description})"
        )
    if "html" in content_type.casefold() or body.startswith((b"<", b"\xef\xbb\xbf<")):
        raise HtmlSourceResponseError(
            "Source returned an HTML/access page instead of JSON "
            f"({response_description}); stop and review access"
        )
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceResponseError(
            f"Source returned malformed JSON ({response_description})"
        ) from exc
    if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
        raise SourceResponseError(
            f"Expected a JSON array of lawyer objects ({response_description})"
        )
    return data


def fetch_bar(
    opener: urllib.request.OpenerDirector,
    bar: Bar,
    *,
    timeout: float,
    max_attempts: int,
) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        ENDPOINT,
        data=_payload(bar),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": ROOT_URL.rstrip("/"),
            "Referer": ROOT_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
        method="POST",
    )

    html_session_refreshed = False
    for attempt in range(1, max_attempts + 1):
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
            return decode_response(raw, bar, content_type=content_type)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 429}:
                raise SourceBlockedError(
                    f"Source returned HTTP {exc.code} for {bar.name}; stop and review access"
                ) from exc
            if exc.code < 500 or attempt == max_attempts:
                raise
        except HtmlSourceResponseError:
            # One HTML response may be the site's generic page for a stale
            # ASP.NET session. Refresh the cookie jar once; repeated HTML is
            # treated as confirmed blocking and must stop the run.
            if html_session_refreshed or attempt == max_attempts:
                raise
            html_session_refreshed = True
            reset_session(opener, timeout)
        except SourceResponseError:
            if attempt == max_attempts:
                raise
            # A fresh ASP.NET session can recover a transient unusable body.
            reset_session(opener, timeout)
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_attempts:
                raise
        time.sleep(min(30.0, 2.0**attempt))
    raise RuntimeError("unreachable")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _degree(row: dict[str, Any]) -> str:
    club = row.get("LDBLawyer_To_BITIranLawyerClub_lastLawyerClubId")
    return _clean(club.get("name")) if isinstance(club, dict) else ""


def _source_id(row: dict[str, Any], bar: Bar) -> str:
    source_id = _clean(row.get("id"))
    if source_id:
        return source_id
    fallback = "|".join(
        (
            bar.id,
            _clean(row.get("personNumber")),
            _clean(row.get("name")),
            _clean(row.get("family")),
        )
    )
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:24]


def normalize_record(
    row: dict[str, Any], bar: Bar, *, retrieved_at: str
) -> dict[str, Any] | None:
    source_id = _source_id(row, bar)
    full_name = _clean(f"{_clean(row.get('name'))} {_clean(row.get('family'))}")
    if not full_name:
        return None
    return {
        "lawyer_id": f"hamivakil:{source_id}",
        "full_name": full_name,
        "specialties": [],
        "location": bar.name,
        "success_rate": 0.0,
        "metadata": {
            "source": "search-hamivakil.ir",
            "source_url": ROOT_URL,
            "source_record_id": source_id,
            "source_retrieved_at": retrieved_at,
            "license_number": _clean(row.get("personNumber")),
            "bar_id": bar.id,
            "bar_name": bar.name,
            "sex": _clean(row.get("sex")),
            "professional_state": _clean(row.get("RealNameOfState")),
            "degree": _degree(row),
            "office_address": _clean(row.get("officeAddress")),
        },
    }


def normalize_records(rows: Iterable[dict[str, Any]], bar: Bar) -> list[dict[str, Any]]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    normalized = [normalize_record(row, bar, retrieved_at=retrieved_at) for row in rows]
    return [record for record in normalized if record is not None]


def existing_ids(output: Path) -> set[str]:
    if not output.exists():
        return set()
    ids: set[str] = set()
    with output.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                ids.add(str(row["lawyer_id"]))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid JSONL at {output}:{line_number}") from exc
    return ids


def append_new(output: Path, records: Sequence[dict[str, Any]], known: set[str]) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("a", encoding="utf-8") as handle:
        for record in records:
            lawyer_id = str(record["lawyer_id"])
            if lawyer_id in known:
                continue
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            known.add(lawyer_id)
            written += 1
    return written


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    completed = data.get("completed_bar_ids", []) if isinstance(data, dict) else []
    return {str(item) for item in completed}


def save_checkpoint(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "completed_bar_ids": sorted(completed),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--bar", action="append", default=[], help="Bar name or source ID; repeatable")
    selection.add_argument("--all-bars", action="store_true", help="Fetch every bar sequentially")
    parser.add_argument("--output", type=Path, required=True, help="Canonical JSONL output")
    parser.add_argument("--checkpoint", type=Path, help="Checkpoint JSON path")
    parser.add_argument("--input-json", type=Path, help="Normalize a saved response instead of fetching")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    bars = resolve_bars(args.bar, all_bars=args.all_bars)
    if args.input_json is not None and len(bars) != 1:
        raise ValueError("--input-json requires exactly one --bar")
    if len(bars) > 1 and args.delay_seconds < 2.0:
        raise ValueError("Use at least 2 seconds between multiple bar requests")
    if args.max_attempts < 1 or args.max_attempts > 5:
        raise ValueError("--max-attempts must be between 1 and 5")

    output: Path = args.output
    checkpoint: Path = args.checkpoint or output.with_suffix(output.suffix + ".checkpoint.json")
    known = existing_ids(output)
    completed = load_checkpoint(checkpoint)
    opener: urllib.request.OpenerDirector | None = None

    if args.input_json is None:
        opener = build_opener()
        bootstrap_session(opener, args.timeout_seconds)

    total_written = 0
    empty_bars: list[str] = []
    for index, bar in enumerate(bars):
        if bar.id in completed:
            print(f"skip completed bar: {bar.name}", file=sys.stderr)
            continue
        if args.input_json is not None:
            rows = json.loads(args.input_json.read_text(encoding="utf-8-sig"))
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise ValueError("--input-json must contain an array of objects")
        else:
            assert opener is not None
            try:
                rows = fetch_bar(
                    opener,
                    bar,
                    timeout=args.timeout_seconds,
                    max_attempts=args.max_attempts,
                )
            except EmptySourceResponseError as exc:
                empty_bars.append(bar.name)
                print(f"warning: {exc}; continuing with the next bar", file=sys.stderr)
                # Do not checkpoint this bar as completed: a later resumed run
                # should retry it in case the empty response was transient.
                if index < len(bars) - 1:
                    time.sleep(args.delay_seconds)
                continue

        records = normalize_records(rows, bar)
        written = append_new(output, records, known)
        total_written += written
        print(
            f"bar={bar.name} received={len(rows)} normalized={len(records)} written={written}",
            file=sys.stderr,
        )
        if len(rows) == POSSIBLE_RESULT_CAP:
            print(
                f"warning: {bar.name} returned exactly {POSSIBLE_RESULT_CAP}; result may be truncated",
                file=sys.stderr,
            )
        completed.add(bar.id)
        save_checkpoint(checkpoint, completed)

        if args.input_json is None and index < len(bars) - 1:
            time.sleep(args.delay_seconds)

    print(
        json.dumps(
            {
                "written": total_written,
                "output": str(output),
                "empty_bars": empty_bars,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except SourceBlockedError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError, json.JSONDecodeError, SourceResponseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
