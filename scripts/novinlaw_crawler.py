#!/usr/bin/env python3
"""Polite, resumable crawler for the public legal pages on novinlaw.ir.

Outputs a SQLite graph plus JSONL exports:
- nodes: index/category/law-group/document/article/note
- structural relations: CONTAINS, LINKS_TO
- textual relations: REFERENCES, AMENDS, REPEALS, IMPLEMENTS

The crawler does not bypass authentication, CAPTCHA, rate limits, or access
controls. Review the website's terms and robots.txt before large-scale use.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
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
    "https://www.novinlaw.ir/rules/legals/"
    "%D9%82%D9%88%D8%A7%D9%86%DB%8C%D9%86-%D9%88-"
    "%D9%85%D9%82%D8%B1%D8%B1%D8%A7%D8%AA/lists"
)
USER_AGENT = "NovinLawResearchCrawler/1.0 (+contact: replace-with-your-email@example.com)"

PERSIAN_TO_ASCII = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
ARABIC_NORMALIZATION = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ك": "ک",
    "ۀ": "ه",
    "ة": "ه",
    "ؤ": "و",
    "إ": "ا",
    "أ": "ا",
    "ٱ": "ا",
})

ROUTE_PATTERNS = [
    ("document", "child", re.compile(r"/childs/show/(?P<id>\d+)(?:/|$)")),
    ("category", "parent", re.compile(r"/parent/(?P<id>\d+)(?:/|$)")),
    ("law_group", "childs", re.compile(r"/childs/(?P<id>\d+)(?:/|$)")),
    ("document", "show", re.compile(r"/show/(?P<id>\d+)(?:/|$)")),
    ("index", "lists", re.compile(r"/lists(?:/|$)")),
]

ARTICLE_RE = re.compile(
    r"(?:^|(?<=[\n\.؛]))\s*(?P<label>ماده|اصل)\s*[\(\[]?\s*"
    r"(?P<number>[۰-۹٠-٩0-9]+)\s*[\)\]]?\s*(?:[-–—ـ:]\s*)?",
    re.MULTILINE,
)
NOTE_RE = re.compile(
    r"(?:^|(?<=[\n\.؛]))\s*تبصره(?:\s*[\(\[]?\s*"
    r"(?P<number>[۰-۹٠-٩0-9]+)\s*[\)\]]?)?\s*(?:[-–—ـ:]\s*)?",
    re.MULTILINE,
)
LEGAL_REF_RE = re.compile(
    r"(?P<kind>ماده|مواد|اصل|اصول|تبصره|بند)\s+"
    r"(?P<numbers>[۰-۹٠-٩0-9\s،,و\-–تاالی]+?)"
    r"(?:\s+(?:از\s+)?(?P<target>"
    r"(?:قانون|آیین\s*نامه|اساسنامه|دستورالعمل|بخشنامه|تصویب\s*نامه|لایحه\s+قانونی)"
    r"[^\n\.؛]{2,140}))?"
    r"(?=$|[،؛\.\n])"
)

COMMON_NOISE = {
    "قانون درجیب شما",
    "قانون‌درجیب‌شما",
    "صفحه اصلی",
    "قوانین کاربردی",
    "درباره ما",
    "دریافت اپلیکیشن",
    "شبکه های اجتماعی",
    "شبکه‌های اجتماعی",
    "ورود",
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
    url: str
    category: Optional[str] = None
    approval_info: Optional[str] = None
    text: Optional[str] = None
    content_hash: Optional[str] = None
    fetched_at: Optional[str] = None


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


def normalize_fa(value: str) -> str:
    value = (value or "").translate(ARABIC_NORMALIZATION).translate(PERSIAN_TO_ASCII)
    value = value.replace("\u200c", " ").replace("\u200f", " ").replace("\ufeff", " ")
    value = re.sub(r"[\(\)\[\]«»\"'`]+", " ", value)
    return normalize_space(value).lower()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parts.path)
    # Slugs after numeric IDs are decorative; remove them for deduplication.
    path = re.sub(r"(/childs/show/\d+)(?:/.*)?$", r"\1", path)
    path = re.sub(r"(/parent/\d+)(?:/.*)?$", r"\1", path)
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
    if "/rules/legals/" not in decoded_path:
        return None

    for node_type, subtype, pattern in ROUTE_PATTERNS:
        match = pattern.search(decoded_path)
        if not match:
            continue
        numeric_id = match.groupdict().get("id")
        if node_type == "index":
            node_id = "index:lists"
        elif node_type == "document":
            node_id = f"document:{subtype}:{numeric_id}"
        else:
            node_id = f"{node_type}:{numeric_id}"
        return Route(node_type, subtype, numeric_id, node_id, canonical)
    return None


def safe_filename(node_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", node_id) + ".html"


def clean_title(title: str) -> str:
    title = normalize_space(title)
    title = re.sub(r"\s*[-|]\s*قانون.?درجیب.?شما.*$", "", title, flags=re.I)
    title = re.sub(r"^.*?\s[-–|]\s(?=(قانون|آیین|اساسنامه|دستورالعمل|بخشنامه))", "", title)
    return title.strip(" -–|")


def soup_text(tag: Optional[Tag]) -> str:
    return normalize_space(tag.get_text(" ", strip=True)) if tag else ""


def breadcrumb_container(soup: BeautifulSoup) -> Optional[Tag]:
    selectors = [
        ".breadcrumb",
        ".breadcrumbs",
        ".bread-crumb",
        "nav[aria-label*=breadcrumb]",
        "ol.breadcrumb",
        "ul.breadcrumb",
    ]
    for selector in selectors:
        found = soup.select_one(selector)
        if found:
            return found
    return None


def extract_title(soup: BeautifulSoup, route: Route) -> str:
    h1 = soup.find("h1")
    if h1 and soup_text(h1):
        return soup_text(h1)

    crumb = breadcrumb_container(soup)
    if crumb:
        text = soup_text(crumb)
        links_text = [soup_text(a) for a in crumb.find_all("a")]
        remainder = text
        for value in links_text:
            remainder = remainder.replace(value, "", 1).strip()
        if remainder:
            return normalize_space(remainder)

    if soup.title and soup.title.string:
        raw = clean_title(soup.title.string)
        pieces = [p.strip() for p in re.split(r"\s[-–|]\s", raw) if p.strip()]
        return pieces[-1] if pieces else raw

    return route.node_id


def choose_content_container(soup: BeautifulSoup) -> Tag:
    h1 = soup.find("h1")
    preferred = soup.select_one(
        "article, main, .article-content, .post-content, .single-content, "
        ".entry-content, .content-detail, .rule-content, .legal-content"
    )
    if preferred and len(soup_text(preferred)) > 100:
        return preferred

    if h1:
        ancestors: list[Tag] = []
        parent = h1.parent
        while isinstance(parent, Tag) and parent.name != "body":
            ancestors.append(parent)
            parent = parent.parent
        for candidate in ancestors:
            text_len = len(soup_text(candidate))
            if text_len >= 300:
                return candidate

    return soup.body or soup


def extract_document_text(soup: BeautifulSoup) -> str:
    # Work on a reparsed fragment so destructive cleanup does not alter link parsing.
    container = choose_content_container(soup)
    fragment = BeautifulSoup(str(container), "lxml")
    cleanup_selector = (
        "script, style, noscript, svg, header, footer, nav, aside, form, button, "
        ".breadcrumb, .breadcrumbs, .bread-crumb, .share, .social, .comments"
    )
    for tag in fragment.select(cleanup_selector):
        tag.decompose()
    h1 = fragment.find("h1")
    if h1:
        h1.decompose()

    lines: list[str] = []
    for line in fragment.get_text("\n", strip=True).splitlines():
        value = normalize_space(line)
        if not value or value in COMMON_NOISE:
            continue
        lines.append(value)

    # Preserve paragraph boundaries while removing immediate duplicates.
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped).strip()


def extract_approval_info(text: str) -> Optional[str]:
    for line in text.splitlines()[:8]:
        if re.search(r"مصوب|تصویب|اصلاحات|الحاقات", line):
            return normalize_space(line)
    match = re.search(r"([^\n]{0,180}(?:مصوب|تصویب)[^\n]{0,180})", text)
    return normalize_space(match.group(1)) if match else None


def extract_internal_links(soup: BeautifulSoup, page_url: str, allowed_host: str) -> list[Route]:
    routes: dict[str, Route] = {}
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(page_url, anchor.get("href", ""))
        route = parse_route(absolute, allowed_host)
        if route:
            routes[route.node_id] = route
    return list(routes.values())


def extract_breadcrumb_routes(soup: BeautifulSoup, page_url: str, allowed_host: str) -> list[Route]:
    crumb = breadcrumb_container(soup)
    if not crumb:
        return []
    routes: list[Route] = []
    for anchor in crumb.find_all("a", href=True):
        route = parse_route(urljoin(page_url, anchor.get("href", "")), allowed_host)
        if route and route.node_type != "index":
            routes.append(route)
    return routes


def structural_relations(
    source: Route,
    links: Iterable[Route],
    breadcrumb_routes: Iterable[Route],
) -> list[Relation]:
    output: dict[tuple[str, str, str], Relation] = {}

    def add(src: str, dst: str, kind: str, confidence: float = 1.0) -> None:
        if src == dst:
            return
        key = (src, dst, kind)
        output[key] = Relation(src, dst, kind, confidence=confidence, source_url=source.canonical_url)

    links = list(links)
    breadcrumbs = list(breadcrumb_routes)

    for target in links:
        if target.node_id != source.node_id:
            add(source.node_id, target.node_id, "LINKS_TO", 0.70)

    # Category pages list laws/law-groups.
    if source.node_type == "category":
        for target in links:
            if target.node_type in {"law_group", "document"}:
                add(source.node_id, target.node_id, "CONTAINS", 1.0)

    # Law-group pages list child documents/sections.
    if source.node_type == "law_group":
        for target in links:
            if target.node_type == "document" and target.subtype == "child":
                add(source.node_id, target.node_id, "CONTAINS", 1.0)

    # Breadcrumbs recover hierarchy even when root-list markup is flattened.
    chain = breadcrumbs + ([source] if source.node_type != "index" else [])
    meaningful = [r for r in chain if r.node_type in {"category", "law_group", "document"}]
    for parent, child in zip(meaningful, meaningful[1:]):
        if parent.node_type == "category" and child.node_type in {"law_group", "document"}:
            add(parent.node_id, child.node_id, "CONTAINS", 1.0)
        elif parent.node_type == "law_group" and child.node_type == "document":
            add(parent.node_id, child.node_id, "CONTAINS", 1.0)

    return list(output.values())


def split_articles(document_id: str, text: str) -> tuple[list[Node], list[Relation]]:
    matches = list(ARTICLE_RE.finditer(text))
    nodes: list[Node] = []
    relations: list[Relation] = []
    if not matches:
        return nodes, relations

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = normalize_space(text[start:end])
        number = match.group("number").translate(PERSIAN_TO_ASCII)
        label = match.group("label")
        article_id = f"article:{document_id}:{label}:{number}"
        nodes.append(Node(
            id=article_id,
            type="article",
            subtype=label,
            numeric_id=number,
            title=f"{label} {number}",
            url="",
            text=section,
            content_hash=sha256_text(section),
        ))
        relations.append(Relation(document_id, article_id, "CONTAINS", confidence=1.0))

        note_matches = list(NOTE_RE.finditer(section))
        for note_index, note_match in enumerate(note_matches):
            note_start = note_match.start()
            note_end = note_matches[note_index + 1].start() if note_index + 1 < len(note_matches) else len(section)
            note_text = normalize_space(section[note_start:note_end])
            note_number = note_match.group("number")
            note_number_ascii = note_number.translate(PERSIAN_TO_ASCII) if note_number else str(note_index + 1)
            note_id = f"note:{article_id}:{note_number_ascii}"
            nodes.append(Node(
                id=note_id,
                type="note",
                subtype="تبصره",
                numeric_id=note_number_ascii,
                title=f"تبصره {note_number_ascii}",
                url="",
                text=note_text,
                content_hash=sha256_text(note_text),
            ))
            relations.append(Relation(article_id, note_id, "CONTAINS", confidence=1.0))

    return nodes, relations


def relation_type_from_context(context: str) -> str:
    context = normalize_fa(context)
    if re.search(r"لغو|ملغی|نسخ", context):
        return "REPEALS"
    if re.search(r"اصلاح|الحاق|تغییر", context):
        return "AMENDS"
    if re.search(r"اجرایی|اجرای|در اجرای", context):
        return "IMPLEMENTS"
    return "REFERENCES"


def parse_reference_numbers(value: str) -> list[str]:
    value = value.translate(PERSIAN_TO_ASCII)
    return re.findall(r"\d+", value)


def make_title_choices(nodes: Iterable[Node]) -> tuple[dict[str, str], list[str]]:
    normalized_to_id: dict[str, str] = {}
    for node in nodes:
        if node.type not in {"document", "law_group"} or not node.title:
            continue
        normalized = normalize_fa(node.title)
        if len(normalized) >= 3:
            normalized_to_id.setdefault(normalized, node.id)
    return normalized_to_id, list(normalized_to_id.keys())


def build_article_lookup(nodes: Iterable[Node], relations: Iterable[Relation]) -> dict[tuple[str, str, str], str]:
    document_articles: dict[str, dict[tuple[str, str], list[str]]] = {}
    article_pattern = re.compile(r"^article:(document:(?:child|show):\d+):(ماده|اصل):(\d+)$")
    for node in nodes:
        if node.type != "article":
            continue
        match = article_pattern.match(node.id)
        if not match:
            continue
        document_id, label, number = match.groups()
        document_articles.setdefault(document_id, {}).setdefault((label, number), []).append(node.id)

    lookup: dict[tuple[str, str, str], str] = {}
    for document_id, values in document_articles.items():
        for (label, number), article_ids in values.items():
            if len(article_ids) == 1:
                lookup[(document_id, label, number)] = article_ids[0]

    children_by_group: dict[str, list[str]] = {}
    for relation in relations:
        if (
            relation.relation_type == "CONTAINS"
            and relation.source_id.startswith("law_group:")
            and relation.target_id.startswith("document:")
        ):
            children_by_group.setdefault(relation.source_id, []).append(relation.target_id)

    for group_id, child_documents in children_by_group.items():
        candidates: dict[tuple[str, str], list[str]] = {}
        for document_id in child_documents:
            for key, article_ids in document_articles.get(document_id, {}).items():
                candidates.setdefault(key, []).extend(article_ids)
        for (label, number), article_ids in candidates.items():
            unique_ids = sorted(set(article_ids))
            if len(unique_ids) == 1:
                lookup[(group_id, label, number)] = unique_ids[0]
    return lookup


def resolve_title(raw_target: str, normalized_to_id: dict[str, str], choices: list[str]) -> tuple[Optional[str], float]:
    candidate = normalize_fa(raw_target)
    candidate = re.split(
        r"\b(?:که|می باشد|است|خواهد|گردید|موضوع|مصوب|و تبصره|و بند|در خصوص)\b",
        candidate,
        maxsplit=1,
    )[0].strip()
    if not candidate:
        return None, 0.0

    if candidate in normalized_to_id:
        return normalized_to_id[candidate], 1.0

    # Prefer a known title contained in the captured phrase.
    contained = [title for title in choices if len(title) >= 5 and title in candidate]
    if contained:
        best = max(contained, key=len)
        return normalized_to_id[best], 0.96

    match = process.extractOne(candidate, choices, scorer=fuzz.token_set_ratio, score_cutoff=80)
    if not match:
        return None, 0.0
    title, score, _ = match
    return normalized_to_id[title], round(score / 100.0, 3)


def extract_textual_relations(
    source_node: Node,
    normalized_to_id: dict[str, str],
    choices: list[str],
    article_lookup: Optional[dict[tuple[str, str, str], str]] = None,
) -> list[Relation]:
    if not source_node.text:
        return []
    output: dict[tuple[str, str, str, str], Relation] = {}
    text = source_node.text
    article_lookup = article_lookup or {}

    for match in LEGAL_REF_RE.finditer(text):
        raw = normalize_space(match.group(0))
        numbers = parse_reference_numbers(match.group("numbers"))
        # Do not turn the article's own heading into a self-citation.
        if (
            source_node.type == "article"
            and match.start() <= 8
            and numbers
            and source_node.numeric_id == numbers[0]
        ):
            continue
        target_phrase = match.group("target")
        context = text[max(0, match.start() - 80): min(len(text), match.end() + 80)]
        relation_type = relation_type_from_context(context)
        target_id: Optional[str] = None
        confidence = 0.55
        if target_phrase:
            target_id, confidence = resolve_title(target_phrase, normalized_to_id, choices)

        if not target_id and not target_phrase:
            if source_node.type == "document":
                target_id = source_node.id
                confidence = 0.72
            elif source_node.type in {"article", "note"}:
                marker = ":ماده:" if ":ماده:" in source_node.id else ":اصل:"
                target_id = source_node.id.split(marker, 1)[0].removeprefix("article:").removeprefix("note:")
                if target_id.startswith("article:"):
                    target_id = target_id.removeprefix("article:")
                confidence = 0.72

        if target_id and numbers and match.group("kind") in {"ماده", "مواد", "اصل", "اصول"}:
            label = "اصل" if match.group("kind") in {"اصل", "اصول"} else "ماده"
            resolved_any = False
            for number in numbers:
                article_target = article_lookup.get((target_id, label, number))
                if not article_target:
                    continue
                resolved_any = True
                key = (source_node.id, article_target, relation_type, raw)
                output[key] = Relation(
                    source_node.id,
                    article_target,
                    relation_type,
                    raw_reference=raw,
                    confidence=confidence,
                    source_url=source_node.url or None,
                )
            if not resolved_any:
                key = (source_node.id, target_id, relation_type, raw)
                output[key] = Relation(
                    source_node.id,
                    target_id,
                    relation_type,
                    raw_reference=raw,
                    confidence=max(0.45, confidence - 0.08),
                    source_url=source_node.url or None,
                )
        elif target_id:
            key = (source_node.id, target_id, relation_type, raw)
            output[key] = Relation(
                source_node.id,
                target_id,
                relation_type,
                raw_reference=raw,
                confidence=confidence,
                source_url=source_node.url or None,
            )
        else:
            # Preserve unresolved citations instead of discarding them.
            unresolved_id = "unresolved:" + sha256_text(raw)[:20]
            key = (source_node.id, unresolved_id, relation_type, raw)
            output[key] = Relation(
                source_node.id,
                unresolved_id,
                relation_type,
                raw_reference=raw,
                confidence=0.35,
                source_url=source_node.url or None,
            )

    return list(output.values())


class GraphStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.connection = sqlite3.connect(db_path)
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
                category TEXT,
                approval_info TEXT,
                text TEXT,
                content_hash TEXT,
                fetched_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
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
        rows = [(
            n.id, n.type, n.subtype, n.numeric_id, n.title, n.url,
            n.category, n.approval_info, n.text, n.content_hash, n.fetched_at,
        ) for n in nodes]
        self.connection.executemany(
            """
            INSERT INTO nodes (
                id, type, subtype, numeric_id, title, url, category,
                approval_info, text, content_hash, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                subtype=excluded.subtype,
                numeric_id=COALESCE(excluded.numeric_id, nodes.numeric_id),
                title=CASE WHEN excluded.title <> '' THEN excluded.title ELSE nodes.title END,
                url=CASE WHEN excluded.url <> '' THEN excluded.url ELSE nodes.url END,
                category=COALESCE(excluded.category, nodes.category),
                approval_info=COALESCE(excluded.approval_info, nodes.approval_info),
                text=COALESCE(excluded.text, nodes.text),
                content_hash=COALESCE(excluded.content_hash, nodes.content_hash),
                fetched_at=COALESCE(excluded.fetched_at, nodes.fetched_at)
            """,
            rows,
        )
        self.connection.commit()

    def upsert_relations(self, relations: Iterable[Relation]) -> None:
        rows = [(
            r.source_id, r.target_id, r.relation_type, r.raw_reference or "",
            r.confidence, r.source_url or "",
        ) for r in relations]
        self.connection.executemany(
            """
            INSERT INTO relations (
                source_id, target_id, relation_type, raw_reference, confidence, source_url
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation_type, raw_reference)
            DO UPDATE SET
                confidence=MAX(relations.confidence, excluded.confidence),
                source_url=CASE WHEN excluded.source_url <> '' THEN excluded.source_url ELSE relations.source_url END
            """,
            rows,
        )
        self.connection.commit()

    def all_nodes(self) -> list[Node]:
        cursor = self.connection.execute(
            "SELECT id,type,subtype,numeric_id,title,url,category,approval_info,text,content_hash,fetched_at FROM nodes"
        )
        return [Node(*row) for row in cursor.fetchall()]

    def propagate_categories(self) -> None:
        # category -> law/document and law -> child document
        changed = True
        while changed:
            cursor = self.connection.execute(
                """
                UPDATE nodes AS child
                SET category = (
                    SELECT CASE
                        WHEN parent.type='category' THEN parent.title
                        ELSE parent.category
                    END
                    FROM relations r
                    JOIN nodes parent ON parent.id=r.source_id
                    WHERE r.target_id=child.id
                      AND r.relation_type='CONTAINS'
                      AND (parent.type='category' OR parent.category IS NOT NULL)
                    ORDER BY CASE WHEN parent.type='category' THEN 0 ELSE 1 END
                    LIMIT 1
                )
                WHERE child.category IS NULL
                  AND EXISTS (
                    SELECT 1 FROM relations r2
                    JOIN nodes parent2 ON parent2.id=r2.source_id
                    WHERE r2.target_id=child.id
                      AND r2.relation_type='CONTAINS'
                      AND (parent2.type='category' OR parent2.category IS NOT NULL)
                  )
                """
            )
            changed = cursor.rowcount > 0
            self.connection.commit()

    def ensure_unresolved_nodes(self) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO nodes (id, type, subtype, title)
            SELECT target_id, 'unresolved_reference', 'citation',
                   CASE WHEN raw_reference <> '' THEN raw_reference ELSE target_id END
            FROM relations
            WHERE target_id LIKE 'unresolved:%'
            """
        )
        self.connection.commit()

    def export_jsonl(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        node_path = output_dir / "nodes.jsonl"
        relation_path = output_dir / "relations.jsonl"
        document_path = output_dir / "documents.jsonl"
        article_path = output_dir / "articles.jsonl"

        columns = [
            "id", "type", "subtype", "numeric_id", "title", "url", "category",
            "approval_info", "text", "content_hash", "fetched_at",
        ]
        rows = self.connection.execute(
            "SELECT id,type,subtype,numeric_id,title,url,category,approval_info,text,content_hash,fetched_at FROM nodes ORDER BY type,id"
        )
        with node_path.open("w", encoding="utf-8") as all_nodes, \
                document_path.open("w", encoding="utf-8") as docs, \
                article_path.open("w", encoding="utf-8") as articles:
            for row in rows:
                item = dict(zip(columns, row))
                serialized = json.dumps(item, ensure_ascii=False) + "\n"
                all_nodes.write(serialized)
                if item["type"] == "document":
                    docs.write(serialized)
                elif item["type"] in {"article", "note"}:
                    articles.write(serialized)

        rel_columns = [
            "source_id", "target_id", "relation_type", "raw_reference", "confidence", "source_url",
        ]
        rows = self.connection.execute(
            "SELECT source_id,target_id,relation_type,raw_reference,confidence,source_url FROM relations ORDER BY relation_type,source_id"
        )
        with relation_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(zip(rel_columns, row)), ensure_ascii=False) + "\n")

    def stats(self) -> dict[str, object]:
        node_counts = dict(self.connection.execute("SELECT type,COUNT(*) FROM nodes GROUP BY type").fetchall())
        relation_counts = dict(
            self.connection.execute("SELECT relation_type,COUNT(*) FROM relations GROUP BY relation_type").fetchall()
        )
        return {"nodes": node_counts, "relations": relation_counts}

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
                logging.warning("robots.txt returned HTTP %s; continuing conservatively", response.status_code)
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
    ):
        self.start_url = canonicalize_url(start_url)
        self.output_dir = output_dir
        self.raw_dir = output_dir / "raw_html"
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
        self.store = GraphStore(output_dir / "novinlaw.sqlite3")
        self.semaphore = asyncio.Semaphore(self.concurrency)
        self.last_request_at = 0.0
        self.throttle_lock = asyncio.Lock()

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
                        wait = float(retry_after) if retry_after and retry_after.isdigit() else min(60, 2 ** attempt)
                        logging.warning("HTTP %s for %s; retrying in %.1fs", response.status_code, url, wait)
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
                        await asyncio.sleep(min(60, 2 ** attempt))
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

    def parse_page(self, route: Route, html: str) -> tuple[Node, list[Route], list[Node], list[Relation]]:
        soup = BeautifulSoup(html, "lxml")
        title = extract_title(soup, route)
        text: Optional[str] = None
        approval: Optional[str] = None
        article_nodes: list[Node] = []
        article_relations: list[Relation] = []
        if route.node_type == "document":
            text = extract_document_text(soup)
            approval = extract_approval_info(text)

        node = Node(
            id=route.node_id,
            type=route.node_type,
            subtype=route.subtype,
            numeric_id=route.numeric_id,
            title=title,
            url=route.canonical_url,
            approval_info=approval,
            text=text,
            content_hash=sha256_text(text or html),
            fetched_at=now_iso(),
        )

        if route.node_type == "document" and text:
            article_nodes, article_relations = split_articles(route.node_id, text)
            for child in article_nodes:
                child.url = route.canonical_url
                child.fetched_at = node.fetched_at

        links = extract_internal_links(soup, route.canonical_url, self.allowed_host)
        breadcrumbs = extract_breadcrumb_routes(soup, route.canonical_url, self.allowed_host)
        structural = structural_relations(route, links, breadcrumbs)
        return node, links, article_nodes, structural + article_relations

    def _relations_from_store(self, relation_type: Optional[str] = None) -> list[Relation]:
        if relation_type:
            rows = self.store.connection.execute(
                "SELECT source_id,target_id,relation_type,raw_reference,confidence,source_url "
                "FROM relations WHERE relation_type=?",
                (relation_type,),
            ).fetchall()
        else:
            rows = self.store.connection.execute(
                "SELECT source_id,target_id,relation_type,raw_reference,confidence,source_url FROM relations"
            ).fetchall()
        return [Relation(*row) for row in rows]

    async def run(self) -> None:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fa,en;q=0.8",
        }
        limits = httpx.Limits(max_connections=self.concurrency, max_keepalive_connections=self.concurrency)
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, limits=limits, http2=True) as client:
            await self.robots.load(client)
            seed = parse_route(self.start_url, self.allowed_host)
            if not seed:
                raise ValueError(f"Start URL is not recognized: {self.start_url}")

            queue: asyncio.Queue[Route] = asyncio.Queue()
            await queue.put(seed)
            seen: set[str] = set()
            processed = 0

            async def worker(worker_id: int) -> None:
                nonlocal processed
                while True:
                    route = await queue.get()
                    try:
                        if route.node_id in seen:
                            continue
                        if self.max_pages is not None and processed >= self.max_pages:
                            continue
                        seen.add(route.node_id)
                        try:
                            html = await self.get_html(client, route)
                            node, links, article_nodes, relations = self.parse_page(route, html)
                            self.store.upsert_nodes([node, *article_nodes])
                            self.store.upsert_relations(relations)
                            processed += 1
                            logging.info(
                                "[%d] %s | %s | links=%d articles/notes=%d",
                                processed, route.node_id, node.title, len(links), len(article_nodes),
                            )
                            for linked_route in links:
                                if linked_route.node_id not in seen:
                                    await queue.put(linked_route)
                        except PermissionError as exc:
                            logging.error("%s", exc)
                        except Exception as exc:  # keep the crawl alive and preserve progress
                            logging.exception("Worker %d failed on %s: %s", worker_id, route.canonical_url, exc)
                    finally:
                        queue.task_done()

            workers = [asyncio.create_task(worker(i + 1)) for i in range(self.concurrency)]
            await queue.join()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        # Second pass: category propagation and textual-reference resolution.
        self.store.propagate_categories()
        nodes = self.store.all_nodes()
        normalized_to_id, choices = make_title_choices(nodes)
        contains_relations = self._relations_from_store("CONTAINS")
        article_lookup = build_article_lookup(nodes, contains_relations)
        textual_relations: list[Relation] = []
        documents_with_articles = {
            relation.source_id
            for relation in contains_relations
            if relation.target_id.startswith("article:")
        }
        for node in nodes:
            should_extract = (
                node.type in {"article", "note"}
                or (node.type == "document" and node.id not in documents_with_articles)
            )
            if should_extract and node.text:
                textual_relations.extend(
                    extract_textual_relations(node, normalized_to_id, choices, article_lookup)
                )
                if len(textual_relations) >= 1000:
                    self.store.upsert_relations(textual_relations)
                    textual_relations.clear()
        if textual_relations:
            self.store.upsert_relations(textual_relations)

        self.store.ensure_unresolved_nodes()
        self.store.export_jsonl(self.output_dir)
        stats = self.store.stats()
        (self.output_dir / "stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logging.info("Finished: %s", json.dumps(stats, ensure_ascii=False))
        self.store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl NovinLaw legal documents and their graph relations.")
    parser.add_argument("--start-url", default=DEFAULT_START_URL)
    parser.add_argument("--output", type=Path, default=Path("novinlaw_output"))
    parser.add_argument("--concurrency", type=int, default=3, help="Keep this low; default: 3")
    parser.add_argument("--delay", type=float, default=0.8, help="Minimum delay between requests; default: 0.8s")
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--user-agent", default=USER_AGENT)
    parser.add_argument("--ignore-robots", action="store_true", help="Not recommended; use only with permission")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached HTML and fetch again")
    parser.add_argument("--max-pages", type=int, default=None, help="Useful for a test crawl, e.g. 20")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args.output.mkdir(parents=True, exist_ok=True)
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
    )
    await crawler.run()
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        logging.warning("Interrupted; cached HTML and SQLite progress are preserved.")
        return 130
    except Exception as exc:
        logging.exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())