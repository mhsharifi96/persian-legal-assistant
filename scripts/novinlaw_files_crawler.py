#!/usr/bin/env python3
"""Authenticated, resumable crawler for NovinLaw legal files.

Crawls:
  /rules/files/.../lists
  /rules/files/.../childs/{category_id}[?page=N]
  /rules/files/.../show/{file_id}[/{slug}]

Primary JSONL output format:
  {"type": "نمونه دادخواست", "title": "...", "file_url": "...", "type_file": "word"}

Authentication is supplied by the account owner through --cookie-file or
--cookie-env. The crawler does not bypass login, subscription, CAPTCHA,
robots.txt, or access controls.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import mimetypes
import os
import random
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag

DEFAULT_START_URL = (
    "https://www.novinlaw.ir/rules/files/"
    "%D9%81%D8%A7%DB%8C%D9%84-%D8%AD%D9%82%D9%88%D9%82%DB%8C/lists"
)
DEFAULT_USER_AGENT = (
    "NovinLawLegalFilesResearchCrawler/1.0 "
    "(+contact: replace-with-your-email@example.com)"
)

PERSIAN_TO_ASCII = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)
ARABIC_NORMALIZATION = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
    "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا",
})

SHOW_RE = re.compile(r"/show/(?P<id>\d+)(?:/|$)")
CHILDS_RE = re.compile(r"/childs/(?P<id>\d+)(?:/|$)")
LISTS_RE = re.compile(r"/lists(?:/|$)")
FILE_EXT_RE = re.compile(
    r"\.(pdf|docx?|xlsx?|pptx?|rtf|odt|ods|odp|txt|csv|zip|rar|7z|"
    r"mp3|wav|m4a|ogg|mp4|mkv|avi|jpg|jpeg|png|gif|webp)(?:$|[?#])",
    re.IGNORECASE,
)

PAYWALL_MARKERS = {
    "خرید اشتراک", "خرید‌اشتراک", "اشتراک سه ماهه", "اشتراک شش ماهه",
    "اشتراک یک ساله", "تومان/ماه", "ماهیانه",
}
LOGIN_MARKERS = {
    "ورود به حساب کاربری", "شماره موبایل", "رمز عبور", "کد تایید",
}
DOWNLOAD_TEXT_MARKERS = {"دانلود", "دریافت", "download"}

EXTENSION_TYPE_MAP = {
    "pdf": "pdf",
    "doc": "word", "docx": "word", "rtf": "word", "odt": "word",
    "xls": "excel", "xlsx": "excel", "ods": "excel", "csv": "csv",
    "ppt": "powerpoint", "pptx": "powerpoint", "odp": "powerpoint",
    "txt": "text",
    "zip": "archive", "rar": "archive", "7z": "archive",
    "mp3": "audio", "wav": "audio", "m4a": "audio", "ogg": "audio",
    "mp4": "video", "mkv": "video", "avi": "video",
    "jpg": "image", "jpeg": "image", "png": "image",
    "gif": "image", "webp": "image",
}

MIME_TYPE_MAP = {
    "application/pdf": "pdf",
    "application/msword": "word",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
    "application/rtf": "word",
    "application/vnd.oasis.opendocument.text": "word",
    "application/vnd.ms-excel": "excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.ms-powerpoint": "powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "powerpoint",
    "application/zip": "archive",
    "application/x-rar-compressed": "archive",
    "application/x-7z-compressed": "archive",
    "text/plain": "text",
    "text/csv": "csv",
    "audio/mpeg": "audio",
    "audio/wav": "audio",
    "video/mp4": "video",
    "image/jpeg": "image",
    "image/png": "image",
}


@dataclass(frozen=True)
class Route:
    kind: str
    numeric_id: Optional[str]
    canonical_url: str


@dataclass
class LegalFile:
    id: str
    page_id: str
    type: str
    title: str
    file_url: str
    type_file: str
    detail_url: str
    canonical_url: str
    mime_type: Optional[str]
    extension: Optional[str]
    access_status: str
    authenticated_fetch: bool
    http_status: int
    content_hash: str
    fetched_at: str
    local_path: Optional[str] = None
    error: Optional[str] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_fa(value: str) -> str:
    value = (value or "").translate(PERSIAN_TO_ASCII).translate(ARABIC_NORMALIZATION)
    value = value.replace("\u200c", " ").replace("\u200f", " ").replace("\ufeff", " ")
    return normalize_space(value).lower()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_filename(value: str, max_len: int = 120) -> str:
    value = normalize_space(value)
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value)
    value = value.strip(" ._") or "file"
    return value[:max_len].rstrip(" ._")


def parse_cookie_header(raw: str) -> dict[str, str]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    if "\r" in raw or "\n" in raw:
        raise ValueError("Cookie input must be a single header line")
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError("Invalid cookie segment in cookie input")
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("Cookie name cannot be empty")
        cookies[name] = value.strip()
    return cookies


def load_auth_cookies(cookie_file: Optional[Path], cookie_env: str) -> dict[str, str]:
    raw = ""
    if cookie_file is not None:
        if not cookie_file.exists():
            raise FileNotFoundError(f"Cookie file not found: {cookie_file}")
        raw = cookie_file.read_text(encoding="utf-8").strip()
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Cookie JSON must be an object")
            return {str(k): str(v) for k, v in parsed.items() if str(k).strip()}
    elif cookie_env:
        raw = os.environ.get(cookie_env, "").strip()
    return parse_cookie_header(raw)


def build_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parts.path)
    # Slug and non-slug detail URLs represent the same record.
    path = re.sub(r"(/show/\d+)(?:/.*)?$", r"\1", path)
    path = path.rstrip("/") or "/"

    query_pairs = parse_qsl(parts.query, keep_blank_values=False)
    # Only pagination changes page identity for category/list pages.
    query_pairs = [(k, v) for k, v in query_pairs if k == "page" and v.isdigit()]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def parse_route(url: str, allowed_host: str) -> Optional[Route]:
    canonical = canonicalize_url(url)
    parts = urlsplit(canonical)
    if parts.netloc.lower() != allowed_host.lower():
        return None
    decoded = unquote(parts.path)
    if "/rules/files/" not in decoded:
        return None
    match = SHOW_RE.search(decoded)
    if match:
        return Route("detail", match.group("id"), canonical)
    match = CHILDS_RE.search(decoded)
    if match:
        return Route("category", match.group("id"), canonical)
    if LISTS_RE.search(decoded):
        return Route("index", None, canonical)
    return None


def infer_extension(url: str, content_disposition: str = "") -> Optional[str]:
    for candidate in (content_disposition, unquote(urlsplit(url).path)):
        match = FILE_EXT_RE.search(candidate or "")
        if match:
            return match.group(1).lower()
    guessed = mimetypes.guess_extension("")
    return guessed.lstrip(".") if guessed else None


def infer_type_file(url: str, mime_type: Optional[str] = None, content_disposition: str = "") -> tuple[str, Optional[str]]:
    ext = infer_extension(url, content_disposition)
    if ext in EXTENSION_TYPE_MAP:
        return EXTENSION_TYPE_MAP[ext], ext
    clean_mime = (mime_type or "").split(";", 1)[0].strip().lower()
    if clean_mime in MIME_TYPE_MAP:
        mapped = MIME_TYPE_MAP[clean_mime]
        guessed_ext = mimetypes.guess_extension(clean_mime)
        return mapped, ext or (guessed_ext.lstrip(".") if guessed_ext else None)
    if clean_mime.startswith("audio/"):
        return "audio", ext
    if clean_mime.startswith("video/"):
        return "video", ext
    if clean_mime.startswith("image/"):
        return "image", ext
    return "unknown", ext


def page_text(soup: BeautifulSoup) -> str:
    return normalize_space(soup.get_text(" ", strip=True))


def detect_access_status(soup: BeautifulSoup, has_file_url: bool, authenticated: bool) -> str:
    normalized = normalize_fa(page_text(soup))
    if any(normalize_fa(marker) in normalized for marker in LOGIN_MARKERS):
        return "unauthorized"
    if any(normalize_fa(marker) in normalized for marker in PAYWALL_MARKERS) and not has_file_url:
        return "paywalled"
    if has_file_url:
        return "subscribed" if authenticated else "public"
    return "missing_file"


def extract_title(soup: BeautifulSoup) -> str:
    for selector in ("h1", "main h2", "article h2", "title"):
        node = soup.select_one(selector)
        if node:
            text = normalize_space(node.get_text(" ", strip=True))
            text = re.sub(r"^.*?\s+-\s+", "", text) if selector == "title" else text
            if text:
                return text
    return ""


def extract_category_type(soup: BeautifulSoup, detail_url: str) -> str:
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(detail_url, anchor.get("href", ""))
        if CHILDS_RE.search(unquote(urlsplit(href).path)):
            text = normalize_space(anchor.get_text(" ", strip=True))
            if text:
                candidates.append(text)
    if candidates:
        return candidates[-1]

    # Breadcrumb fallback: find text between "فایل حقوقی" and the title.
    title = extract_title(soup)
    for selector in ("nav", ".breadcrumb", "ol.breadcrumb", "ul.breadcrumb"):
        node = soup.select_one(selector)
        if not node:
            continue
        parts = [normalize_space(x.get_text(" ", strip=True)) for x in node.find_all(["a", "li", "span"])]
        parts = [x for x in parts if x and x not in {title, "صفحه اصلی", "صفحه‌اصلی", "فایل حقوقی"}]
        if parts:
            return parts[-1]
    return "نامشخص"


def is_probable_download(anchor: Tag, absolute_url: str) -> bool:
    text = normalize_fa(anchor.get_text(" ", strip=True))
    if any(marker in text for marker in DOWNLOAD_TEXT_MARKERS):
        return True
    if anchor.has_attr("download"):
        return True
    if FILE_EXT_RE.search(unquote(absolute_url)):
        return True
    return False


def extract_file_url(soup: BeautifulSoup, detail_url: str, allowed_host: str) -> str:
    candidates: list[tuple[int, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = normalize_space(anchor.get("href", ""))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(detail_url, href)
        if not is_probable_download(anchor, absolute):
            continue
        score = 0
        text = normalize_fa(anchor.get_text(" ", strip=True))
        if "دانلود" in text or "download" in text:
            score += 10
        if anchor.has_attr("download"):
            score += 6
        if FILE_EXT_RE.search(unquote(absolute)):
            score += 5
        if urlsplit(absolute).netloc.lower() != allowed_host.lower():
            score += 2
        if "/show/" in unquote(urlsplit(absolute).path):
            score -= 10
        candidates.append((score, absolute))

    # Embedded audio/video/document URLs.
    for tag_name, attr in (("source", "src"), ("audio", "src"), ("video", "src"), ("iframe", "src"), ("embed", "src")):
        for node in soup.find_all(tag_name):
            raw = normalize_space(node.get(attr, ""))
            if raw:
                absolute = urljoin(detail_url, raw)
                score = 7 if FILE_EXT_RE.search(unquote(absolute)) else 3
                candidates.append((score, absolute))

    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def extract_internal_links(soup: BeautifulSoup, current_url: str, allowed_host: str) -> set[str]:
    links: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = normalize_space(anchor.get("href", ""))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(current_url, href)
        route = parse_route(absolute, allowed_host)
        if route is not None:
            links.add(route.canonical_url)
    return links


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS legal_files (
                id TEXT PRIMARY KEY,
                page_id TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                file_url TEXT NOT NULL DEFAULT '',
                type_file TEXT NOT NULL DEFAULT 'unknown',
                detail_url TEXT NOT NULL,
                canonical_url TEXT NOT NULL UNIQUE,
                mime_type TEXT,
                extension TEXT,
                access_status TEXT NOT NULL,
                authenticated_fetch INTEGER NOT NULL DEFAULT 0,
                http_status INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                local_path TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS crawl_pages (
                url TEXT PRIMARY KEY,
                route_kind TEXT NOT NULL,
                status TEXT NOT NULL,
                http_status INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                content_hash TEXT,
                fetched_at TEXT,
                authenticated_fetch INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_legal_files_type ON legal_files(type);
            CREATE INDEX IF NOT EXISTS idx_legal_files_access ON legal_files(access_status);
            """
        )
        self.conn.commit()

    def upsert_page(self, url: str, route_kind: str, status: str, http_status: int,
                    error: Optional[str], content_hash: Optional[str], authenticated: bool) -> None:
        self.conn.execute(
            """
            INSERT INTO crawl_pages(
                url, route_kind, status, http_status, attempt_count, last_error,
                content_hash, fetched_at, authenticated_fetch
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                route_kind=excluded.route_kind,
                status=excluded.status,
                http_status=excluded.http_status,
                attempt_count=crawl_pages.attempt_count + 1,
                last_error=excluded.last_error,
                content_hash=excluded.content_hash,
                fetched_at=excluded.fetched_at,
                authenticated_fetch=excluded.authenticated_fetch
            """,
            (url, route_kind, status, http_status, error, content_hash, now_iso(), int(authenticated)),
        )
        self.conn.commit()

    def upsert_file(self, item: LegalFile) -> None:
        data = asdict(item)
        data["authenticated_fetch"] = int(item.authenticated_fetch)
        columns = list(data)
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{c}=excluded.{c}" for c in columns if c != "id")
        self.conn.execute(
            f"INSERT INTO legal_files({','.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [data[c] for c in columns],
        )
        self.conn.commit()

    def all_files(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM legal_files ORDER BY CAST(page_id AS INTEGER), title"))

    def close(self) -> None:
        self.conn.close()


class Crawler:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.output = args.output
        self.output.mkdir(parents=True, exist_ok=True)
        self.cookies = load_auth_cookies(args.cookie_file, args.cookie_env)
        self.authenticated = bool(self.cookies)
        self.cookie_header = build_cookie_header(self.cookies)
        self.cache_dir = self.output / ("raw_html_authenticated" if self.authenticated else "raw_html")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir = self.output / "downloaded_files"
        if args.download_files:
            self.download_dir.mkdir(parents=True, exist_ok=True)

        start = canonicalize_url(args.start_url)
        self.allowed_host = urlsplit(start).netloc
        self.store = Store(self.output / "novinlaw_files.sqlite3")
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(args.timeout),
            headers={
                "User-Agent": args.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
            },
            limits=httpx.Limits(max_connections=max(2, args.concurrency + 1), max_keepalive_connections=args.concurrency),
        )
        self.robots = RobotFileParser()
        self.robots_ready = False
        self.seen: set[str] = set()
        self.enqueued: set[str] = set()
        self.count = 0
        self.stats = {
            "pages_processed": 0,
            "details": 0,
            "with_file_url": 0,
            "public": 0,
            "subscribed": 0,
            "paywalled": 0,
            "unauthorized": 0,
            "missing_file": 0,
            "downloaded": 0,
            "failed": 0,
        }

    async def close(self) -> None:
        await self.client.aclose()
        self.store.close()

    def cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.html"

    def headers_for(self, url: str) -> dict[str, str]:
        # Never send NovinLaw session cookies to third-party file hosts.
        if self.authenticated and urlsplit(url).netloc.lower() == self.allowed_host.lower():
            return {"Cookie": self.cookie_header}
        return {}

    async def load_robots(self) -> None:
        robots_url = f"{urlsplit(self.args.start_url).scheme}://{self.allowed_host}/robots.txt"
        try:
            response = await self.client.get(robots_url)
            if response.status_code == 200:
                self.robots.set_url(robots_url)
                self.robots.parse(response.text.splitlines())
                self.robots_ready = True
                logging.info("Loaded robots.txt from %s", robots_url)
            else:
                logging.warning("robots.txt returned HTTP %s", response.status_code)
        except Exception as exc:
            logging.warning("Could not load robots.txt: %s", exc)

    def allowed_by_robots(self, url: str) -> bool:
        if self.args.ignore_robots or not self.robots_ready:
            return True
        return self.robots.can_fetch(self.args.user_agent, url)

    async def polite_sleep(self) -> None:
        jitter = random.uniform(0.90, 1.25)
        await asyncio.sleep(max(0.0, self.args.delay * jitter))

    async def fetch_html(self, url: str) -> tuple[str, int, str]:
        cache = self.cache_path(url)
        if cache.exists() and not self.args.refresh:
            return cache.read_text(encoding="utf-8"), 200, url
        if not self.allowed_by_robots(url):
            raise PermissionError(f"Blocked by robots.txt: {url}")

        last_error: Optional[Exception] = None
        for attempt in range(self.args.retries + 1):
            if attempt or self.count:
                await self.polite_sleep()
            try:
                response = await self.client.get(url, headers=self.headers_for(url))
                if response.status_code in {429, 500, 502, 503, 504}:
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after and retry_after.isdigit() else min(60.0, 2 ** attempt)
                    logging.warning("HTTP %s for %s; retrying", response.status_code, url)
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                html = response.text
                cache.write_text(html, encoding="utf-8")
                return html, response.status_code, str(response.url)
            except Exception as exc:
                last_error = exc
                if attempt >= self.args.retries:
                    break
                await asyncio.sleep(min(60.0, 2 ** attempt))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}")

    async def inspect_file_url(self, file_url: str) -> tuple[Optional[str], str, Optional[str]]:
        type_file, ext = infer_type_file(file_url)
        if not self.args.verify_file_urls and not self.args.download_files:
            return None, type_file, ext
        try:
            file_headers = {"User-Agent": self.args.user_agent, **self.headers_for(file_url)}
            response = await self.client.head(
                file_url,
                headers=file_headers,
                follow_redirects=True,
            )
            if response.status_code in {405, 501}:
                response = await self.client.get(
                    file_url,
                    headers={"User-Agent": self.args.user_agent, "Range": "bytes=0-0", **self.headers_for(file_url)},
                    follow_redirects=True,
                )
            mime = response.headers.get("Content-Type")
            content_disposition = response.headers.get("Content-Disposition", "")
            detected_type, detected_ext = infer_type_file(str(response.url), mime, content_disposition)
            return mime, detected_type if detected_type != "unknown" else type_file, detected_ext or ext
        except Exception as exc:
            logging.warning("Could not inspect file URL %s: %s", file_url, exc)
            return None, type_file, ext

    async def download_file(self, item: LegalFile) -> Optional[str]:
        if not self.args.download_files or not item.file_url:
            return None
        category_dir = self.download_dir / safe_filename(item.type)
        category_dir.mkdir(parents=True, exist_ok=True)
        suffix = f".{item.extension}" if item.extension else ""
        target = category_dir / f"{item.page_id}_{safe_filename(item.title)}{suffix}"
        if target.exists() and target.stat().st_size > 0 and not self.args.refresh:
            return str(target.relative_to(self.output))
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            async with self.client.stream(
                "GET",
                item.file_url,
                headers={"User-Agent": self.args.user_agent, **self.headers_for(item.file_url)},
                follow_redirects=True,
            ) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    async for chunk in response.aiter_bytes():
                        handle.write(chunk)
            tmp.replace(target)
            self.stats["downloaded"] += 1
            return str(target.relative_to(self.output))
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            logging.warning("Download failed for %s: %s", item.file_url, exc)
            return None

    async def process_detail(self, route: Route, requested_url: str, html: str, status: int, final_url: str) -> None:
        soup = BeautifulSoup(html, "lxml")
        title = extract_title(soup) or f"file-{route.numeric_id}"
        category_type = extract_category_type(soup, final_url)
        file_url = extract_file_url(soup, final_url, self.allowed_host)
        access_status = detect_access_status(soup, bool(file_url), self.authenticated)
        mime_type: Optional[str] = None
        type_file, extension = infer_type_file(file_url) if file_url else ("unknown", None)
        if file_url:
            mime_type, type_file, extension = await self.inspect_file_url(file_url)

        item = LegalFile(
            id=f"legal_file:{route.numeric_id}",
            page_id=str(route.numeric_id),
            type=category_type,
            title=title,
            file_url=file_url,
            type_file=type_file,
            detail_url=final_url,
            canonical_url=route.canonical_url,
            mime_type=mime_type,
            extension=extension,
            access_status=access_status,
            authenticated_fetch=self.authenticated,
            http_status=status,
            content_hash=sha256_text(html),
            fetched_at=now_iso(),
        )
        item.local_path = await self.download_file(item)
        self.store.upsert_file(item)

        self.stats["details"] += 1
        self.stats[access_status] = self.stats.get(access_status, 0) + 1
        if file_url:
            self.stats["with_file_url"] += 1
        logging.info(
            "%s | %s | type=%s | file=%s | access=%s",
            item.id, item.title, item.type, item.type_file, item.access_status,
        )

    async def process_url(self, url: str, queue: asyncio.Queue[str]) -> None:
        route = parse_route(url, self.allowed_host)
        if route is None:
            return
        try:
            html, status, final_url = await self.fetch_html(url)
            content_hash = sha256_text(html)
            soup = BeautifulSoup(html, "lxml")
            links = extract_internal_links(soup, final_url, self.allowed_host)
            for link in sorted(links):
                if link not in self.enqueued and link not in self.seen:
                    self.enqueued.add(link)
                    await queue.put(link)
            if route.kind == "detail":
                await self.process_detail(route, url, html, status, final_url)
            self.store.upsert_page(route.canonical_url, route.kind, "ok", status, None, content_hash, self.authenticated)
            self.stats["pages_processed"] += 1
        except Exception as exc:
            self.stats["failed"] += 1
            self.store.upsert_page(route.canonical_url, route.kind, "failed", 0, str(exc), None, self.authenticated)
            logging.error("%s", exc)

    async def worker(self, queue: asyncio.Queue[str]) -> None:
        while True:
            url = await queue.get()
            try:
                if url in self.seen:
                    continue
                if self.args.max_pages is not None and self.count >= self.args.max_pages:
                    continue
                self.seen.add(url)
                self.count += 1
                await self.process_url(url, queue)
            finally:
                queue.task_done()

    async def run(self) -> None:
        if self.authenticated:
            logging.info(
                "Authenticated session enabled (%d cookies); using cache directory %s",
                len(self.cookies), self.cache_dir,
            )
        else:
            logging.info("No authentication cookies supplied; using public access")
        await self.load_robots()

        queue: asyncio.Queue[str] = asyncio.Queue()
        start = canonicalize_url(self.args.start_url)
        self.enqueued.add(start)
        await queue.put(start)
        workers = [asyncio.create_task(self.worker(queue)) for _ in range(self.args.concurrency)]
        await queue.join()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        self.export_outputs()
        logging.info("Finished: %s", json.dumps(self.stats, ensure_ascii=False))

    def export_outputs(self) -> None:
        rows = self.store.all_files()
        primary_fields = ["type", "title", "file_url", "type_file"]

        with (self.output / "files.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = {field: row[field] for field in primary_fields}
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        with (self.output / "files.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=primary_fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row[field] for field in primary_fields})

        with (self.output / "files_metadata.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = dict(row)
                payload["authenticated_fetch"] = bool(payload["authenticated_fetch"])
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

        (self.output / "stats.json").write_text(
            json.dumps(self.stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl NovinLaw legal-file records and download URLs")
    parser.add_argument("--start-url", default=DEFAULT_START_URL)
    parser.add_argument("--output", type=Path, default=Path("novinlaw_files_output"))
    parser.add_argument("--cookie-file", type=Path, help="Local Cookie header file; never logged")
    parser.add_argument("--cookie-env", default="NOVINLAW_COOKIE", help="Environment variable containing Cookie header")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--refresh", action="store_true", help="Redownload HTML instead of using cache")
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--verify-file-urls", action="store_true", help="HEAD/inspect direct file URLs")
    parser.add_argument("--download-files", action="store_true", help="Download the files in addition to metadata")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    crawler = Crawler(args)
    try:
        await crawler.run()
        return 0
    finally:
        await crawler.close()


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
        logging.warning("Interrupted")
        return 130
    except Exception as exc:
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
