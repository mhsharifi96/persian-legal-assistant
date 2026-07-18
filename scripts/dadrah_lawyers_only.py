#!/usr/bin/env python3
"""Crawl only public lawyer profiles from dadrah.ir using HTTPX + BeautifulSoup4.

Extracts:
- lawyer id
- name
- profile URL
- canonical/slug URL
- specialties (حوزه‌های تخصصی)
- email
- address
- city

No consultation/advice pages are requested.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import random
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

BASE_URL = "https://www.dadrah.ir"
LIST_URL = BASE_URL + "/dadrah-lawyers.php?page_num={page}"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SPACE_RE = re.compile(r"\s+")
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


@dataclass(slots=True)
class LawyerLink:
    lawyer_id: str
    profile_url: str
    listing_name: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_fa(value: str) -> str:
    return (
        value.replace("ي", "ی")
        .replace("ك", "ک")
        .replace("ۀ", "ه")
        .replace("ة", "ه")
        .replace("\u200c", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
    )


def clean_text(value: object) -> str:
    return SPACE_RE.sub(" ", normalize_fa(str(value or ""))).strip(" \t\r\n:：-")


def unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = clean_text(value)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def extract_lawyer_id(url: str) -> str:
    return parse_qs(urlparse(url).query).get("lawyerID", [""])[0]


LISTING_BUTTON_TEXTS = {
    "مشاهده سوابق",
    "مشاهده پروفایل",
    "مشاهده اطلاعات",
    "اطلاعات بیشتر",
}


def listing_name_for_anchor(anchor: Tag) -> str:
    """Find the lawyer name in the card containing a profile button/link."""
    direct = clean_text(anchor.get_text(" ", strip=True))
    if direct and direct not in LISTING_BUTTON_TEXTS:
        return direct

    # Dadrah's profile URL is commonly attached to a button whose text is
    # "مشاهده سوابق". Search the surrounding card for the actual heading/name.
    ancestors = []
    current = anchor.parent
    while isinstance(current, Tag) and len(ancestors) < 7:
        ancestors.append(current)
        current = current.parent

    selectors = (
        "[itemprop='name']",
        ".lawyer-name",
        ".user-name",
        ".profile-name",
        ".name",
        "h1", "h2", "h3", "h4", "h5",
    )
    for container in ancestors:
        for selector in selectors:
            for node in container.select(selector):
                text = clean_text(node.get_text(" ", strip=True))
                if (
                    text
                    and text not in LISTING_BUTTON_TEXTS
                    and "مشاهده" not in text
                    and len(text) <= 120
                ):
                    return text

        image = container.find("img", alt=True)
        if image:
            alt = clean_text(image.get("alt", ""))
            if alt and alt not in LISTING_BUTTON_TEXTS and len(alt) <= 120:
                return alt

    return ""


def parse_listing(html: str) -> list[LawyerLink]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, LawyerLink] = {}

    for anchor in soup.select("a[href]"):
        href = urljoin(BASE_URL, str(anchor.get("href", "")))
        if "lawyer-information.php" not in href or "lawyerID=" not in href:
            continue

        lawyer_id = extract_lawyer_id(href)
        if not lawyer_id:
            continue

        # Remove fragments while preserving the original query parameters.
        href = href.split("#", 1)[0]
        found[href] = LawyerLink(
            lawyer_id=lawyer_id,
            profile_url=href,
            listing_name=listing_name_for_anchor(anchor),
        )

    return list(found.values())


def heading_matches(tag: Tag, label: str) -> bool:
    if tag.name not in {"h1", "h2", "h3", "h4", "h5", "h6", "div", "span", "p"}:
        return False
    return clean_text(tag.get_text(" ", strip=True)) == clean_text(label)


def find_heading(soup: BeautifulSoup, label: str) -> Tag | None:
    # Prefer semantic headings, then fall back to exact visible labels.
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if heading_matches(tag, label):
            return tag
    for tag in soup.find_all(["div", "span", "p"]):
        if heading_matches(tag, label):
            return tag
    return None


def strings_after_heading(heading: Tag | None) -> list[str]:
    """Collect visible text after a section heading until the next heading."""
    if heading is None:
        return []

    values: list[str] = []
    for element in heading.next_elements:
        if element is heading:
            continue
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
    return unique(values)


def page_strings(soup: BeautifulSoup) -> list[str]:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    # Keep duplicates. Positional parsing depends on the second occurrence of
    # values such as a city appearing once under "شهر محل فعالیت" and again
    # under "آدرس". The previous global unique() call removed that occurrence.
    return [text for text in (clean_text(x) for x in soup.stripped_strings) if text]


FIELD_OR_SECTION_LABELS = {
    "ایمیل",
    "آدرس",
    "نشانی",
    "شهر",
    "شهر محل فعالیت",
    "شماره تماس",
    "تلفن",
    "موبایل",
    "شبکه های اجتماعی من",
    "شبکه‌های اجتماعی من",
    "اشتراک گذاری وب سایت من",
    "اشتراک‌گذاری وب سایت من",
    "ارتباط با من",
}


def value_after_label(strings: list[str], labels: Iterable[str]) -> str:
    normalized_labels = sorted(
        {clean_text(label) for label in labels}, key=len, reverse=True
    )
    stop_labels = {clean_text(value) for value in FIELD_OR_SECTION_LABELS}

    for index, text in enumerate(strings):
        normalized = clean_text(text)

        # Label and value in consecutive nodes. Check exact labels before
        # shorter-prefix labels such as "شهر" vs. "شهر محل فعالیت".
        if normalized in normalized_labels:
            for candidate in strings[index + 1 : index + 6]:
                candidate = clean_text(candidate)
                if not candidate:
                    continue
                if candidate in normalized_labels:
                    continue
                # An empty field is often followed immediately by the next
                # contact-section label. Do not mistake that label for a value.
                if candidate in stop_labels or candidate.endswith(":"):
                    return ""
                return candidate

        # Label and value in the same text node: "آدرس: تهران ..."
        for label in normalized_labels:
            if normalized.startswith(label + " "):
                value = clean_text(normalized[len(label) :])
                if value and value not in stop_labels:
                    return value

    return ""


def parse_profile(
    html: str,
    requested_url: str,
    final_url: str,
    listing_name: str = "",
) -> dict[str, object]:
    soup = BeautifulSoup(html, "lxml")

    # Extract the name before page_strings() removes non-visible elements.
    h1 = soup.find("h1")
    name = clean_text(h1.get_text(" ", strip=True)) if h1 else clean_text(listing_name)
    if not name:
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title:
            name = clean_text(og_title.get("content", ""))

    specialty_heading = find_heading(soup, "حوزه های تخصصی")
    specialties = strings_after_heading(specialty_heading)
    ignored = {
        "مشاهده بیشتر",
        "مشاوره های انجام شده",
        "مشاوره ها",
        "درباره من",
        "اطلاعات تماس",
        "اشتراک گذاری",
    }
    specialties = [
        value
        for value in specialties
        if value not in ignored
        and "@" not in value
        and len(value) >= 2
        and not value.startswith(("آدرس", "ایمیل", "شماره تماس"))
    ]

    strings = page_strings(soup)

    email = value_after_label(strings, ["ایمیل"])
    email_match = EMAIL_RE.search(email) or EMAIL_RE.search("\n".join(strings))
    email = email_match.group(0) if email_match else ""

    address = value_after_label(strings, ["آدرس", "نشانی"])
    city = value_after_label(strings, ["شهر محل فعالیت", "شهر"])

    canonical = final_url.split("#", 1)[0].rstrip("/")

    return {
        "lawyer_id": extract_lawyer_id(requested_url),
        "name": name,
        "profile_url": requested_url,
        "slug_url": canonical,
        "city": city,
        "specialties": specialties,
        "email": email,
        "address": address,
    }


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lawyers (
                profile_url TEXT PRIMARY KEY,
                lawyer_id TEXT,
                listing_name TEXT,
                name TEXT,
                slug_url TEXT,
                city TEXT,
                specialties_json TEXT NOT NULL DEFAULT '[]',
                email TEXT,
                address TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                updated_at TEXT
            )
            """
        )
        self.conn.commit()

    def add_links(self, links: Iterable[LawyerLink]) -> int:
        before = self.conn.total_changes
        self.conn.executemany(
            """
            INSERT INTO lawyers(profile_url, lawyer_id, listing_name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_url) DO UPDATE SET
                lawyer_id=excluded.lawyer_id,
                listing_name=CASE
                    WHEN lawyers.listing_name IS NULL OR lawyers.listing_name=''
                    THEN excluded.listing_name ELSE lawyers.listing_name END,
                updated_at=excluded.updated_at
            """,
            [
                (link.profile_url, link.lawyer_id, link.listing_name, now_iso())
                for link in links
            ],
        )
        self.conn.commit()
        return self.conn.total_changes - before

    def pending(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM lawyers WHERE status != 'done' ORDER BY CAST(lawyer_id AS INTEGER)"
        params: tuple[object, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        return list(self.conn.execute(sql, params))

    def save(self, data: dict[str, object]) -> None:
        self.conn.execute(
            """
            UPDATE lawyers SET
                name=?, slug_url=?, city=?, specialties_json=?, email=?, address=?,
                status='done', error=NULL, updated_at=?
            WHERE profile_url=?
            """,
            (
                data.get("name", ""),
                data.get("slug_url", ""),
                data.get("city", ""),
                json.dumps(data.get("specialties", []), ensure_ascii=False),
                data.get("email", ""),
                data.get("address", ""),
                now_iso(),
                data["profile_url"],
            ),
        )
        self.conn.commit()

    def mark_error(self, profile_url: str, error: str) -> None:
        self.conn.execute(
            "UPDATE lawyers SET status='error', error=?, updated_at=? WHERE profile_url=?",
            (error[:2000], now_iso(), profile_url),
        )
        self.conn.commit()

    def reset_errors(self) -> None:
        self.conn.execute("UPDATE lawyers SET status='pending', error=NULL WHERE status='error'")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class Crawler:
    def __init__(self, args: argparse.Namespace, db: Database) -> None:
        self.args = args
        self.db = db
        self.db_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(args.timeout),
            headers={
                "User-Agent": args.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.7",
                "Cache-Control": "no-cache",
            },
            limits=httpx.Limits(
                max_connections=max(4, args.concurrency + 2),
                max_keepalive_connections=max(2, args.concurrency),
            ),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def sleep(self) -> None:
        await asyncio.sleep(random.uniform(self.args.delay_min, self.args.delay_max))

    async def fetch(self, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.args.retries + 1):
            try:
                response = await self.client.get(url)
                if response.status_code == 429:
                    retry_after = response.headers.get("retry-after")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 2**attempt)
                    logging.warning("HTTP 429 for %s; sleeping %.1fs", url, delay)
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.args.retries:
                    await asyncio.sleep(min(30, 2**attempt + random.random()))
        raise RuntimeError(f"Failed after {self.args.retries} attempts: {url}: {last_error}")

    async def crawl_listings(self) -> None:
        empty_pages = 0
        for page in range(1, self.args.max_list_pages + 1):
            url = LIST_URL.format(page=page)
            response = await self.fetch(url)
            links = parse_listing(response.text)

            if not links:
                empty_pages += 1
                logging.warning("Listing page %d returned no lawyer links", page)
                if empty_pages >= self.args.stop_after_empty_pages:
                    logging.info("Stopping after %d consecutive empty listing pages", empty_pages)
                    break
            else:
                empty_pages = 0
                async with self.db_lock:
                    self.db.add_links(links)
                logging.info("Listing page %d: %d lawyer links", page, len(links))

            await self.sleep()

    async def crawl_profiles(self) -> None:
        rows = self.db.pending(self.args.max_lawyers)
        logging.info("Pending lawyer profiles: %d", len(rows))
        if not rows:
            return

        queue: asyncio.Queue[sqlite3.Row | None] = asyncio.Queue()
        for row in rows:
            queue.put_nowait(row)
        for _ in range(self.args.concurrency):
            queue.put_nowait(None)

        async def worker(worker_id: int) -> None:
            while True:
                row = await queue.get()
                try:
                    if row is None:
                        return

                    profile_url = str(row["profile_url"])
                    try:
                        response = await self.fetch(profile_url)
                        data = parse_profile(
                            response.text,
                            requested_url=profile_url,
                            final_url=str(response.url),
                            listing_name=str(row["listing_name"] or ""),
                        )
                        if not data["name"]:
                            raise ValueError("Could not extract lawyer name")

                        async with self.db_lock:
                            self.db.save(data)
                        logging.info("Worker %d: %s", worker_id, data["name"])
                    except Exception as exc:  # noqa: BLE001
                        logging.exception("Profile failed: %s", profile_url)
                        async with self.db_lock:
                            self.db.mark_error(profile_url, str(exc))
                    await self.sleep()
                finally:
                    queue.task_done()

        tasks = [asyncio.create_task(worker(i + 1)) for i in range(self.args.concurrency)]
        await queue.join()
        await asyncio.gather(*tasks)


def export_data(
    db: Database,
    output_dir: Path,
    include_pending: bool = False,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    where = "" if include_pending else "WHERE status = 'done'"
    rows = list(
        db.conn.execute(
            f"SELECT * FROM lawyers {where} "
            "ORDER BY CAST(lawyer_id AS INTEGER), profile_url"
        )
    )

    fields = [
        "lawyer_id",
        "name",
        "profile_url",
        "slug_url",
        "city",
        "specialties",
        "email",
        "address",
        "status",
        "error",
    ]

    with (output_dir / "lawyers.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            item = dict(row)
            try:
                specialties = json.loads(item.get("specialties_json") or "[]")
            except json.JSONDecodeError:
                specialties = []
            item["specialties"] = " | ".join(specialties)
            writer.writerow({field: item.get(field, "") for field in fields})

    with (output_dir / "lawyers.jsonl").open("w", encoding="utf-8") as file:
        for row in rows:
            item = dict(row)
            try:
                item["specialties"] = json.loads(item.pop("specialties_json") or "[]")
            except json.JSONDecodeError:
                item["specialties"] = []
            file.write(json.dumps(item, ensure_ascii=False) + "\n")

    logging.info("Exported %d lawyer rows to %s", len(rows), output_dir.resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="dadrah_lawyers.sqlite3")
    parser.add_argument("--output-dir", default="output_lawyers")
    parser.add_argument("--max-list-pages", type=int, default=214)
    parser.add_argument("--stop-after-empty-pages", type=int, default=2)
    parser.add_argument("--max-lawyers", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--delay-min", type=float, default=1.5)
    parser.add_argument("--delay-max", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--reset-errors", action="store_true")
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="Also export pending/error discovery rows. By default only completed lawyers are exported.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    if args.delay_min < 0 or args.delay_max < args.delay_min:
        raise ValueError("Invalid delay range")

    db = Database(Path(args.db))
    if args.reset_errors:
        db.reset_errors()

    crawler = Crawler(args, db)
    try:
        await crawler.crawl_listings()
        await crawler.crawl_profiles()
        export_data(
            db,
            Path(args.output_dir),
            include_pending=args.include_pending,
        )
    finally:
        await crawler.close()
        db.close()
    return 0


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logging.warning("Interrupted. Run the same command again to resume.")
        return 130
    except Exception as exc:  # noqa: BLE001
        logging.exception("Crawler stopped: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
