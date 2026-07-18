#!/usr/bin/env python3
"""Polite, resumable crawler for public lawyer profiles on dadrah.ir.

Outputs:
  - dadrah.sqlite3
  - output/lawyers.csv
  - output/lawyers.jsonl
  - output/consultations.jsonl

The crawler uses normal HTTP requests for list/profile pages. For a lawyer's
/advices page, it uses Playwright only when the page contains the dynamic
"مشاهده بیشتر" control, so all publicly displayed consultations can load.

Run a small test first:
    python dadrah_crawler.py --max-list-pages 1 --max-lawyers 3

Then resume the full crawl:
    python dadrah_crawler.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import random
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from playwright.async_api import (
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

BASE_URL = "https://www.dadrah.ir"
LIST_URL = BASE_URL + "/dadrah-lawyers.php?page_num={page}"
DEFAULT_DB = "dadrah.sqlite3"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DATE_RE = re.compile(r"^(?:13|14)\d{2}/\d{1,2}/\d{1,2}$")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
SPACE_RE = re.compile(r"\s+")
BLOCK_TAGS = {"p", "li", "article", "section", "h1", "h2", "h3", "h4", "h5", "h6"}
UI_TEXTS = {
    "مشاهده بیشتر",
    "مشاهده",
    "اشتراک گذاری",
    "خانه",
    "مشاوره ها",
    "مشاوره‌ها",
    "پاسخ",
    "سوال",
}


@dataclass(slots=True)
class Consultation:
    date: str
    title: str
    question: str
    answer: str
    raw_text: str
    source_url: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u200c", " ").replace("\ufeff", " ")
    return SPACE_RE.sub(" ", text).strip()


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = clean_text(value)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def page_strings(soup: BeautifulSoup) -> list[str]:
    return [clean_text(x) for x in soup.stripped_strings if clean_text(x)]


def value_after_label(strings: list[str], labels: Iterable[str]) -> str:
    normalized_labels = {clean_text(label).rstrip(":：") for label in labels}
    for index, item in enumerate(strings):
        key = clean_text(item).rstrip(":：")
        if key in normalized_labels:
            for candidate in strings[index + 1 : index + 5]:
                candidate = clean_text(candidate)
                if candidate and candidate.rstrip(":：") not in normalized_labels:
                    return candidate
    return ""


def find_heading(soup: BeautifulSoup, phrase: str) -> Optional[Tag]:
    phrase = clean_text(phrase)
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if phrase in clean_text(tag.get_text(" ", strip=True)):
            return tag
    return None


def strings_between_headings(heading: Optional[Tag]) -> list[str]:
    """Return visible text after a heading and before the next heading.

    This intentionally works without relying on the site's CSS class names.
    """
    if heading is None:
        return []

    values: list[str] = []
    for element in heading.next_elements:
        if element is heading:
            continue
        # next_elements begins with the heading's own text descendants.
        if isinstance(element, Tag) and heading in element.parents:
            continue
        if isinstance(element, NavigableString) and heading in element.parents:
            continue
        if isinstance(element, Tag) and element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            break
        if isinstance(element, NavigableString):
            text = clean_text(element)
            if text:
                values.append(text)
    return unique_preserving_order(values)


def extract_lawyer_id(url: str) -> str:
    parsed = urlparse(url)
    return parse_qs(parsed.query).get("lawyerID", [""])[0]


def parse_listing(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, str] = {}
    for anchor in soup.select("a[href]"):
        href = urljoin(BASE_URL, anchor.get("href", ""))
        if "lawyer-information.php" not in href or "lawyerID=" not in href:
            continue
        lawyer_id = extract_lawyer_id(href)
        if not lawyer_id:
            continue
        name = clean_text(anchor.get_text(" ", strip=True))
        found[href] = name
    return list(found.items())


def parse_profile(html: str, requested_url: str, final_url: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "lxml")
    strings = page_strings(soup)

    h1 = soup.find("h1")
    name = clean_text(h1.get_text(" ", strip=True)) if h1 else ""

    about = "\n".join(strings_between_headings(find_heading(soup, "درباره من")))
    specialties = strings_between_headings(find_heading(soup, "حوزه‌های تخصصی"))
    # Remove section/button labels that occasionally leak into the section.
    specialties = [
        x
        for x in specialties
        if x not in UI_TEXTS and not DATE_RE.fullmatch(x) and len(x) > 2
    ]

    email = value_after_label(strings, ["ایمیل", "ایمیل:"])
    match = EMAIL_RE.search(email)
    if match:
        email = match.group(0)
    else:
        # Some lawyers put the email in the biography rather than the contact block.
        match = EMAIL_RE.search("\n".join(strings))
        email = match.group(0) if match else ""

    address = value_after_label(strings, ["آدرس", "آدرس:"])

    canonical = final_url.split("#", 1)[0].rstrip("/")
    advice_url = canonical + "/advices"

    return {
        "profile_url": requested_url,
        "lawyer_id": extract_lawyer_id(requested_url),
        "slug_url": canonical,
        "name": name,
        "license_source": value_after_label(
            strings, ["دارای سابقه پروانه وکالت از", "دارای سابقه پروانه وکالت از:"]
        ),
        "license_number": value_after_label(strings, ["شماره پروانه", "شماره پروانه:"]),
        "education": value_after_label(
            strings, ["آخرین مدرک تحصیلی", "آخرین مدرک تحصیلی:"]
        ),
        "city": value_after_label(strings, ["شهر محل فعالیت", "شهر محل فعالیت:"]),
        "about": about,
        "specialties": specialties,
        "email": email,
        "address": address,
        "advice_url": advice_url,
    }


def date_nodes(soup: BeautifulSoup) -> list[NavigableString]:
    result: list[NavigableString] = []
    for node in soup.find_all(string=True):
        if DATE_RE.fullmatch(clean_text(node)):
            result.append(node)
    return result


def count_dates(tag: Tag) -> int:
    return sum(1 for node in tag.find_all(string=True) if DATE_RE.fullmatch(clean_text(node)))


def choose_advice_card(date_node: NavigableString) -> Optional[Tag]:
    """Find the smallest sensible ancestor containing exactly one advice date."""
    candidates: list[Tag] = []
    parent = date_node.parent
    while isinstance(parent, Tag) and parent.name not in {"body", "html"}:
        dcount = count_dates(parent)
        if dcount > 1:
            break
        texts = unique_preserving_order(parent.stripped_strings)
        total = sum(len(x) for x in texts)
        if dcount == 1 and 3 <= len(texts) <= 80 and 20 <= total <= 30000:
            candidates.append(parent)
        parent = parent.parent

    if not candidates:
        return date_node.parent if isinstance(date_node.parent, Tag) else None

    def score(tag: Tag) -> tuple[int, int]:
        attrs = " ".join(
            [tag.get("id", ""), *[str(x) for x in tag.get("class", [])]]
        ).lower()
        hint = 1 if any(x in attrs for x in ("advice", "consult", "question", "item", "card")) else 0
        return (hint, len(clean_text(tag.get_text(" ", strip=True))))

    return max(candidates, key=score)


def leaf_blocks(card: Tag) -> list[str]:
    blocks: list[str] = []
    for tag in card.find_all(True):
        if tag.name not in BLOCK_TAGS and tag.name != "div":
            continue
        # Keep leaf-ish blocks to avoid the same text from parent and child containers.
        child_blocks = tag.find_all(list(BLOCK_TAGS | {"div"}), recursive=False)
        if child_blocks:
            continue
        text = clean_text(tag.get_text(" ", strip=True))
        if text:
            blocks.append(text)
    return unique_preserving_order(blocks)


def text_from_answer_hint(card: Tag) -> str:
    for tag in card.find_all(True):
        attrs = " ".join(
            [tag.get("id", ""), *[str(x) for x in tag.get("class", [])]]
        ).lower()
        itemprop = str(tag.get("itemprop", "")).lower()
        if (
            any(x in attrs for x in ("answer", "reply", "response", "lawyer-answer"))
            or itemprop in {"acceptedanswer", "suggestedanswer", "text"}
        ):
            text = clean_text(tag.get_text(" ", strip=True))
            if len(text) >= 5:
                return text
    return ""


def parse_consultation_card(card: Tag, source_url: str) -> Optional[Consultation]:
    raw_parts = unique_preserving_order(card.stripped_strings)
    dates = [x for x in raw_parts if DATE_RE.fullmatch(x)]
    if not dates:
        return None
    date = dates[0]

    raw_parts = [x for x in raw_parts if x != date and x not in UI_TEXTS]
    if len(raw_parts) < 2:
        return None

    answer = text_from_answer_hint(card)

    title = ""
    for tag in card.find_all(["h2", "h3", "h4", "h5", "h6", "strong", "a"]):
        candidate = clean_text(tag.get_text(" ", strip=True))
        if candidate and candidate not in UI_TEXTS and candidate != date and len(candidate) <= 250:
            title = candidate
            break

    blocks = [x for x in leaf_blocks(card) if x != date and x not in UI_TEXTS]
    if not blocks:
        blocks = raw_parts[:]

    if not title:
        title = blocks[0] if blocks and len(blocks[0]) <= 250 else ""

    if not answer:
        # On the current site, the answer is the final visible block in each card.
        # raw_text is also stored so no information is lost if the layout changes.
        answer = blocks[-1] if len(blocks) >= 2 else ""

    question_parts: list[str] = []
    for part in blocks:
        if part in {date, title, answer} or part in UI_TEXTS:
            continue
        question_parts.append(part)

    # Fallback when the first block contains both title and the opening of the question.
    if not question_parts:
        for part in raw_parts:
            if part not in {title, answer}:
                question_parts.append(part)

    question = "\n".join(unique_preserving_order(question_parts))
    raw_text = "\n".join([date, *raw_parts])

    return Consultation(
        date=date,
        title=title,
        question=question,
        answer=answer,
        raw_text=raw_text,
        source_url=source_url,
    )


def parse_advices(html: str, source_url: str) -> list[Consultation]:
    soup = BeautifulSoup(html, "lxml")
    consultations: list[Consultation] = []
    seen_cards: set[int] = set()

    for node in date_nodes(soup):
        card = choose_advice_card(node)
        if card is None or id(card) in seen_cards:
            continue
        seen_cards.add(id(card))
        item = parse_consultation_card(card, source_url)
        if item:
            consultations.append(item)

    # Exact duplicates can occur when the site repeats a boundary item after load-more.
    deduped: list[Consultation] = []
    seen: set[str] = set()
    for item in consultations:
        key = hashlib.sha256(
            clean_text(item.date + "\n" + item.title + "\n" + item.question + "\n" + item.answer).encode("utf-8")
        ).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.create_schema()

    def create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS listing_pages (
                page_num INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS lawyers (
                profile_url TEXT PRIMARY KEY,
                lawyer_id TEXT,
                slug_url TEXT,
                name TEXT,
                license_source TEXT,
                license_number TEXT,
                education TEXT,
                city TEXT,
                about TEXT,
                specialties_json TEXT NOT NULL DEFAULT '[]',
                email TEXT,
                address TEXT,
                advice_url TEXT,
                detail_status TEXT NOT NULL DEFAULT 'pending',
                advice_status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_lawyers_detail_status ON lawyers(detail_status);
            CREATE INDEX IF NOT EXISTS idx_lawyers_advice_status ON lawyers(advice_status);
            CREATE INDEX IF NOT EXISTS idx_lawyers_lawyer_id ON lawyers(lawyer_id);

            CREATE TABLE IF NOT EXISTS consultations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_url TEXT NOT NULL,
                item_hash TEXT NOT NULL UNIQUE,
                advice_date TEXT,
                title TEXT,
                question TEXT,
                answer TEXT,
                raw_text TEXT,
                source_url TEXT,
                created_at TEXT,
                FOREIGN KEY(profile_url) REFERENCES lawyers(profile_url)
            );

            CREATE INDEX IF NOT EXISTS idx_consultations_profile_url
            ON consultations(profile_url);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def listing_done(self, page_num: int) -> bool:
        row = self.conn.execute(
            "SELECT status FROM listing_pages WHERE page_num=?", (page_num,)
        ).fetchone()
        return bool(row and row["status"] == "done")

    def save_listing_result(
        self, page_num: int, profiles: list[tuple[str, str]], error: str = ""
    ) -> None:
        status = "error" if error else "done"
        self.conn.execute(
            """
            INSERT INTO listing_pages(page_num, status, error, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(page_num) DO UPDATE SET
                status=excluded.status,
                error=excluded.error,
                updated_at=excluded.updated_at
            """,
            (page_num, status, error, now_iso()),
        )
        for profile_url, name in profiles:
            self.conn.execute(
                """
                INSERT INTO lawyers(profile_url, lawyer_id, name, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_url) DO UPDATE SET
                    lawyer_id=COALESCE(NULLIF(excluded.lawyer_id, ''), lawyers.lawyer_id),
                    name=COALESCE(NULLIF(lawyers.name, ''), excluded.name),
                    updated_at=excluded.updated_at
                """,
                (profile_url, extract_lawyer_id(profile_url), name, now_iso()),
            )
        self.conn.commit()

    def pending_profiles(self, limit: Optional[int] = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM lawyers WHERE detail_status != 'done' ORDER BY CAST(lawyer_id AS INTEGER)"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return list(self.conn.execute(sql, params))

    def save_profile(self, data: dict[str, object]) -> None:
        self.conn.execute(
            """
            UPDATE lawyers SET
                lawyer_id=?, slug_url=?, name=?, license_source=?, license_number=?,
                education=?, city=?, about=?, specialties_json=?, email=?, address=?,
                advice_url=?, detail_status='done', advice_status=CASE
                    WHEN advice_status='done' THEN 'done' ELSE 'pending' END,
                error=NULL, updated_at=?
            WHERE profile_url=?
            """,
            (
                data.get("lawyer_id", ""),
                data.get("slug_url", ""),
                data.get("name", ""),
                data.get("license_source", ""),
                data.get("license_number", ""),
                data.get("education", ""),
                data.get("city", ""),
                data.get("about", ""),
                json.dumps(data.get("specialties", []), ensure_ascii=False),
                data.get("email", ""),
                data.get("address", ""),
                data.get("advice_url", ""),
                now_iso(),
                data["profile_url"],
            ),
        )
        self.conn.commit()

    def mark_profile_error(self, profile_url: str, error: str) -> None:
        self.conn.execute(
            "UPDATE lawyers SET detail_status='error', error=?, updated_at=? WHERE profile_url=?",
            (error[:2000], now_iso(), profile_url),
        )
        self.conn.commit()

    def pending_advices(self, limit: Optional[int] = None) -> list[sqlite3.Row]:
        sql = """
            SELECT * FROM lawyers
            WHERE detail_status='done'
              AND advice_status!='done'
              AND COALESCE(advice_url, '')!=''
            ORDER BY CAST(lawyer_id AS INTEGER)
        """
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return list(self.conn.execute(sql, params))

    def save_consultations(
        self, profile_url: str, items: list[Consultation], source_url: str
    ) -> None:
        for item in items:
            canonical = clean_text(
                item.date + "\n" + item.title + "\n" + item.question + "\n" + item.answer
            )
            item_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.conn.execute(
                """
                INSERT OR IGNORE INTO consultations(
                    profile_url, item_hash, advice_date, title, question, answer,
                    raw_text, source_url, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_url,
                    item_hash,
                    item.date,
                    item.title,
                    item.question,
                    item.answer,
                    item.raw_text,
                    source_url,
                    now_iso(),
                ),
            )
        self.conn.execute(
            "UPDATE lawyers SET advice_status='done', error=NULL, updated_at=? WHERE profile_url=?",
            (now_iso(), profile_url),
        )
        self.conn.commit()

    def mark_advice_error(self, profile_url: str, error: str) -> None:
        self.conn.execute(
            "UPDATE lawyers SET advice_status='error', error=?, updated_at=? WHERE profile_url=?",
            (error[:2000], now_iso(), profile_url),
        )
        self.conn.commit()

    def reset_errors(self) -> None:
        self.conn.execute(
            "UPDATE lawyers SET detail_status='pending' WHERE detail_status='error'"
        )
        self.conn.execute(
            "UPDATE lawyers SET advice_status='pending' WHERE advice_status='error'"
        )
        self.conn.execute(
            "UPDATE listing_pages SET status='pending' WHERE status='error'"
        )
        self.conn.commit()


class DadrahCrawler:
    def __init__(self, args: argparse.Namespace, db: Database):
        self.args = args
        self.db = db
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": args.user_agent,
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(args.timeout),
            http2=True,
            limits=httpx.Limits(
                max_connections=max(args.detail_concurrency + 2, 4),
                max_keepalive_connections=max(args.detail_concurrency, 2),
            ),
        )
        self.db_lock = asyncio.Lock()
        self.robots: Optional[RobotFileParser] = None

    async def close(self) -> None:
        await self.client.aclose()

    async def polite_sleep(self) -> None:
        await asyncio.sleep(random.uniform(self.args.delay_min, self.args.delay_max))

    async def initialize_robots(self) -> None:
        if not self.args.respect_robots:
            return
        robots_url = BASE_URL + "/robots.txt"
        try:
            response = await self.client.get(robots_url)
            if response.status_code == 200 and response.text.strip():
                parser = RobotFileParser()
                parser.set_url(robots_url)
                parser.parse(response.text.splitlines())
                self.robots = parser
                logging.info("Loaded robots.txt")
            else:
                logging.warning(
                    "robots.txt was empty or unavailable (HTTP %s); continuing cautiously",
                    response.status_code,
                )
        except Exception as exc:  # noqa: BLE001
            logging.warning("Could not read robots.txt: %s; continuing cautiously", exc)

    def allowed(self, url: str) -> bool:
        if self.robots is None:
            return True
        return self.robots.can_fetch(self.args.user_agent, url)

    async def fetch(self, url: str) -> httpx.Response:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows: {url}")

        last_error: Optional[Exception] = None
        for attempt in range(1, self.args.retries + 1):
            try:
                response = await self.client.get(url)
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 2**attempt)
                    logging.warning("HTTP 429 for %s; sleeping %.1fs", url, delay)
                    await asyncio.sleep(delay)
                    continue
                if response.status_code in {403, 401}:
                    raise PermissionError(
                        f"HTTP {response.status_code}; stopping rather than bypassing access controls: {url}"
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, PermissionError) as exc:
                last_error = exc
                if isinstance(exc, PermissionError):
                    raise
                if attempt < self.args.retries:
                    await asyncio.sleep(min(30, 2**attempt + random.random()))
        raise RuntimeError(f"Failed after {self.args.retries} attempts: {url}: {last_error}")

    async def crawl_listing_pages(self) -> None:
        max_pages = self.args.max_list_pages or self.args.total_list_pages
        logging.info("Crawling lawyer list pages 1..%d", max_pages)
        for page_num in range(1, max_pages + 1):
            if self.db.listing_done(page_num):
                continue
            url = LIST_URL.format(page=page_num)
            try:
                response = await self.fetch(url)
                profiles = parse_listing(response.text)
                if not profiles:
                    raise ValueError("No lawyer profile links found; site layout may have changed")
                async with self.db_lock:
                    self.db.save_listing_result(page_num, profiles)
                logging.info("List page %d: %d profile links", page_num, len(profiles))
            except Exception as exc:  # noqa: BLE001
                logging.exception("List page %d failed", page_num)
                async with self.db_lock:
                    self.db.save_listing_result(page_num, [], str(exc))
                if isinstance(exc, PermissionError):
                    raise
            await self.polite_sleep()

    async def crawl_profiles(self) -> None:
        rows = self.db.pending_profiles(self.args.max_lawyers)
        if not rows:
            logging.info("No pending lawyer profiles")
            return

        logging.info("Crawling %d lawyer profile(s)", len(rows))
        queue: asyncio.Queue[Optional[sqlite3.Row]] = asyncio.Queue()
        for row in rows:
            queue.put_nowait(row)
        for _ in range(self.args.detail_concurrency):
            queue.put_nowait(None)

        fatal_event = asyncio.Event()
        fatal_messages: list[str] = []

        async def worker(worker_id: int) -> None:
            while True:
                row = await queue.get()
                if row is None:
                    queue.task_done()
                    return
                if fatal_event.is_set():
                    # Drain the queue cleanly without issuing more requests.
                    queue.task_done()
                    continue
                profile_url = row["profile_url"]
                try:
                    response = await self.fetch(profile_url)
                    data = parse_profile(response.text, profile_url, str(response.url))
                    if not data.get("name"):
                        raise ValueError("Profile name not found; site layout may have changed")
                    async with self.db_lock:
                        self.db.save_profile(data)
                    logging.info("Profile worker %d: %s", worker_id, data.get("name"))
                except Exception as exc:  # noqa: BLE001
                    logging.exception("Profile failed: %s", profile_url)
                    async with self.db_lock:
                        self.db.mark_profile_error(profile_url, str(exc))
                    if isinstance(exc, PermissionError):
                        fatal_messages.append(str(exc))
                        fatal_event.set()
                finally:
                    queue.task_done()
                    if not fatal_event.is_set():
                        await self.polite_sleep()

        tasks = [
            asyncio.create_task(worker(i + 1))
            for i in range(self.args.detail_concurrency)
        ]
        await queue.join()
        await asyncio.gather(*tasks)
        if fatal_event.is_set():
            raise PermissionError(fatal_messages[0] if fatal_messages else "Access denied")

    async def render_all_advices(
        self, context: BrowserContext, url: str
    ) -> str:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.args.browser_timeout * 1000)
            await page.wait_for_timeout(500)

            unchanged_rounds = 0
            for click_num in range(self.args.max_load_more_clicks):
                locator = page.get_by_text("مشاهده بیشتر", exact=True)
                count = await locator.count()
                target = None
                for index in range(count):
                    candidate = locator.nth(index)
                    if await candidate.is_visible():
                        target = candidate
                        break
                if target is None:
                    break

                before_len = len(await page.locator("body").inner_text())
                try:
                    await target.scroll_into_view_if_needed()
                    await target.click(timeout=5000)
                except Exception:  # noqa: BLE001
                    await target.evaluate("el => el.click()")

                try:
                    await page.wait_for_function(
                        "n => document.body.innerText.length > n",
                        arg=before_len,
                        timeout=self.args.load_more_timeout * 1000,
                    )
                    unchanged_rounds = 0
                except PlaywrightTimeoutError:
                    unchanged_rounds += 1
                    if unchanged_rounds >= 2:
                        logging.warning(
                            "Load-more stopped changing content after %d clicks: %s",
                            click_num + 1,
                            url,
                        )
                        break
                await page.wait_for_timeout(self.args.load_more_pause_ms)

            return await page.content()
        finally:
            await page.close()

    async def crawl_advices(self) -> None:
        if self.args.skip_advices:
            logging.info("Skipping consultations because --skip-advices was supplied")
            return

        rows = self.db.pending_advices(self.args.max_lawyers)
        if not rows:
            logging.info("No pending consultation pages")
            return

        logging.info("Crawling consultations for %d lawyer(s)", len(rows))
        queue: asyncio.Queue[Optional[sqlite3.Row]] = asyncio.Queue()
        for row in rows:
            queue.put_nowait(row)
        for _ in range(self.args.advice_concurrency):
            queue.put_nowait(None)

        fatal_event = asyncio.Event()
        fatal_messages: list[str] = []

        async with async_playwright() as playwright:
            browser: Browser = await playwright.chromium.launch(headless=not self.args.headful)
            context = await browser.new_context(
                user_agent=self.args.user_agent,
                locale="fa-IR",
            )

            async def worker(worker_id: int) -> None:
                while True:
                    row = await queue.get()
                    if row is None:
                        queue.task_done()
                        return
                    if fatal_event.is_set():
                        queue.task_done()
                        continue
                    profile_url = row["profile_url"]
                    advice_url = row["advice_url"]
                    try:
                        response = await self.fetch(advice_url)
                        html = response.text
                        # Use a browser only if the server-rendered page says more items exist.
                        if "مشاهده بیشتر" in clean_text(BeautifulSoup(html, "lxml").get_text(" ", strip=True)):
                            html = await self.render_all_advices(context, advice_url)
                        items = parse_advices(html, advice_url)
                        async with self.db_lock:
                            self.db.save_consultations(profile_url, items, advice_url)
                        logging.info(
                            "Advice worker %d: %s -> %d item(s)",
                            worker_id,
                            row["name"] or row["lawyer_id"],
                            len(items),
                        )
                    except Exception as exc:  # noqa: BLE001
                        logging.exception("Advice page failed: %s", advice_url)
                        async with self.db_lock:
                            self.db.mark_advice_error(profile_url, str(exc))
                        if isinstance(exc, PermissionError):
                            fatal_messages.append(str(exc))
                            fatal_event.set()
                    finally:
                        queue.task_done()
                        if not fatal_event.is_set():
                            await self.polite_sleep()

            tasks = [
                asyncio.create_task(worker(i + 1))
                for i in range(self.args.advice_concurrency)
            ]
            await queue.join()
            await asyncio.gather(*tasks)
            await context.close()
            await browser.close()
            if fatal_event.is_set():
                raise PermissionError(fatal_messages[0] if fatal_messages else "Access denied")


def export_data(db: Database, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    lawyer_rows = list(
        db.conn.execute(
            """
            SELECT l.*,
                   (SELECT COUNT(*) FROM consultations c WHERE c.profile_url=l.profile_url)
                   AS consultation_count
            FROM lawyers l
            ORDER BY CAST(lawyer_id AS INTEGER)
            """
        )
    )

    lawyer_fields = [
        "lawyer_id",
        "name",
        "profile_url",
        "slug_url",
        "license_source",
        "license_number",
        "education",
        "city",
        "about",
        "specialties",
        "email",
        "address",
        "advice_url",
        "consultation_count",
        "detail_status",
        "advice_status",
        "error",
    ]

    with (output_dir / "lawyers.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=lawyer_fields)
        writer.writeheader()
        for row in lawyer_rows:
            item = dict(row)
            try:
                specialties = json.loads(item.get("specialties_json") or "[]")
            except json.JSONDecodeError:
                specialties = []
            item["specialties"] = " | ".join(specialties)
            writer.writerow({field: item.get(field, "") for field in lawyer_fields})

    with (output_dir / "lawyers.jsonl").open("w", encoding="utf-8") as f:
        for row in lawyer_rows:
            item = dict(row)
            try:
                item["specialties"] = json.loads(item.pop("specialties_json") or "[]")
            except json.JSONDecodeError:
                item["specialties"] = []
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    consultation_rows = db.conn.execute(
        """
        SELECT c.*, l.lawyer_id, l.name AS lawyer_name, l.slug_url
        FROM consultations c
        JOIN lawyers l ON l.profile_url=c.profile_url
        ORDER BY CAST(l.lawyer_id AS INTEGER), c.id
        """
    )
    with (output_dir / "consultations.jsonl").open("w", encoding="utf-8") as f:
        for row in consultation_rows:
            f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")

    logging.info("Exported data to %s", output_dir.resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--total-list-pages",
        type=int,
        default=214,
        help="Known number of list pages; update this if the site changes",
    )
    parser.add_argument(
        "--max-list-pages",
        type=int,
        default=None,
        help="Only crawl the first N list pages (useful for testing)",
    )
    parser.add_argument(
        "--max-lawyers",
        type=int,
        default=None,
        help="Process at most N pending lawyers in each phase",
    )
    parser.add_argument("--detail-concurrency", type=int, default=2)
    parser.add_argument("--advice-concurrency", type=int, default=1)
    parser.add_argument("--delay-min", type=float, default=1.5)
    parser.add_argument("--delay-max", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--browser-timeout", type=int, default=45)
    parser.add_argument("--load-more-timeout", type=int, default=12)
    parser.add_argument("--load-more-pause-ms", type=int, default=600)
    parser.add_argument("--max-load-more-clicks", type=int, default=2000)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--skip-advices", action="store_true")
    parser.add_argument("--headful", action="store_true", help="Show Chromium while crawling")
    parser.add_argument("--reset-errors", action="store_true")
    parser.add_argument(
        "--no-respect-robots",
        dest="respect_robots",
        action="store_false",
        help="Do not parse robots.txt (not recommended)",
    )
    parser.set_defaults(respect_robots=True)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.delay_min < 0 or args.delay_max < args.delay_min:
        raise ValueError("Invalid delay range")
    if args.detail_concurrency < 1 or args.advice_concurrency < 1:
        raise ValueError("Concurrency values must be >= 1")

    db = Database(Path(args.db))
    if args.reset_errors:
        db.reset_errors()

    crawler = DadrahCrawler(args, db)
    try:
        await crawler.initialize_robots()
        await crawler.crawl_listing_pages()
        await crawler.crawl_profiles()
        await crawler.crawl_advices()
        export_data(db, Path(args.output_dir))
    finally:
        await crawler.close()
        db.close()
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logging.warning("Interrupted. Progress is already saved; rerun the same command to resume.")
        return 130
    except Exception as exc:  # noqa: BLE001
        logging.exception("Crawler stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
