#!/usr/bin/env python3
"""Fetch a resumable range of public Dadrah question pages into JSONL chunks."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


PAGE_URL_TEMPLATE = "https://www.dadrah.ir/consulting-paper.php?requestID={request_id}"
DEFAULT_START_ID = 800_000
DEFAULT_END_ID = 891_818
DEFAULT_CHUNKS = 10
DEFAULT_DELAY_SECONDS = 1.0
STOP_STATUS_CODES = {401, 403, 429}


class SourceBlockedError(RuntimeError):
    """Raised when Dadrah signals that the whole crawl must stop."""


@dataclass(frozen=True)
class IdChunk:
    number: int
    start_id: int
    end_id: int


class GlobalRateLimiter:
    """Ensure request starts are spaced across all worker threads."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self._lock = threading.Lock()
        self._next_request_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_request_at - now)
            if wait_seconds:
                time.sleep(wait_seconds)
            self._next_request_at = time.monotonic() + self.delay_seconds


def clean_text(element):
    """Extract and normalize text from an HTML element."""
    if element is None:
        return None

    text = element.get_text(" ", strip=True)
    return " ".join(text.split()) or None


def absolute_url(page_url, value):
    """Convert a relative URL to an absolute URL."""
    if not value:
        return None

    return urljoin(page_url, value.strip())


def create_session():
    """Create a requests session with retries."""
    session = requests.Session()

    retry_strategy = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update(
        {
            "User-Agent": "PersianLegalAssistantDadrahFetcher/1.0",
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
        }
    )

    return session


def fetch_html(session, url, *, timeout_seconds):
    """Download HTML from the page."""
    response = session.get(url, timeout=timeout_seconds)
    if response.status_code in STOP_STATUS_CODES:
        raise SourceBlockedError(
            f"Dadrah returned HTTP {response.status_code}; stopping every chunk"
        )
    response.raise_for_status()

    if not response.content:
        raise ValueError("The server returned an empty response.")

    return response.content, response.url


def extract_request_id(page_url):
    """Extract requestID from the URL."""
    query = parse_qs(urlparse(page_url).query)
    values = query.get("requestID", [])

    return values[0] if values else None


def extract_question(soup):
    """Extract question title and text."""
    question_card = soup.select_one(".bg-question")

    if question_card is None:
        return {
            "title": None,
            "text": None,
        }

    return {
        "title": clean_text(
            question_card.select_one(".card-title h3")
        ),
        "text": clean_text(
            question_card.select_one(".card-body")
        ),
    }


def extract_tags(soup, page_url):
    """Extract all page tags."""
    tags = []
    seen = set()

    selectors = (
        ".tags a[href], "
        ".tags .btn-info, "
        "a[rel='tag']"
    )

    for element in soup.select(selectors):
        tag_name = clean_text(element)

        if not tag_name:
            continue

        tag_url = None

        if element.name == "a":
            tag_url = absolute_url(
                page_url,
                element.get("href"),
            )

        unique_key = (tag_name, tag_url)

        if unique_key in seen:
            continue

        seen.add(unique_key)

        tags.append(
            {
                "name": tag_name,
                "url": tag_url,
            }
        )

    return tags


def extract_answer_date_and_time(card):
    """Extract answer date and time."""
    answer_date = None
    answer_time = None

    for item in card.select(".date-time-item"):
        icon = item.select_one("i")
        value = clean_text(item.select_one("span"))

        if icon is None or not value:
            continue

        icon_classes = set(icon.get("class", []))

        if "fa-calendar" in icon_classes:
            answer_date = value

        elif (
            "fa-clock-o" in icon_classes
            or "fa-clock" in icon_classes
        ):
            answer_time = value

    return answer_date, answer_time


def extract_lawyer_city(card):
    """Extract lawyer city."""
    city = clean_text(card.select_one(".lawyer-meta"))

    if city and city.startswith("شهر "):
        city = city.removeprefix("شهر ").strip()

    return city


def extract_consultation_links(card, page_url):
    """Extract lawyer consultation links."""
    phone_url = None
    meeting_url = None

    for link in card.select(".btn-actions a[href]"):
        text = clean_text(link)
        href = absolute_url(page_url, link.get("href"))

        if not text:
            continue

        if "تلفنی" in text:
            phone_url = href

        elif "حضوری" in text:
            meeting_url = href

    return {
        "phone_consultation_url": phone_url,
        "meeting_consultation_url": meeting_url,
    }


def extract_page_content(soup, page_url):
    """Extract one question and its answers without repeating page data."""
    question = extract_question(soup)
    question["tags"] = extract_tags(soup, page_url)

    answers = []

    for answer_number, card in enumerate(
        soup.select(".answer-card"),
        start=1,
    ):
        answer_text = clean_text(
            card.select_one(".answer-text")
        )

        if not answer_text:
            continue

        lawyer_name_element = card.select_one(".lawyer-name")
        lawyer_image_element = card.select_one("img.lawyer-img")

        lawyer_name = clean_text(lawyer_name_element)
        lawyer_city = extract_lawyer_city(card)

        lawyer_profile_url = None

        if lawyer_name_element is not None:
            lawyer_profile_url = absolute_url(
                page_url,
                lawyer_name_element.get("href"),
            )

        lawyer_image_url = None
        lawyer_image_alt = None

        if lawyer_image_element is not None:
            lawyer_image_url = absolute_url(
                page_url,
                lawyer_image_element.get("src"),
            )

            lawyer_image_alt = lawyer_image_element.get("alt")

            if lawyer_image_alt:
                lawyer_image_alt = " ".join(
                    lawyer_image_alt.split()
                )

        answer_date, answer_time = extract_answer_date_and_time(
            card
        )

        consultation_links = extract_consultation_links(
            card,
            page_url,
        )

        answer = {
            "number": answer_number,
            "text": answer_text,
            "date": answer_date,
            "time": answer_time,
            "lawyer": {
                "name": lawyer_name,
                "city": lawyer_city,
                "image_url": lawyer_image_url,
                "image_alt": lawyer_image_alt,
                "profile_url": lawyer_profile_url,
                **consultation_links,
            },
        }

        answers.append(answer)

    return {
        "question": question,
        "answers": answers,
    }


def split_id_range(start_id: int, end_id: int, number_of_chunks: int) -> list[IdChunk]:
    """Split an inclusive integer range into near-equal contiguous chunks."""
    if start_id > end_id:
        raise ValueError("--start-id must be less than or equal to --end-id")
    if number_of_chunks < 1:
        raise ValueError("--chunks must be at least 1")

    total_ids = end_id - start_id + 1
    actual_chunks = min(number_of_chunks, total_ids)
    base_size, remainder = divmod(total_ids, actual_chunks)
    chunks: list[IdChunk] = []
    next_start = start_id

    for index in range(actual_chunks):
        size = base_size + (1 if index < remainder else 0)
        chunk_end = next_start + size - 1
        chunks.append(IdChunk(index + 1, next_start, chunk_end))
        next_start = chunk_end + 1

    return chunks


def chunk_paths(output_directory: Path, chunk: IdChunk) -> tuple[Path, Path]:
    stem = f"chunk_{chunk.number:02d}_{chunk.start_id}_{chunk.end_id}"
    return output_directory / f"{stem}.jsonl", output_directory / f"{stem}.checkpoint.json"


def load_checkpoint(path: Path, chunk: IdChunk) -> dict[str, int]:
    default = {
        "last_processed_id": chunk.start_id - 1,
        "pages_written": 0,
        "answers_written": 0,
        "errors": 0,
    }
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid checkpoint object: {path}")
    if "answers_written" not in data and "records_written" in data:
        data["answers_written"] = data["records_written"]
    for key in default:
        if key in data:
            default[key] = int(data[key])
    if default["last_processed_id"] < chunk.start_id - 1:
        raise ValueError(f"Checkpoint is outside chunk range: {path}")
    return default


def save_checkpoint(path: Path, chunk: IdChunk, state: dict[str, int]) -> None:
    data: dict[str, Any] = {
        "chunk": chunk.number,
        "start_id": chunk.start_id,
        "end_id": chunk.end_id,
        **state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def page_result(
    request_id: int,
    final_url: str,
    content: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request_id": str(request_id),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "page_url": final_url,
        "question": content["question"],
        "answers": content["answers"],
    }


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()


def validate_output_schema(path: Path) -> None:
    """Prevent old and new page schemas from being mixed in one JSONL file."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}") from error
            if not isinstance(row, dict) or "answers" not in row or "records" in row:
                raise ValueError(
                    f"Old JSONL schema found in {path}; use a new output directory "
                    "or convert the existing file before resuming"
                )
            return


def fetch_chunk(
    chunk: IdChunk,
    *,
    output_directory: Path,
    timeout_seconds: float,
    rate_limiter: GlobalRateLimiter,
    stop_event: threading.Event,
) -> dict[str, Any]:
    output_path, checkpoint_path = chunk_paths(output_directory, chunk)
    validate_output_schema(output_path)
    output_path.touch(exist_ok=True)
    state = load_checkpoint(checkpoint_path, chunk)
    first_id = max(chunk.start_id, state["last_processed_id"] + 1)
    session = create_session()

    try:
        for request_id in range(first_id, chunk.end_id + 1):
            if stop_event.is_set():
                break

            rate_limiter.wait()
            url = PAGE_URL_TEMPLATE.format(request_id=request_id)
            try:
                html, final_url = fetch_html(
                    session,
                    url,
                    timeout_seconds=timeout_seconds,
                )
                content = extract_page_content(BeautifulSoup(html, "html.parser"), final_url)
                append_jsonl(output_path, page_result(request_id, final_url, content))
                state["pages_written"] += 1
                state["answers_written"] += len(content["answers"])
            except SourceBlockedError:
                stop_event.set()
                raise
            except requests.exceptions.HTTPError as error:
                # Missing IDs are expected in a numeric range and are recorded
                # so a resumed run does not request them again.
                if error.response is not None and error.response.status_code == 404:
                    append_jsonl(
                        output_path,
                        {
                            "request_id": str(request_id),
                            "page_url": url,
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "status": "not_found",
                            "question": None,
                            "answers": [],
                        },
                    )
                    state["pages_written"] += 1
                else:
                    raise
            except requests.exceptions.RequestException as error:
                # Retries are already exhausted. Record the failure and move on;
                # the checkpoint summary makes such pages reviewable.
                append_jsonl(
                    output_path,
                    {
                        "request_id": str(request_id),
                        "page_url": url,
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "status": "request_error",
                        "error": str(error),
                        "question": None,
                        "answers": [],
                    },
                )
                state["pages_written"] += 1
                state["errors"] += 1

            state["last_processed_id"] = request_id
            save_checkpoint(checkpoint_path, chunk, state)

            if request_id % 100 == 0:
                print(
                    f"chunk={chunk.number:02d} processed={request_id} "
                    f"end={chunk.end_id} answers={state['answers_written']}",
                    file=sys.stderr,
                )
    finally:
        session.close()

    return {
        "chunk": chunk.number,
        "range": [chunk.start_id, chunk.end_id],
        "output": str(output_path),
        "checkpoint": str(checkpoint_path),
        **state,
        "stopped": stop_event.is_set(),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-id", type=int, default=DEFAULT_START_ID)
    parser.add_argument("--end-id", type=int, default=DEFAULT_END_ID)
    parser.add_argument("--chunks", type=int, default=DEFAULT_CHUNKS)
    parser.add_argument("--workers", type=int, default=DEFAULT_CHUNKS)
    parser.add_argument("--output-directory", type=Path, default=Path("dadrah_output"))
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=DEFAULT_DELAY_SECONDS,
        help="Minimum delay between request starts across all threads",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    if args.workers < 1:
        raise ValueError("--workers must be at least 1")
    if args.delay_seconds < 0:
        raise ValueError("--delay-seconds cannot be negative")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than zero")

    chunks = split_id_range(args.start_id, args.end_id, args.chunks)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    rate_limiter = GlobalRateLimiter(args.delay_seconds)
    summaries: list[dict[str, Any]] = []

    with ThreadPoolExecutor(
        max_workers=min(args.workers, len(chunks)),
        thread_name_prefix="dadrah",
    ) as executor:
        futures = {
            executor.submit(
                fetch_chunk,
                chunk,
                output_directory=args.output_directory,
                timeout_seconds=args.timeout_seconds,
                rate_limiter=rate_limiter,
                stop_event=stop_event,
            ): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                summaries.append(future.result())
            except SourceBlockedError as error:
                stop_event.set()
                print(f"blocked: chunk={chunk.number:02d}: {error}", file=sys.stderr)
            except Exception as error:
                stop_event.set()
                print(f"error: chunk={chunk.number:02d}: {error}", file=sys.stderr)

    summaries.sort(key=lambda item: int(item["chunk"]))
    print(json.dumps({"chunks": summaries, "stopped": stop_event.is_set()}, ensure_ascii=False))
    return 3 if stop_event.is_set() else 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
