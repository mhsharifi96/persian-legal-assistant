#!/usr/bin/env python3
"""Polite, resumable graph crawler for NovinLaw unanimity decisions.

Crawls:
- list/index page: /rules/unanimity/.../lists
- year pages:       /rules/unanimity/.../childs/{id}
- decision pages:   /rules/unanimity/.../show/{id}

The crawler supports an authenticated NovinLaw session supplied by the account
owner through a local cookie file or environment variable. It does not bypass
login, subscription, CAPTCHA, robots.txt, or rate limits. Pages unavailable to
the supplied account are retained with access_status='paywalled'.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, Tag
from rapidfuzz import fuzz, process

DEFAULT_START_URL = (
    "https://www.novinlaw.ir/rules/unanimity/"
    "%D8%A2%D8%B1%D8%A7-%D9%88%D8%AD%D8%AF%D8%AA-%D8%B1%D9%88%DB%8C%D9%87/lists"
)
DEFAULT_USER_AGENT = (
    "NovinLawUnanimityResearchCrawler/1.0 "
    "(+contact: replace-with-your-email@example.com)"
)

PERSIAN_TO_ASCII = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
)
ARABIC_NORMALIZATION = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
    "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا",
})

ROUTE_PATTERNS = [
    ("year", "childs", re.compile(r"/childs/(?P<id>\d+)(?:/|$)")),
    ("decision", "show", re.compile(r"/show/(?P<id>\d+)(?:/|$)")),
    ("index", "lists", re.compile(r"/lists(?:/|$)")),
]

YEAR_RE = re.compile(r"(?:سال\s*)?(?P<year>1[234]\d{2})")
DECISION_NUMBER_RE = re.compile(
    r"ر[أا]ی\s+وحدت\s*رویه(?:\s+قضایی)?\s*(?:شماره|ردیف)?\s*"
    r"(?P<number>[\(\)رR۰-۹٠-٩0-9/\-–،,\sو]+)",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"تاریخ\s*(?:تصویب|صدور)?\s*[:：]?\s*"
    r"(?P<date>[۰-۹٠-٩0-9]{2,4}\s*/\s*[۰-۹٠-٩0-9]{1,2}\s*/\s*[۰-۹٠-٩0-9]{1,2})"
)
SUBJECT_RE = re.compile(r"موضوع\s*[:：]\s*(?P<subject>.+)")

LEGAL_REF_RE = re.compile(
    r"(?P<kind>ماده|مواد|اصل|اصول|تبصره|بند)\s*"
    r"[\(\[«]?[\s]*"
    r"(?P<numbers>(?:[۰-۹٠-٩0-9]+(?:\s*مکرر)?|"
    r"یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده)"
    r"(?:\s*(?:،|,|و|تا|الی|\-|–)\s*"
    r"(?:[۰-۹٠-٩0-9]+(?:\s*مکرر)?|یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده))*)"
    r"[\)\]»]?"
    r"(?:\s+(?:از\s+)?(?P<target>"
    r"(?:قانون|آیین\s*نامه|اساسنامه|دستورالعمل|بخشنامه|تصویب\s*نامه|"
    r"لایحه\s+قانونی|مقررات|نظامنامه)"
    r"[^\n\.؛]{2,220}))?"
    r"(?=$|[،؛\.\n])"
)

STANDALONE_LAW_RE = re.compile(
    r"(?P<target>(?:قانون|آیین\s*نامه|اساسنامه|دستورالعمل|بخشنامه|"
    r"تصویب\s*نامه|لایحه\s+قانونی|نظامنامه)"
    r"[^\n\.؛]{3,180})(?=$|[،؛\.\n])"
)
DECISION_CITATION_RE = re.compile(
    r"ر[أا]ی\s+وحدت\s*رویه(?:\s+قضایی)?\s*"
    r"(?:شماره(?:های)?|ردیف)?\s*"
    r"(?P<numbers>[\(\)رR۰-۹٠-٩0-9/\-–،,\sو]{1,80})"
    r"(?=$|[،؛\.\n])",
    re.IGNORECASE,
)

KNOWN_INSTITUTIONS = [
    "هیأت عمومی دیوان عالی کشور",
    "هیات عمومی دیوان عالی کشور",
    "هیأت عمومی دیوان عدالت اداری",
    "هیات عمومی دیوان عدالت اداری",
    "هیأت عمومی دیوان عالی انتظامی قضات",
    "هیات عمومی دیوان عالی انتظامی قضات",
    "شورای عالی ثبت",
]

COMMON_NOISE = {
    "قانون درجیب شما", "قانون‌درجیب‌شما", "صفحه اصلی", "صفحه‌اصلی",
    "قوانین کاربردی", "قوانین‌کاربردی", "درباره ما", "درباره‌ما",
    "دریافت اپلیکیشن", "شبکه های اجتماعی", "شبکه‌های اجتماعی", "ورود",
    "خرید اشتراک", "خرید‌اشتراک",
}
PAYWALL_MARKERS = {
    "اشتراک سه ماهه", "اشتراک شش ماهه", "اشتراک یک ساله", "خرید اشتراک",
    "خرید‌اشتراک", "تومان/ماه", "ماهیانه",
}


PERSIAN_NUMBER_WORDS = {
    "یک": "1", "دو": "2", "سه": "3", "چهار": "4", "پنج": "5",
    "شش": "6", "هفت": "7", "هشت": "8", "نه": "9", "ده": "10",
}


@dataclass(frozen=True)
class Route:
    node_type: str
    subtype: str
    numeric_id: Optional[str]
    node_id: str
    canonical_url: str


@dataclass
class Node:
    id: str
    type: str
    subtype: str
    numeric_id: Optional[str]
    title: str
    url: str = ""
    year: Optional[str] = None
    decision_number: Optional[str] = None
    approval_date: Optional[str] = None
    subject: Optional[str] = None
    issuing_body: Optional[str] = None
    text: Optional[str] = None
    access_status: Optional[str] = None
    content_hash: Optional[str] = None
    fetched_at: Optional[str] = None
    metadata_json: Optional[str] = None


@dataclass(frozen=True)
class Relation:
    source_id: str
    target_id: str
    relation_type: str
    raw_reference: Optional[str] = None
    confidence: float = 1.0
    source_url: Optional[str] = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_digits(value: str) -> str:
    return (value or "").translate(PERSIAN_TO_ASCII)


def normalize_fa(value: str) -> str:
    value = normalize_digits(value or "").translate(ARABIC_NORMALIZATION)
    value = value.replace("\u200c", " ").replace("\u200f", " ").replace("\ufeff", " ")
    value = re.sub(r"[\[\]«»\"'`]+", " ", value)
    return normalize_space(value).lower()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_cookie_header(raw: str) -> dict[str, str]:
    """Parse a browser/curl Cookie header without logging secret values."""
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
            raise ValueError(f"Invalid cookie segment: {part!r}")
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError("Cookie name cannot be empty")
        cookies[name] = value
    return cookies


def load_auth_cookies(cookie_file: Optional[Path], cookie_env: str) -> dict[str, str]:
    """Load auth cookies from a local file or environment variable.

    The file may contain either a raw Cookie header value or a JSON object such
    as {"XSRF-TOKEN": "...", "novinlaw_session": "..."}. Cookie values are
    intentionally never printed.
    """
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


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parts.path)
    path = re.sub(r"(/childs/\d+)(?:/.*)?$", r"\1", path)
    path = re.sub(r"(/show/\d+)(?:/.*)?$", r"\1", path)
    path = path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def parse_route(url: str, allowed_host: str) -> Optional[Route]:
    canonical = canonicalize_url(url)
    parts = urlsplit(canonical)
    if parts.netloc.lower() != allowed_host.lower():
        return None
    decoded_path = unquote(parts.path)
    if "/rules/unanimity/" not in decoded_path:
        return None

    for node_type, subtype, pattern in ROUTE_PATTERNS:
        match = pattern.search(decoded_path)
        if not match:
            continue
        numeric_id = match.groupdict().get("id")
        if node_type == "index":
            node_id = "unanimity:index"
        elif node_type == "year":
            node_id = f"unanimity_year:{numeric_id}"
        else:
            node_id = f"unanimity_decision:{numeric_id}"
        return Route(node_type, subtype, numeric_id, node_id, canonical)
    return None


def safe_filename(node_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", node_id) + ".html"


def soup_text(tag: Optional[Tag]) -> str:
    return normalize_space(tag.get_text(" ", strip=True)) if tag else ""


def breadcrumb_container(soup: BeautifulSoup) -> Optional[Tag]:
    for selector in (
        ".breadcrumb", ".breadcrumbs", ".bread-crumb",
        "nav[aria-label*=breadcrumb]", "ol.breadcrumb", "ul.breadcrumb",
    ):
        found = soup.select_one(selector)
        if found:
            return found
    return None


def breadcrumb_items(soup: BeautifulSoup) -> list[str]:
    crumb = breadcrumb_container(soup)
    if not crumb:
        return []
    items = [soup_text(tag) for tag in crumb.find_all(["a", "li", "span"])]
    return [item for item in items if item]


def clean_page_title(value: str) -> str:
    value = normalize_space(value)
    value = re.sub(r"\s*[-|]\s*قانون.?درجیب.?شما.*$", "", value, flags=re.I)
    pieces = [p.strip() for p in re.split(r"\s[-–|]\s", value) if p.strip()]
    return pieces[-1] if pieces else value


def extract_title(soup: BeautifulSoup, route: Route) -> str:
    h1 = soup.find("h1")
    if h1 and soup_text(h1):
        return soup_text(h1)

    crumb = breadcrumb_container(soup)
    if crumb:
        candidates = [soup_text(x) for x in crumb.find_all(["li", "span"])]
        candidates = [x for x in candidates if x and x not in COMMON_NOISE]
        if candidates:
            return candidates[-1]
        text = soup_text(crumb)
        if text:
            return text.split("آراء وحدت رویه")[-1].strip() or text

    if soup.title and soup.title.string:
        return clean_page_title(soup.title.string)
    return route.node_id


def choose_content_container(soup: BeautifulSoup) -> Tag:
    preferred = soup.select_one(
        "article, main, .article-content, .post-content, .single-content, "
        ".entry-content, .content-detail, .rule-content, .legal-content"
    )
    if preferred and len(soup_text(preferred)) > 80:
        return preferred

    h1 = soup.find("h1")
    if h1:
        parent = h1.parent
        candidates: list[Tag] = []
        while isinstance(parent, Tag) and parent.name != "body":
            candidates.append(parent)
            parent = parent.parent
        for candidate in candidates:
            if len(soup_text(candidate)) >= 200:
                return candidate
    return soup.body or soup


def extract_clean_lines(soup: BeautifulSoup) -> list[str]:
    container = choose_content_container(soup)
    fragment = BeautifulSoup(str(container), "lxml")
    for tag in fragment.select(
        "script, style, noscript, svg, header, footer, nav, aside, form, button, "
        ".breadcrumb, .breadcrumbs, .bread-crumb, .share, .social, .comments"
    ):
        tag.decompose()
    h1 = fragment.find("h1")
    if h1:
        h1.decompose()

    lines: list[str] = []
    for raw in fragment.get_text("\n", strip=True).splitlines():
        line = normalize_space(raw)
        if not line or line in COMMON_NOISE:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return lines


def detect_paywall(lines: Iterable[str]) -> bool:
    # Normalize Persian/Arabic variants and ZWNJ so markers such as
    # "خرید اشتراک" and "خرید‌اشتراک" are treated identically.
    joined = normalize_fa("\n".join(lines))
    normalized_markers = {normalize_fa(marker) for marker in PAYWALL_MARKERS}
    marker_count = sum(marker in joined for marker in normalized_markers)
    has_legal_content = bool(
        DATE_RE.search(joined)
        or re.search(r"موضوع\s*[:：]", joined)
    )
    return marker_count >= 2 and not has_legal_content


def extract_full_page_lines(soup: BeautifulSoup) -> list[str]:
    """Return visible-ish text from the whole HTML for access-gate detection.

    The site's subscription panel can be a sibling of the article container.
    Looking only inside ``article``/``main`` can therefore miss the gate and
    incorrectly classify a gated decision as ``empty``.
    """
    fragment = BeautifulSoup(str(soup), "lxml")
    for tag in fragment.select("script, style, noscript, svg"):
        tag.decompose()

    lines: list[str] = []
    for raw in fragment.get_text("\n", strip=True).splitlines():
        line = normalize_space(raw)
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return lines


def extract_decision_text(soup: BeautifulSoup, title: str) -> tuple[str, str]:
    # Detect access restrictions from the complete page before narrowing the
    # DOM to the legal-content container.
    if detect_paywall(extract_full_page_lines(soup)):
        return "", "paywalled"

    lines = extract_clean_lines(soup)

    filtered: list[str] = []
    for line in lines:
        if line == title:
            continue
        if any(marker in line for marker in PAYWALL_MARKERS):
            continue
        if re.fullmatch(r"[%٪]?\d+(?:,\d+)*(?:\s*تومان(?:/ماه)?)?", normalize_digits(line)):
            continue
        filtered.append(line)

    # Prefer the legal body beginning at the date/subject marker. If the HTML has
    # no marker, retain the cleaned text so older records are not silently lost.
    start = None
    for idx, line in enumerate(filtered):
        if DATE_RE.search(line) or re.search(r"موضوع\s*[:：]", line):
            start = idx
            break
    body = filtered[start:] if start is not None else filtered

    # Remove trailing previous/next navigation when it appears as standalone titles.
    while body and re.fullmatch(
        r"ر[أا]ی\s+وحدت\s*رویه(?:\s+قضایی)?\s*(?:شماره|ردیف)?.{0,80}",
        body[-1], re.IGNORECASE,
    ):
        body.pop()

    text = "\n".join(body).strip()
    return text, ("public" if text else "empty")


def extract_year(value: str) -> Optional[str]:
    match = YEAR_RE.search(normalize_digits(value))
    return match.group("year") if match else None


def clean_decision_number(value: str) -> Optional[str]:
    if not value:
        return None
    value = normalize_digits(value)
    value = normalize_space(value).strip("-–،,؛. ")
    value = re.split(r"\s+(?:مورخ|صادره|هیأت|هیات|موضوع)\b", value, maxsplit=1)[0]
    return value or None


def extract_decision_number(title: str) -> Optional[str]:
    match = DECISION_NUMBER_RE.search(title)
    return clean_decision_number(match.group("number")) if match else None


def extract_approval_date(text: str) -> Optional[str]:
    match = DATE_RE.search(text)
    if not match:
        return None
    return re.sub(r"\s+", "", normalize_digits(match.group("date")))


def extract_subject(text: str) -> Optional[str]:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        match = SUBJECT_RE.search(line)
        if not match:
            continue
        subject = normalize_space(match.group("subject"))
        # When HTML keeps the label alone, use the next nonempty line.
        if not subject and idx + 1 < len(lines):
            subject = normalize_space(lines[idx + 1])
        # Avoid swallowing a whole opinion when the page flattened all content.
        if len(subject) > 700:
            boundary = re.search(
                r"\s+(?=(?:در\s+ماده|نظر\s+به|با\s+توجه|حسب|مطابق\s+ماده|در\s+پرونده))",
                subject[80:],
            )
            if boundary:
                subject = subject[:80 + boundary.start()].strip()
            else:
                subject = subject[:700].rstrip() + "…"
        return subject or None
    return None


def extract_issuing_body(text: str) -> Optional[str]:
    normalized = normalize_fa(text)
    for institution in KNOWN_INSTITUTIONS:
        if normalize_fa(institution) in normalized:
            return institution.replace("هیات", "هیأت")
    match = re.search(
        r"((?:هیأت|هیات)\s+عمومی\s+[^\n\.؛]{3,100}|شورای\s+عالی\s+ثبت)", text
    )
    return normalize_space(match.group(1)) if match else None


def extract_internal_links(soup: BeautifulSoup, page_url: str, allowed_host: str) -> list[Route]:
    routes: dict[str, Route] = {}
    for anchor in soup.find_all("a", href=True):
        route = parse_route(urljoin(page_url, anchor.get("href", "")), allowed_host)
        if route:
            routes[route.node_id] = route
    return list(routes.values())


def extract_breadcrumb_routes(soup: BeautifulSoup, page_url: str, allowed_host: str) -> list[Route]:
    crumb = breadcrumb_container(soup)
    if not crumb:
        return []
    output: list[Route] = []
    for anchor in crumb.find_all("a", href=True):
        route = parse_route(urljoin(page_url, anchor.get("href", "")), allowed_host)
        if route:
            output.append(route)
    return output


def structural_relations(
    source: Route,
    links: Iterable[Route],
    breadcrumbs: Iterable[Route],
) -> list[Relation]:
    result: dict[tuple[str, str, str], Relation] = {}

    def add(src: str, dst: str, kind: str, confidence: float = 1.0) -> None:
        if src == dst:
            return
        result[(src, dst, kind)] = Relation(
            src, dst, kind, confidence=confidence, source_url=source.canonical_url
        )

    links = list(links)
    breadcrumbs = list(breadcrumbs)
    for target in links:
        add(source.node_id, target.node_id, "LINKS_TO", 0.70)

    if source.node_type == "index":
        for target in links:
            if target.node_type == "year":
                add(source.node_id, target.node_id, "CONTAINS", 1.0)
            elif target.node_type == "decision":
                add(source.node_id, target.node_id, "LISTS", 0.95)
    elif source.node_type == "year":
        for target in links:
            if target.node_type == "decision":
                add(source.node_id, target.node_id, "CONTAINS", 1.0)

    chain = [x for x in breadcrumbs if x.node_type in {"year", "decision"}]
    if source.node_type != "index" and (not chain or chain[-1].node_id != source.node_id):
        chain.append(source)
    for parent, child in zip(chain, chain[1:]):
        if parent.node_type == "year" and child.node_type == "decision":
            add(parent.node_id, child.node_id, "CONTAINS", 1.0)

    # Decision pages often expose previous/next decisions. Keep LINKS_TO for all,
    # and add a directional convenience edge when both numbers are simple integers.
    if source.node_type == "decision":
        source_number = None
        for route in [source]:
            source_number = route.numeric_id
        for target in links:
            if target.node_type != "decision":
                continue
            # Database IDs are not vote numbers; direction is finalized later from titles.
            add(source.node_id, target.node_id, "ADJACENT_DECISION", 0.75)

    return list(result.values())


def parse_number_tokens(value: str) -> list[str]:
    value = normalize_digits(value)
    tokens = re.findall(r"(?:\(ر\)|ر)?\s*\d+(?:/\d+)?", value, flags=re.IGNORECASE)
    return [normalize_space(token).replace(" ", "") for token in tokens]


def sentence_context(text: str, start: int, end: int) -> str:
    left_candidates = [text.rfind(ch, 0, start) for ch in ("\n", ".", "؛")]
    left = max(left_candidates) + 1
    right_candidates = [pos for ch in ("\n", ".", "؛") if (pos := text.find(ch, end)) != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right]


def clean_legal_title(value: str) -> str:
    value = normalize_space(value)
    value = re.split(
        r"\s+(?=(?:مصوب|الحاقی|اصلاحی|مورخ|با\s+اصلاحات|با\s+الحاقات|"
        r"که|می\s*باشد|خواهد\s+بود|است)(?:\s|$))",
        value, maxsplit=1,
    )[0]
    return value.strip(" ،؛.ـ-–")


def parse_legal_number_tokens(value: str) -> list[str]:
    normalized = normalize_digits(value)
    output: list[str] = []
    for token in re.findall(
        r"\d+(?:\s*مکرر)?|یک|دو|سه|چهار|پنج|شش|هفت|هشت|نه|ده",
        normalized, flags=re.IGNORECASE,
    ):
        compact = normalize_space(token)
        if compact in PERSIAN_NUMBER_WORDS:
            output.append(PERSIAN_NUMBER_WORDS[compact])
        else:
            output.append(compact.replace(" ", "_"))
    return output


def relation_type_for_legal_context(context: str) -> str:
    normalized = normalize_fa(context)
    if re.search(r"لغو|ملغی|نسخ|منسوخ|بی اعتبار", normalized):
        return "REPEALS_OR_DISAPPLIES"
    if re.search(r"اصلاح|الحاق|تغییر", normalized):
        return "INTERPRETS_AMENDMENT"
    if re.search(r"در اجرای|اجرایی|اجرای", normalized):
        return "IMPLEMENTS"
    if re.search(r"لازم الاتباع|مستند|مطابق|به موجب|با استناد", normalized):
        return "APPLIES"
    return "REFERENCES"


def relation_type_for_decision_context(context: str) -> str:
    normalized = normalize_fa(context)
    if re.search(r"عدول|منسوخ|نسخ|بی اعتبار", normalized):
        return "OVERRULES_DECISION"
    if re.search(r"تایید|تأیید|صحیح و قانونی|موافق", normalized):
        return "AFFIRMS_DECISION"
    if re.search(r"معارض|مغایر|مخالف", normalized):
        return "DISTINGUISHES_DECISION"
    return "CITES_DECISION"


class LegalResolver:
    """Optional resolver against the SQLite output of the previous legal crawler."""

    def __init__(self, db_path: Optional[Path]):
        self.db_path = db_path
        self.normalized_to_rows: dict[str, list[tuple[str, str, str, str]]] = {}
        self.choices: list[str] = []
        self.article_lookup: dict[tuple[str, str, str], tuple[str, str, str]] = {}
        if db_path:
            self._load(db_path)

    def _load(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"Legal database not found: {db_path}")
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                "SELECT id,type,title,url FROM nodes "
                "WHERE type IN ('document','law_group') AND title IS NOT NULL AND title<>''"
            ).fetchall()
            for node_id, node_type, title, url in rows:
                normalized = normalize_fa(title)
                if len(normalized) < 3:
                    continue
                self.normalized_to_rows.setdefault(normalized, []).append(
                    (node_id, node_type, title, url or "")
                )
            self.choices = list(self.normalized_to_rows)

            article_rows = connection.execute(
                "SELECT id,subtype,numeric_id,title,url FROM nodes "
                "WHERE type='article' AND numeric_id IS NOT NULL"
            ).fetchall()
            article_re = re.compile(r"^article:(document:(?:child|show):\d+):(ماده|اصل):(\d+)$")
            for article_id, subtype, numeric_id, title, url in article_rows:
                match = article_re.match(article_id)
                if not match:
                    continue
                document_id, label, number = match.groups()
                self.article_lookup[(document_id, label, number)] = (
                    article_id, title or f"{label} {number}", url or ""
                )
        finally:
            connection.close()
        logging.info(
            "Loaded legal resolver: %d titles, %d article keys",
            len(self.choices), len(self.article_lookup),
        )

    def resolve_document(self, raw_target: str) -> tuple[Optional[Node], float]:
        candidate = normalize_fa(clean_legal_title(raw_target))
        candidate = re.split(
            r"\b(?:که|می باشد|است|خواهد|گردید|موضوع|مصوب|در خصوص|با اصلاحات)\b",
            candidate, maxsplit=1,
        )[0].strip(" ،؛.")
        if not candidate or not self.choices:
            return None, 0.0

        normalized_title = None
        confidence = 0.0
        if candidate in self.normalized_to_rows:
            normalized_title, confidence = candidate, 1.0
        else:
            contained = [title for title in self.choices if len(title) >= 5 and title in candidate]
            if contained:
                normalized_title, confidence = max(contained, key=len), 0.96
            else:
                match = process.extractOne(
                    candidate, self.choices, scorer=fuzz.token_set_ratio, score_cutoff=82
                )
                if match:
                    normalized_title, score, _ = match
                    confidence = round(score / 100.0, 3)
        if not normalized_title:
            return None, 0.0

        rows = self.normalized_to_rows[normalized_title]
        node_id, node_type, title, url = rows[0]
        return Node(
            id=node_id,
            type="legal_document" if node_type == "document" else "legal_group",
            subtype=node_type,
            numeric_id=None,
            title=title,
            url=url,
            access_status="linked_from_legal_db",
            metadata_json=json.dumps({"source_db": str(self.db_path)}, ensure_ascii=False),
        ), confidence

    def resolve_provision(
        self, document_node: Node, label: str, number: str
    ) -> Optional[Node]:
        resolved = self.article_lookup.get((document_node.id, label, number))
        if not resolved:
            return None
        article_id, title, url = resolved
        return Node(
            id=article_id,
            type="legal_provision",
            subtype=label,
            numeric_id=number,
            title=title,
            url=url,
            access_status="linked_from_legal_db",
            metadata_json=json.dumps({"source_db": str(self.db_path)}, ensure_ascii=False),
        )


def external_law_node(raw_target: str) -> Node:
    title = clean_legal_title(raw_target)
    normalized = normalize_fa(title)
    node_id = "external_legal_document:" + sha256_text(normalized)[:20]
    return Node(
        id=node_id,
        type="external_legal_document",
        subtype="unresolved_title",
        numeric_id=None,
        title=title,
        access_status="reference_only",
    )


def external_provision_node(document: Node, label: str, number: str) -> Node:
    return Node(
        id=f"external_legal_provision:{sha256_text(document.id + label + number)[:24]}",
        type="external_legal_provision",
        subtype=label,
        numeric_id=number,
        title=f"{label} {number} از {document.title}",
        access_status="reference_only",
    )


def extract_legal_relations(
    source: Node, resolver: LegalResolver
) -> tuple[list[Node], list[Relation]]:
    if not source.text:
        return [], []
    nodes: dict[str, Node] = {}
    relations: dict[tuple[str, str, str, str], Relation] = {}
    text = source.text

    for match in LEGAL_REF_RE.finditer(text):
        raw = normalize_space(match.group(0))
        target_phrase = normalize_space(match.group("target") or "")
        numbers = parse_legal_number_tokens(match.group("numbers"))
        kind = match.group("kind")
        label = "اصل" if kind in {"اصل", "اصول"} else ("ماده" if kind in {"ماده", "مواد"} else kind)
        context = sentence_context(text, match.start(), match.end())
        relation_type = relation_type_for_legal_context(context)

        document_node = None
        confidence = 0.45
        if target_phrase:
            document_node, confidence = resolver.resolve_document(target_phrase)
            if not document_node:
                document_node = external_law_node(target_phrase)
                confidence = 0.45
            nodes[document_node.id] = document_node

        if document_node and numbers and label in {"ماده", "اصل", "تبصره", "بند"}:
            for number in numbers:
                provision = resolver.resolve_provision(document_node, label, number)
                if not provision:
                    provision = external_provision_node(document_node, label, number)
                nodes[provision.id] = provision
                relation_key = (document_node.id, provision.id, "CONTAINS", "")
                relations[relation_key] = Relation(
                    document_node.id, provision.id, "CONTAINS", confidence=0.85
                )
                key = (source.id, provision.id, relation_type, raw)
                relations[key] = Relation(
                    source.id, provision.id, relation_type,
                    raw_reference=raw, confidence=confidence, source_url=source.url,
                )
        elif document_node:
            key = (source.id, document_node.id, relation_type, raw)
            relations[key] = Relation(
                source.id, document_node.id, relation_type,
                raw_reference=raw, confidence=confidence, source_url=source.url,
            )
        else:
            unresolved_id = "unresolved_legal_reference:" + sha256_text(raw)[:20]
            unresolved = Node(
                id=unresolved_id,
                type="unresolved_legal_reference",
                subtype=label,
                numeric_id=",".join(numbers) or None,
                title=raw,
                access_status="reference_only",
            )
            nodes[unresolved.id] = unresolved
            key = (source.id, unresolved.id, relation_type, raw)
            relations[key] = Relation(
                source.id, unresolved.id, relation_type,
                raw_reference=raw, confidence=0.35, source_url=source.url,
            )

    # Capture standalone law/regulation mentions that were not already part of a
    # provision citation. This preserves document-level relations such as
    # "به موجب قانون ..." even when no article number is given.
    provision_spans = [match.span() for match in LEGAL_REF_RE.finditer(text)]
    for match in STANDALONE_LAW_RE.finditer(text):
        if any(not (match.end() <= start or match.start() >= end) for start, end in provision_spans):
            continue
        raw = normalize_space(match.group(0))
        target_phrase = clean_legal_title(match.group("target"))
        if len(target_phrase) < 6:
            continue
        document_node, confidence = resolver.resolve_document(target_phrase)
        if not document_node:
            document_node = external_law_node(target_phrase)
            confidence = 0.42
        nodes[document_node.id] = document_node
        context = sentence_context(text, match.start(), match.end())
        relation_type = relation_type_for_legal_context(context)
        key = (source.id, document_node.id, relation_type, raw)
        relations[key] = Relation(
            source.id, document_node.id, relation_type,
            raw_reference=raw, confidence=confidence, source_url=source.url,
        )

    return list(nodes.values()), list(relations.values())


def normalize_decision_key(value: str) -> str:
    return normalize_fa(value).replace(" ", "").replace("شماره", "")


def extract_decision_citations(
    source: Node,
    decision_number_lookup: dict[str, list[str]],
) -> tuple[list[Node], list[Relation]]:
    if not source.text:
        return [], []
    nodes: dict[str, Node] = {}
    relations: dict[tuple[str, str, str, str], Relation] = {}
    text = source.text

    for match in DECISION_CITATION_RE.finditer(text):
        raw = normalize_space(match.group(0))
        # Ignore the current decision heading/date line when it repeats the title.
        if match.start() < 10 and source.decision_number and source.decision_number in raw:
            continue
        numbers = parse_number_tokens(match.group("numbers"))
        context = sentence_context(text, match.start(), match.end())
        relation_type = relation_type_for_decision_context(context)
        for number in numbers:
            key_number = normalize_decision_key(number)
            target_ids = decision_number_lookup.get(key_number, [])
            if len(target_ids) == 1:
                target_id = target_ids[0]
                confidence = 0.95
            else:
                target_id = "external_unanimity_decision:" + sha256_text(key_number)[:20]
                confidence = 0.40 if not target_ids else 0.60
                nodes[target_id] = Node(
                    id=target_id,
                    type="external_unanimity_decision",
                    subtype="citation",
                    numeric_id=None,
                    title=f"رأی وحدت رویه شماره {number}",
                    decision_number=number,
                    access_status="reference_only",
                )
            if target_id == source.id:
                continue
            key = (source.id, target_id, relation_type, raw)
            relations[key] = Relation(
                source.id, target_id, relation_type,
                raw_reference=raw, confidence=confidence, source_url=source.url,
            )
    return list(nodes.values()), list(relations.values())


class GraphStore:
    COLUMNS = [
        "id", "type", "subtype", "numeric_id", "title", "url", "year",
        "decision_number", "approval_date", "subject", "issuing_body", "text",
        "access_status", "content_hash", "fetched_at", "metadata_json",
    ]

    def __init__(self, path: Path):
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=OFF")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                subtype TEXT,
                numeric_id TEXT,
                title TEXT,
                url TEXT,
                year TEXT,
                decision_number TEXT,
                approval_date TEXT,
                subject TEXT,
                issuing_body TEXT,
                text TEXT,
                access_status TEXT,
                content_hash TEXT,
                fetched_at TEXT,
                metadata_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_year ON nodes(year);
            CREATE INDEX IF NOT EXISTS idx_nodes_number ON nodes(decision_number);
            CREATE INDEX IF NOT EXISTS idx_nodes_url ON nodes(url);

            CREATE TABLE IF NOT EXISTS relations (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                raw_reference TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 1.0,
                source_url TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (source_id, target_id, relation_type, raw_reference)
            );
            CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_id);
            CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_id);
            CREATE INDEX IF NOT EXISTS idx_rel_type ON relations(relation_type);
            """
        )
        self.connection.commit()

    def upsert_nodes(self, nodes: Iterable[Node]) -> None:
        rows = []
        for node in nodes:
            item = asdict(node)
            rows.append(tuple(item[column] for column in self.COLUMNS))
        if not rows:
            return
        placeholders = ",".join("?" for _ in self.COLUMNS)
        updates = ",\n".join(
            f"{column}=CASE WHEN excluded.{column} IS NOT NULL AND excluded.{column}<>'' "
            f"THEN excluded.{column} ELSE nodes.{column} END"
            for column in self.COLUMNS if column not in {"id", "type"}
        )
        self.connection.executemany(
            f"""
            INSERT INTO nodes ({','.join(self.COLUMNS)}) VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                {updates}
            """,
            rows,
        )
        self.connection.commit()

    def upsert_relations(self, relations: Iterable[Relation]) -> None:
        rows = [(
            relation.source_id, relation.target_id, relation.relation_type,
            relation.raw_reference or "", relation.confidence, relation.source_url or "",
        ) for relation in relations]
        if not rows:
            return
        self.connection.executemany(
            """
            INSERT INTO relations (
                source_id,target_id,relation_type,raw_reference,confidence,source_url
            ) VALUES (?,?,?,?,?,?)
            ON CONFLICT(source_id,target_id,relation_type,raw_reference)
            DO UPDATE SET
                confidence=MAX(relations.confidence,excluded.confidence),
                source_url=CASE WHEN excluded.source_url<>'' THEN excluded.source_url ELSE relations.source_url END
            """,
            rows,
        )
        self.connection.commit()

    def all_nodes(self, node_type: Optional[str] = None) -> list[Node]:
        query = f"SELECT {','.join(self.COLUMNS)} FROM nodes"
        params: tuple[str, ...] = ()
        if node_type:
            query += " WHERE type=?"
            params = (node_type,)
        return [Node(*row) for row in self.connection.execute(query, params).fetchall()]

    def relations(self, relation_type: Optional[str] = None) -> list[Relation]:
        query = (
            "SELECT source_id,target_id,relation_type,raw_reference,confidence,source_url "
            "FROM relations"
        )
        params: tuple[str, ...] = ()
        if relation_type:
            query += " WHERE relation_type=?"
            params = (relation_type,)
        return [Relation(*row) for row in self.connection.execute(query, params).fetchall()]

    def propagate_years(self) -> None:
        self.connection.execute(
            """
            UPDATE nodes AS decision
            SET year=(
                SELECT parent.year
                FROM relations r
                JOIN nodes parent ON parent.id=r.source_id
                WHERE r.target_id=decision.id
                  AND r.relation_type='CONTAINS'
                  AND parent.type='year'
                  AND parent.year IS NOT NULL
                LIMIT 1
            )
            WHERE decision.type='decision' AND decision.year IS NULL
            """
        )
        self.connection.commit()

    def finalize_adjacency(self) -> None:
        rows = self.connection.execute(
            """
            SELECT r.source_id,r.target_id,s.decision_number,t.decision_number,r.source_url
            FROM relations r
            JOIN nodes s ON s.id=r.source_id
            JOIN nodes t ON t.id=r.target_id
            WHERE r.relation_type='ADJACENT_DECISION'
              AND s.type='decision' AND t.type='decision'
            """
        ).fetchall()
        output: list[Relation] = []
        for source_id, target_id, source_number, target_number, source_url in rows:
            if not source_number or not target_number:
                continue
            if source_number.isdigit() and target_number.isdigit():
                source_n, target_n = int(source_number), int(target_number)
                if target_n == source_n - 1:
                    kind = "PREVIOUS_DECISION"
                elif target_n == source_n + 1:
                    kind = "NEXT_DECISION"
                else:
                    continue
                output.append(Relation(
                    source_id, target_id, kind, confidence=0.95, source_url=source_url
                ))
        self.upsert_relations(output)

    def export(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "nodes": output_dir / "nodes.jsonl",
            "decisions": output_dir / "decisions.jsonl",
            "years": output_dir / "years.jsonl",
            "legal_references": output_dir / "legal_references.jsonl",
        }
        handles = {name: path.open("w", encoding="utf-8") for name, path in files.items()}
        try:
            query = f"SELECT {','.join(self.COLUMNS)} FROM nodes ORDER BY type,id"
            for row in self.connection.execute(query):
                item = dict(zip(self.COLUMNS, row))
                serialized = json.dumps(item, ensure_ascii=False) + "\n"
                handles["nodes"].write(serialized)
                if item["type"] == "decision":
                    handles["decisions"].write(serialized)
                elif item["type"] == "year":
                    handles["years"].write(serialized)
                elif item["type"] in {
                    "legal_document", "legal_group", "legal_provision",
                    "external_legal_document", "external_legal_provision",
                    "unresolved_legal_reference",
                }:
                    handles["legal_references"].write(serialized)
        finally:
            for handle in handles.values():
                handle.close()

        relation_columns = [
            "source_id", "target_id", "relation_type", "raw_reference", "confidence", "source_url"
        ]
        with (output_dir / "relations.jsonl").open("w", encoding="utf-8") as handle:
            rows = self.connection.execute(
                "SELECT source_id,target_id,relation_type,raw_reference,confidence,source_url "
                "FROM relations ORDER BY relation_type,source_id,target_id"
            )
            for row in rows:
                handle.write(json.dumps(dict(zip(relation_columns, row)), ensure_ascii=False) + "\n")

    def stats(self) -> dict[str, object]:
        node_counts = dict(
            self.connection.execute("SELECT type,COUNT(*) FROM nodes GROUP BY type").fetchall()
        )
        relation_counts = dict(
            self.connection.execute(
                "SELECT relation_type,COUNT(*) FROM relations GROUP BY relation_type"
            ).fetchall()
        )
        access_counts = dict(
            self.connection.execute(
                "SELECT COALESCE(access_status,'unknown'),COUNT(*) FROM nodes "
                "WHERE type='decision' GROUP BY COALESCE(access_status,'unknown')"
            ).fetchall()
        )
        return {"nodes": node_counts, "relations": relation_counts, "decision_access": access_counts}

    def close(self) -> None:
        self.connection.close()


class RobotsPolicy:
    def __init__(self, start_url: str, user_agent: str, obey: bool):
        self.start_url = start_url
        self.user_agent = user_agent
        self.obey = obey
        self.parser: Optional[RobotFileParser] = None

    async def load(self, client: httpx.AsyncClient) -> None:
        if not self.obey:
            return
        parts = urlsplit(self.start_url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = await client.get(robots_url, timeout=15)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
                self.parser = parser
                logging.info("Loaded robots.txt from %s", robots_url)
            else:
                logging.warning("robots.txt returned HTTP %s", response.status_code)
        except httpx.HTTPError as exc:
            logging.warning("Could not read robots.txt (%s); continuing conservatively", exc)

    def allowed(self, url: str) -> bool:
        return not self.obey or self.parser is None or self.parser.can_fetch(self.user_agent, url)


class Crawler:
    def __init__(
        self,
        start_url: str,
        output_dir: Path,
        concurrency: int,
        delay: float,
        timeout: float,
        retries: int,
        user_agent: str,
        obey_robots: bool,
        refresh: bool,
        max_pages: Optional[int],
        legal_db: Optional[Path],
        auth_cookies: Optional[dict[str, str]] = None,
    ):
        self.start_url = canonicalize_url(start_url)
        self.output_dir = output_dir
        self.auth_cookies = dict(auth_cookies or {})
        self.authenticated = bool(self.auth_cookies)
        # Never reuse anonymous paywall HTML during an authenticated crawl.
        # This also prevents authenticated HTML from being mixed with the public cache.
        cache_name = "raw_html_authenticated" if self.authenticated else "raw_html"
        self.raw_dir = output_dir / cache_name
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_host = urlsplit(self.start_url).netloc
        self.concurrency = max(1, concurrency)
        self.delay = max(0.0, delay)
        self.timeout = timeout
        self.retries = max(1, retries)
        self.user_agent = user_agent
        self.robots = RobotsPolicy(self.start_url, user_agent, obey_robots)
        self.refresh = refresh
        self.max_pages = max_pages
        self.store = GraphStore(output_dir / "novinlaw_unanimity.sqlite3")
        self.resolver = LegalResolver(legal_db)
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.throttle_lock = asyncio.Lock()
        self.seen_lock = asyncio.Lock()
        self.last_request_at = 0.0

    async def throttled_get(self, client: httpx.AsyncClient, url: str) -> str:
        async with self.semaphore:
            async with self.throttle_lock:
                elapsed = time.monotonic() - self.last_request_at
                if elapsed < self.delay:
                    await asyncio.sleep(self.delay - elapsed)
                self.last_request_at = time.monotonic()

            last_error: Optional[Exception] = None
            for attempt in range(1, self.retries + 1):
                try:
                    response = await client.get(url, timeout=self.timeout)
                    if response.status_code in {429, 500, 502, 503, 504}:
                        retry_after = response.headers.get("Retry-After")
                        wait = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else min(60.0, 2.0 ** attempt)
                        )
                        logging.warning(
                            "HTTP %s for %s; retrying in %.1fs",
                            response.status_code, url, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type.lower() and "text" not in content_type.lower():
                        raise RuntimeError(f"Unexpected content type {content_type!r} for {url}")
                    return response.text
                except (httpx.HTTPError, RuntimeError) as exc:
                    last_error = exc
                    if attempt < self.retries:
                        await asyncio.sleep(min(60.0, 2.0 ** attempt))
            raise RuntimeError(f"Failed after {self.retries} attempts: {url}: {last_error}")

    async def get_html(self, client: httpx.AsyncClient, route: Route) -> str:
        cache_path = self.raw_dir / safe_filename(route.node_id)
        if cache_path.exists() and not self.refresh:
            return cache_path.read_text(encoding="utf-8")
        if not self.robots.allowed(route.canonical_url):
            raise PermissionError(f"Blocked by robots.txt: {route.canonical_url}")
        html = await self.throttled_get(client, route.canonical_url)
        cache_path.write_text(html, encoding="utf-8")
        return html

    def parse_page(
        self, route: Route, html: str
    ) -> tuple[Node, list[Route], list[Node], list[Relation]]:
        soup = BeautifulSoup(html, "lxml")
        title = extract_title(soup, route)
        text = None
        year = extract_year(title)
        decision_number = None
        approval_date = None
        subject = None
        issuing_body = None
        access_status = "public"

        if route.node_type == "decision":
            decision_number = extract_decision_number(title)
            text, access_status = extract_decision_text(soup, title)
            approval_date = extract_approval_date(text)
            subject = extract_subject(text)
            issuing_body = extract_issuing_body(text)
            if not year:
                year = extract_year(approval_date or "")
            if not year:
                for item in breadcrumb_items(soup):
                    year = extract_year(item)
                    if year:
                        break
        elif route.node_type == "year":
            access_status = "index"
        else:
            access_status = "index"

        node = Node(
            id=route.node_id,
            type=route.node_type,
            subtype=route.subtype,
            numeric_id=route.numeric_id,
            title=title,
            url=route.canonical_url,
            year=year,
            decision_number=decision_number,
            approval_date=approval_date,
            subject=subject,
            issuing_body=issuing_body,
            text=text,
            access_status=access_status,
            content_hash=sha256_text(text or html),
            fetched_at=now_iso(),
            metadata_json=json.dumps(
                {"authenticated_fetch": self.authenticated},
                ensure_ascii=False,
            ),
        )

        extra_nodes: list[Node] = []
        extra_relations: list[Relation] = []
        if issuing_body:
            institution_id = "institution:" + sha256_text(normalize_fa(issuing_body))[:20]
            extra_nodes.append(Node(
                id=institution_id,
                type="institution",
                subtype="issuing_body",
                numeric_id=None,
                title=issuing_body,
                access_status="entity",
            ))
            extra_relations.append(Relation(
                node.id, institution_id, "ISSUED_BY", confidence=0.98,
                source_url=node.url,
            ))

        links = extract_internal_links(soup, route.canonical_url, self.allowed_host)
        breadcrumbs = extract_breadcrumb_routes(soup, route.canonical_url, self.allowed_host)
        extra_relations.extend(structural_relations(route, links, breadcrumbs))
        return node, links, extra_nodes, extra_relations

    async def run(self) -> None:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa,en;q=0.8",
        }
        limits = httpx.Limits(
            max_connections=self.concurrency,
            max_keepalive_connections=self.concurrency,
        )
        processed = 0
        seen: set[str] = set()

        cookie_jar = httpx.Cookies()
        for name, value in self.auth_cookies.items():
            cookie_jar.set(name, value, domain=self.allowed_host, path="/")

        async with httpx.AsyncClient(
            headers=headers,
            cookies=cookie_jar,
            follow_redirects=True,
            limits=limits,
            http2=True,
        ) as client:
            if self.authenticated:
                logging.info(
                    "Authenticated session enabled (%d cookies); using cache directory %s",
                    len(self.auth_cookies), self.raw_dir,
                )
            await self.robots.load(client)
            seed = parse_route(self.start_url, self.allowed_host)
            if not seed:
                raise ValueError(f"Start URL is not recognized: {self.start_url}")

            queue: asyncio.Queue[Route] = asyncio.Queue()
            await queue.put(seed)

            async def worker(worker_id: int) -> None:
                nonlocal processed
                while True:
                    route = await queue.get()
                    try:
                        async with self.seen_lock:
                            if route.node_id in seen:
                                continue
                            if self.max_pages is not None and processed >= self.max_pages:
                                continue
                            seen.add(route.node_id)
                            processed += 1
                            ordinal = processed
                        try:
                            html = await self.get_html(client, route)
                            node, links, extra_nodes, relations = self.parse_page(route, html)
                            self.store.upsert_nodes([node, *extra_nodes])
                            self.store.upsert_relations(relations)
                            logging.info(
                                "[%d] %s | %s | access=%s | links=%d",
                                ordinal, route.node_id, node.title, node.access_status, len(links),
                            )
                            if self.authenticated and node.access_status == "paywalled":
                                logging.warning(
                                    "Authenticated request still received a subscription gate for %s; "
                                    "the session may be expired or the account may not have access.",
                                    route.canonical_url,
                                )
                            for linked in links:
                                async with self.seen_lock:
                                    should_add = linked.node_id not in seen
                                if should_add:
                                    await queue.put(linked)
                        except PermissionError as exc:
                            logging.error("%s", exc)
                        except Exception as exc:
                            logging.exception(
                                "Worker %d failed on %s: %s",
                                worker_id, route.canonical_url, exc,
                            )
                    finally:
                        queue.task_done()

            workers = [asyncio.create_task(worker(i + 1)) for i in range(self.concurrency)]
            await queue.join()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        self.store.propagate_years()
        decisions = self.store.all_nodes("decision")
        decision_number_lookup: dict[str, list[str]] = {}
        for decision in decisions:
            if decision.decision_number:
                decision_number_lookup.setdefault(
                    normalize_decision_key(decision.decision_number), []
                ).append(decision.id)

        buffered_nodes: list[Node] = []
        buffered_relations: list[Relation] = []
        for decision in decisions:
            legal_nodes, legal_relations = extract_legal_relations(decision, self.resolver)
            citation_nodes, citation_relations = extract_decision_citations(
                decision, decision_number_lookup
            )
            buffered_nodes.extend(legal_nodes)
            buffered_nodes.extend(citation_nodes)
            buffered_relations.extend(legal_relations)
            buffered_relations.extend(citation_relations)
            if len(buffered_relations) >= 1000:
                self.store.upsert_nodes(buffered_nodes)
                self.store.upsert_relations(buffered_relations)
                buffered_nodes.clear()
                buffered_relations.clear()
        self.store.upsert_nodes(buffered_nodes)
        self.store.upsert_relations(buffered_relations)
        self.store.finalize_adjacency()
        self.store.export(self.output_dir)
        stats = self.store.stats()
        (self.output_dir / "stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logging.info("Finished: %s", json.dumps(stats, ensure_ascii=False))
        self.store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawl NovinLaw unanimity decisions and graph relations."
    )
    parser.add_argument("--start-url", default=DEFAULT_START_URL)
    parser.add_argument("--output", type=Path, default=Path("novinlaw_unanimity_output"))
    parser.add_argument("--legal-db", type=Path, default=None,
                        help="Optional novinlaw.sqlite3 from the earlier laws crawler")
    parser.add_argument(
        "--cookie-file", type=Path, default=None,
        help=(
            "Local file containing the Cookie header value or a JSON cookie object. "
            "Use chmod 600 and never commit this file."
        ),
    )
    parser.add_argument(
        "--cookie-env", default="NOVINLAW_COOKIE",
        help=(
            "Environment variable containing the Cookie header value; "
            "default: NOVINLAW_COOKIE. Ignored when --cookie-file is used."
        ),
    )
    parser.add_argument("--concurrency", type=int, default=3,
                        help="Keep low; default: 3")
    parser.add_argument("--delay", type=float, default=0.8,
                        help="Global minimum delay between requests; default: 0.8s")
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--ignore-robots", action="store_true",
                        help="Not recommended; only with explicit permission")
    parser.add_argument("--refresh", action="store_true",
                        help="Ignore cached HTML and fetch again")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="Test crawl limit, e.g. 20")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args.output.mkdir(parents=True, exist_ok=True)
    auth_cookies = load_auth_cookies(args.cookie_file, args.cookie_env)
    crawler = Crawler(
        start_url=args.start_url,
        output_dir=args.output,
        concurrency=args.concurrency,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        user_agent=args.user_agent,
        obey_robots=not args.ignore_robots,
        refresh=args.refresh,
        max_pages=args.max_pages,
        legal_db=args.legal_db,
        auth_cookies=auth_cookies,
    )
    await crawler.run()
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        logging.warning("Interrupted; cache and SQLite progress are preserved.")
        return 130
    except Exception as exc:
        logging.exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
