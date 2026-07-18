#!/usr/bin/env python3
"""
Resumable crawler for NovinLaw terminology pages.

Default range:
    1 .. 9138

Outputs:
    novinlaw_terminologies/
      raw_html/<id>.html
      terminologies.jsonl
      terminologies.csv
      failures.jsonl
      crawler.log

Install:
    python -m pip install httpx beautifulsoup4 lxml

Run:
    python novinlaw_terminologies_crawler.py

Example with conservative settings:
    python novinlaw_terminologies_crawler.py \
        --start-id 1 \
        --end-id 9138 \
        --concurrency 4 \
        --delay 0.8

Resume:
    Run the same command again. Successful and missing IDs are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import os
import random
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup


URL_TEMPLATE = (
    "https://www.novinlaw.ir/rules/terminologies/"
    "%D8%AA%D8%B1%D9%85%DB%8C%D9%86%D9%88%D9%84%D9%88%DA%98%D9%8A"
    "/show/{id}"
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; NovinLawResearchCrawler/1.0; "
    "+contact: replace-with-your-email@example.com)"
)

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
TERMINAL_STATUS_VALUES = {"ok", "missing"}

CONTENT_SELECTORS = (
    "article",
    "main article",
    ".entry-content",
    ".post-content",
    ".single-content",
    ".single-post-content",
    ".page-content",
    ".content-area",
    ".card-body",
    ".rule-content",
    ".terminology-content",
    "#content",
    "main",
)

TITLE_SELECTORS = (
    "h1",
    ".entry-title",
    ".post-title",
    ".page-title",
    ".card-title",
    "main h2",
    "article h2",
)


@dataclass
class CrawlRecord:
    id: int
    url: str
    status: str
    http_status: int | None
    title: str | None
    term: str | None
    content: str | None
    downloaded_at: str
    sha256: str | None
    source: str
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[ \t\u00a0]+", " ", value).strip()


def clean_multiline_text(value: str | None) -> str:
    if not value:
        return ""
    lines: list[str] = []
    for line in value.splitlines():
        line = normalize_space(line)
        if line:
            lines.append(line)

    # Remove immediately repeated navigation/layout lines.
    deduplicated: list[str] = []
    for line in lines:
        if not deduplicated or line != deduplicated[-1]:
            deduplicated.append(line)
    return "\n".join(deduplicated)


def first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = clean_multiline_text(node.get_text("\n", strip=True))
            if text:
                return text
    return None


def select_main_content(soup: BeautifulSoup) -> str:
    candidates: list[str] = []

    for selector in CONTENT_SELECTORS:
        for node in soup.select(selector):
            text = clean_multiline_text(node.get_text("\n", strip=True))
            if text:
                candidates.append(text)

    # Fallback: inspect likely content-bearing containers.
    if not candidates:
        for node in soup.find_all(["div", "section"], limit=300):
            classes = " ".join(node.get("class", []))
            node_id = node.get("id", "")
            marker = f"{classes} {node_id}".lower()
            if any(
                token in marker
                for token in ("content", "article", "post", "rule", "terminology", "detail")
            ):
                text = clean_multiline_text(node.get_text("\n", strip=True))
                if text:
                    candidates.append(text)

    if candidates:
        # The largest candidate is usually the substantive page content.
        return max(candidates, key=len)

    body = soup.body or soup
    return clean_multiline_text(body.get_text("\n", strip=True))


def strip_layout_noise(content: str, title: str | None) -> str:
    if not content:
        return content

    lines = content.splitlines()
    noise_exact = {
        "خانه",
        "صفحه اصلی",
        "ورود",
        "ثبت نام",
        "جستجو",
        "اشتراک گذاری",
        "چاپ",
        "بازگشت",
    }

    cleaned: list[str] = []
    for line in lines:
        normalized = normalize_space(line)
        if not normalized:
            continue
        if normalized in noise_exact:
            continue
        cleaned.append(normalized)

    # Avoid repeating the title as the first content line.
    if title and cleaned and normalize_space(cleaned[0]) == normalize_space(title):
        cleaned = cleaned[1:]

    return "\n".join(cleaned).strip()


def parse_html(html: str) -> tuple[str | None, str | None, str]:
    soup = BeautifulSoup(html, "lxml")

    for node in soup(["script", "style", "noscript", "svg", "template"]):
        node.decompose()

    title = first_text(soup, TITLE_SELECTORS)
    if not title and soup.title:
        title = normalize_space(soup.title.get_text(" ", strip=True)) or None

    content = select_main_content(soup)
    content = strip_layout_noise(content, title)

    # In these pages the page heading is normally the terminology itself.
    term = title

    return title, term, content


def looks_missing(http_status: int, title: str | None, content: str) -> bool:
    if http_status == 404:
        return True

    title_text = normalize_space(title).lower()
    short_content = normalize_space(content).lower()

    title_markers = (
        "404",
        "not found",
        "page not found",
        "صفحه یافت نشد",
        "صفحه مورد نظر یافت نشد",
    )
    if any(marker in title_text for marker in title_markers):
        return True

    # Only use body markers when the page is short, reducing false positives.
    if len(short_content) < 500:
        body_markers = (
            "page not found",
            "صفحه مورد نظر یافت نشد",
            "اطلاعاتی یافت نشد",
            "موردی یافت نشد",
        )
        if any(marker in short_content for marker in body_markers):
            return True

    return False


def parse_cookie_header(cookie_header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not cookie_header:
        return cookies

    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies[name.strip()] = value.strip()
    return cookies


def load_terminal_ids(jsonl_path: Path) -> set[int]:
    completed: set[int] = set()
    if not jsonl_path.exists():
        return completed

    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                if record.get("status") in TERMINAL_STATUS_VALUES:
                    completed.add(int(record["id"]))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    return completed


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def load_latest_successes(jsonl_path: Path) -> dict[int, dict[str, Any]]:
    latest: dict[int, dict[str, Any]] = {}
    if not jsonl_path.exists():
        return latest

    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
                record_id = int(record["id"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue

            if record.get("status") == "ok":
                latest[record_id] = record

    return latest


def export_csv(jsonl_path: Path, csv_path: Path) -> None:
    records = load_latest_successes(jsonl_path)
    fields = [
        "id",
        "url",
        "status",
        "http_status",
        "title",
        "term",
        "content",
        "downloaded_at",
        "sha256",
        "source",
        "error",
    ]

    tmp_path = csv_path.with_suffix(".csv.tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record_id in sorted(records):
            writer.writerow(records[record_id])
    os.replace(tmp_path, csv_path)


async def robots_allows(
    client: httpx.AsyncClient,
    target_url: str,
    user_agent: str,
    ignore_robots: bool,
) -> bool:
    if ignore_robots:
        logging.warning("robots.txt checking disabled by --ignore-robots")
        return True

    parts = urlsplit(target_url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"

    try:
        response = await client.get(robots_url)
    except httpx.HTTPError as exc:
        logging.warning("Could not fetch robots.txt (%s); continuing cautiously.", exc)
        return True

    if response.status_code >= 400:
        logging.warning(
            "robots.txt returned HTTP %s; continuing cautiously.",
            response.status_code,
        )
        return True

    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(response.text.splitlines())

    allowed = parser.can_fetch(user_agent, target_url)
    if not allowed:
        logging.error(
            "robots.txt disallows this path for the configured User-Agent. "
            "Aborting. Use --ignore-robots only if you have permission."
        )
    return allowed


async def fetch_with_retries(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int,
) -> httpx.Response:
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url)

            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response

            if attempt >= max_retries:
                return response

            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = min(float(retry_after), 120.0)
            else:
                delay = min(2 ** attempt + random.uniform(0.2, 1.0), 60.0)

            logging.warning(
                "Retryable HTTP %s for %s; retrying after %.1fs",
                response.status_code,
                url,
                delay,
            )
            await asyncio.sleep(delay)

        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt >= max_retries:
                raise

            delay = min(2 ** attempt + random.uniform(0.2, 1.0), 60.0)
            logging.warning(
                "Network error for %s: %s; retrying after %.1fs",
                url,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    if last_error:
        raise last_error
    raise RuntimeError(f"Request failed without a response: {url}")


async def process_id(
    item_id: int,
    client: httpx.AsyncClient,
    raw_dir: Path,
    results_path: Path,
    failures_path: Path,
    write_lock: asyncio.Lock,
    max_retries: int,
    delay: float,
) -> CrawlRecord:
    url = URL_TEMPLATE.format(id=item_id)
    html_path = raw_dir / f"{item_id}.html"

    # Recover from a crash that happened after HTML was saved but before JSONL write.
    if html_path.exists() and html_path.stat().st_size > 0:
        raw = html_path.read_bytes()
        html = raw.decode("utf-8", errors="replace")
        title, term, content = parse_html(html)
        digest = hashlib.sha256(raw).hexdigest()

        record = CrawlRecord(
            id=item_id,
            url=url,
            status="ok",
            http_status=200,
            title=title,
            term=term,
            content=content,
            downloaded_at=utc_now(),
            sha256=digest,
            source="cache",
        )
        async with write_lock:
            append_jsonl(results_path, asdict(record))
        logging.info("[%s] parsed cached HTML", item_id)
        return record

    try:
        response = await fetch_with_retries(client, url, max_retries=max_retries)
        http_status = response.status_code

        if http_status == 404:
            record = CrawlRecord(
                id=item_id,
                url=str(response.url),
                status="missing",
                http_status=http_status,
                title=None,
                term=None,
                content=None,
                downloaded_at=utc_now(),
                sha256=None,
                source="network",
            )
        elif http_status >= 400:
            record = CrawlRecord(
                id=item_id,
                url=str(response.url),
                status="error",
                http_status=http_status,
                title=None,
                term=None,
                content=None,
                downloaded_at=utc_now(),
                sha256=None,
                source="network",
                error=f"HTTP {http_status}",
            )
        else:
            raw = response.content
            html = response.text
            title, term, content = parse_html(html)

            if looks_missing(http_status, title, content):
                record = CrawlRecord(
                    id=item_id,
                    url=str(response.url),
                    status="missing",
                    http_status=http_status,
                    title=title,
                    term=term,
                    content=None,
                    downloaded_at=utc_now(),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    source="network",
                )
            else:
                atomic_write_bytes(html_path, raw)
                record = CrawlRecord(
                    id=item_id,
                    url=str(response.url),
                    status="ok",
                    http_status=http_status,
                    title=title,
                    term=term,
                    content=content,
                    downloaded_at=utc_now(),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    source="network",
                )

    except Exception as exc:
        record = CrawlRecord(
            id=item_id,
            url=url,
            status="error",
            http_status=None,
            title=None,
            term=None,
            content=None,
            downloaded_at=utc_now(),
            sha256=None,
            source="network",
            error=f"{type(exc).__name__}: {exc}",
        )

    async with write_lock:
        append_jsonl(results_path, asdict(record))
        if record.status == "error":
            append_jsonl(failures_path, asdict(record))

    if record.status == "ok":
        logging.info("[%s] OK: %s", item_id, record.title or "(no title)")
    elif record.status == "missing":
        logging.info("[%s] missing", item_id)
    else:
        logging.error("[%s] failed: %s", item_id, record.error)

    if delay > 0:
        await asyncio.sleep(delay + random.uniform(0, delay * 0.25))

    return record


async def worker(
    name: str,
    queue: asyncio.Queue[int],
    client: httpx.AsyncClient,
    raw_dir: Path,
    results_path: Path,
    failures_path: Path,
    write_lock: asyncio.Lock,
    max_retries: int,
    delay: float,
    counters: dict[str, int],
) -> None:
    while True:
        try:
            item_id = queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        try:
            record = await process_id(
                item_id=item_id,
                client=client,
                raw_dir=raw_dir,
                results_path=results_path,
                failures_path=failures_path,
                write_lock=write_lock,
                max_retries=max_retries,
                delay=delay,
            )
            counters[record.status] = counters.get(record.status, 0) + 1
            counters["processed"] = counters.get("processed", 0) + 1

            if counters["processed"] % 100 == 0:
                logging.info(
                    "Progress: %s processed | ok=%s missing=%s error=%s remaining=%s",
                    counters["processed"],
                    counters.get("ok", 0),
                    counters.get("missing", 0),
                    counters.get("error", 0),
                    queue.qsize(),
                )
        finally:
            queue.task_done()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl NovinLaw terminology pages by numeric ID."
    )
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--end-id", type=int, default=9138)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Per-worker delay after each request, in seconds.",
    )
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("novinlaw_terminologies"),
    )
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument(
        "--cookie",
        default=None,
        help='Optional Cookie header, e.g. "session=abc; other=value".',
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Skip robots.txt enforcement. Use only when you have permission.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Crawl all IDs again, including completed IDs.",
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.start_id < 1:
        raise ValueError("--start-id must be at least 1")
    if args.end_id < args.start_id:
        raise ValueError("--end-id must be greater than or equal to --start-id")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    if args.delay < 0:
        raise ValueError("--delay cannot be negative")

    output_dir: Path = args.output_dir
    raw_dir = output_dir / "raw_html"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    results_path = output_dir / "terminologies.jsonl"
    csv_path = output_dir / "terminologies.csv"
    failures_path = output_dir / "failures.jsonl"
    log_path = output_dir / "crawler.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )

    completed = set() if args.force else load_terminal_ids(results_path)
    requested_ids = range(args.start_id, args.end_id + 1)
    pending_ids = [item_id for item_id in requested_ids if item_id not in completed]

    logging.info(
        "Range=%s..%s | already completed=%s | pending=%s",
        args.start_id,
        args.end_id,
        len(completed),
        len(pending_ids),
    )

    if not pending_ids:
        export_csv(results_path, csv_path)
        logging.info("Nothing to crawl. CSV refreshed at %s", csv_path)
        return 0

    headers = {
        "User-Agent": args.user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
        "Cache-Control": "no-cache",
    }
    cookies = parse_cookie_header(args.cookie)

    timeout = httpx.Timeout(args.timeout)
    limits = httpx.Limits(
        max_connections=max(args.concurrency, 2),
        max_keepalive_connections=max(args.concurrency, 2),
    )

    async with httpx.AsyncClient(
        headers=headers,
        cookies=cookies,
        timeout=timeout,
        limits=limits,
        follow_redirects=True,
        http2=False,
    ) as client:
        first_url = URL_TEMPLATE.format(id=args.start_id)
        if not await robots_allows(
            client=client,
            target_url=first_url,
            user_agent=args.user_agent,
            ignore_robots=args.ignore_robots,
        ):
            return 2

        queue: asyncio.Queue[int] = asyncio.Queue()
        for item_id in pending_ids:
            queue.put_nowait(item_id)

        write_lock = asyncio.Lock()
        counters: dict[str, int] = {
            "processed": 0,
            "ok": 0,
            "missing": 0,
            "error": 0,
        }

        tasks = [
            asyncio.create_task(
                worker(
                    name=f"worker-{index + 1}",
                    queue=queue,
                    client=client,
                    raw_dir=raw_dir,
                    results_path=results_path,
                    failures_path=failures_path,
                    write_lock=write_lock,
                    max_retries=args.max_retries,
                    delay=args.delay,
                    counters=counters,
                )
            )
            for index in range(args.concurrency)
        ]

        await asyncio.gather(*tasks)

    export_csv(results_path, csv_path)

    logging.info(
        "Finished | ok=%s missing=%s error=%s",
        counters.get("ok", 0),
        counters.get("missing", 0),
        counters.get("error", 0),
    )
    logging.info("JSONL: %s", results_path)
    logging.info("CSV:   %s", csv_path)
    logging.info("HTML:  %s", raw_dir)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted. Run the same command again to resume.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Fatal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
