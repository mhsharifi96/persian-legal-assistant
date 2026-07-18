#!/usr/bin/env python3
"""Polite, resumable crawler for public lawyer profiles on dadrah.ir.

Outputs:
  - dadrah.sqlite3
  - output/lawyers.csv
  - output/lawyers.jsonl
  - output/consultations.jsonl

The crawler uses only HTTP requests plus BeautifulSoup (v2). For a lawyer's
/advices page, it discovers the "مشاهده بیشتر" pagination/AJAX target and
requests each additional batch directly; no browser automation is required.

Run a small test first:
    python dadrah_crawler_bs4.py --max-list-pages 1 --max-lawyers 3

Then resume the full crawl:
    python dadrah_crawler_bs4.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html as html_lib
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
from urllib.parse import parse_qs, parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
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


@dataclass(slots=True)
class PaginationStrategy:
    label: str
    method: str
    url: str
    counter_key: str
    counter_mode: str  # "page" or "offset"
    payload: dict[str, str]


PAGINATION_PAGE_KEYS = (
    "page_num", "page", "p", "pageNum", "page_no", "pageNo",
    "pageNumber", "currentPage", "current_page",
)
PAGINATION_OFFSET_KEYS = (
    "offset", "start", "from", "skip", "index", "count", "position",
)
LAWYER_ID_KEYS = {
    "lawyerid", "lawyer_id", "lawyer", "userid", "user_id", "profileid",
    "profile_id", "consultantid", "consultant_id", "advisorid", "advisor_id",
    "expertid", "expert_id", "memberid", "member_id",
}
LOAD_MORE_TEXT = "مشاهده بیشتر"


def consultation_key(item: Consultation) -> str:
    canonical = clean_text(
        item.date + "\n" + item.title + "\n" + item.question + "\n" + item.answer
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def set_query_param(url: str, key: str, value: object) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def response_body_as_html(response: httpx.Response) -> str:
    """Return HTML from a normal response or from a JSON-wrapped AJAX response."""
    text = response.text
    content_type = response.headers.get("content-type", "").lower()
    looks_json = "json" in content_type or text.lstrip().startswith(("{", "["))
    if not looks_json:
        return text

    try:
        payload = response.json()
    except ValueError:
        return text

    strings: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    html_candidates = [
        value
        for value in strings
        if "<" in value or DATE_RE.search(clean_text(BeautifulSoup(value, "lxml").get_text(" ", strip=True)))
    ]
    return max(html_candidates, key=len) if html_candidates else text



def same_origin_url(raw_url: str, base_url: str) -> str:
    raw_url = clean_text(raw_url).strip("'\"")
    if not raw_url or raw_url.startswith(("#", "javascript:", "mailto:", "tel:")):
        return ""
    url = urljoin(base_url, raw_url)
    parsed = urlparse(url)
    base_parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != base_parsed.netloc:
        return ""
    return url


def external_script_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for tag in soup.find_all("script", src=True):
        url = same_origin_url(str(tag.get("src", "")), base_url)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def consultation_from_mapping(value: dict[str, object], source_url: str) -> Optional[Consultation]:
    """Parse one consultation from a JSON object returned by an AJAX endpoint."""
    normalized = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in value.items()}

    def pick(*keys: str) -> str:
        for key in keys:
            raw = normalized.get(re.sub(r"[^a-z0-9]", "", key.lower()))
            if isinstance(raw, (str, int, float)):
                text = clean_text(html_lib.unescape(str(raw)))
                if text:
                    return clean_text(BeautifulSoup(text, "lxml").get_text(" ", strip=True))
        return ""

    date = pick("date", "created_at", "createdAt", "answer_date", "answerDate", "jalali_date", "jalaliDate")
    title = pick("title", "subject", "topic", "caption")
    question = pick("question", "question_text", "request", "request_text", "body", "content", "text")
    answer = pick("answer", "answer_text", "reply", "response", "lawyer_answer", "comment")

    # Avoid interpreting arbitrary JSON metadata as a consultation.
    if not (question and answer):
        return None
    if date and not DATE_RE.fullmatch(date):
        match = DATE_RE.search(date)
        date = match.group(0) if match else ""

    raw_text = "\n".join(x for x in (date, title, question, answer) if x)
    return Consultation(
        date=date,
        title=title,
        question=question,
        answer=answer,
        raw_text=raw_text,
        source_url=source_url,
    )


def parse_advices_response(response: httpx.Response) -> list[Consultation]:
    """Parse full HTML, HTML fragments, or structured JSON AJAX responses."""
    source_url = str(response.url)
    candidates: list[Consultation] = []

    def add_html(raw: str) -> None:
        raw = html_lib.unescape(raw)
        if not raw.strip():
            return
        candidates.extend(parse_advices(raw, source_url))

    # Parse the raw body and the best JSON-wrapped HTML candidate.
    add_html(response.text)
    best = response_body_as_html(response)
    if best != response.text:
        add_html(best)

    try:
        payload = response.json()
    except ValueError:
        payload = None

    def walk(value: object) -> None:
        if isinstance(value, dict):
            item = consultation_from_mapping(value, source_url)
            if item:
                candidates.append(item)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str):
            text = html_lib.unescape(value)
            if "<" in text or DATE_RE.search(clean_text(text)):
                add_html(text)

    if payload is not None:
        walk(payload)

    deduped: list[Consultation] = []
    seen: set[str] = set()
    for item in candidates:
        key = consultation_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def extract_js_targets(javascript: str, base_url: str) -> list[dict[str, object]]:
    """Extract literal AJAX endpoints and form payload keys from JavaScript."""
    targets: list[dict[str, object]] = []

    def add(raw_url: str, method: str = "GET", payload: Optional[dict[str, str]] = None) -> None:
        url = same_origin_url(raw_url, base_url)
        if not url:
            return
        targets.append({"url": url, "method": method.upper(), "payload": dict(payload or {})})

    # jQuery shorthand calls.
    handled: set[tuple[str, str]] = set()
    for method, raw_url, object_source in re.findall(
        r"\$\.(get|post)\(\s*['\"]([^'\"]+)['\"]\s*,\s*\{(.*?)\}",
        javascript,
        flags=re.I | re.S,
    ):
        add(raw_url, method, parse_simple_js_object(object_source))
        handled.add((method.lower(), raw_url))
    for method, raw_url in re.findall(r"\$\.(get|post)\(\s*['\"]([^'\"]+)['\"]", javascript, flags=re.I):
        if (method.lower(), raw_url) not in handled:
            add(raw_url, method)

    # $.ajax({...}) blocks, including literal data objects.
    for block in re.findall(r"\$\.ajax\s*\(\s*\{(.*?)\}\s*\)", javascript, flags=re.I | re.S):
        url_match = re.search(r"\burl\s*:\s*['\"]([^'\"]+)['\"]", block, flags=re.I)
        if not url_match:
            continue
        method_match = re.search(r"\b(?:type|method)\s*:\s*['\"](GET|POST)['\"]", block, flags=re.I)
        data_match = re.search(r"\bdata\s*:\s*\{(.*?)\}", block, flags=re.I | re.S)
        add(
            url_match.group(1),
            method_match.group(1) if method_match else "GET",
            parse_simple_js_object(data_match.group(1)) if data_match else {},
        )

    # fetch(), axios, and XMLHttpRequest literal URLs.
    for raw_url, options in re.findall(r"fetch\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*\{(.*?)\})?", javascript, flags=re.I | re.S):
        method_match = re.search(r"\bmethod\s*:\s*['\"](GET|POST)['\"]", options or "", flags=re.I)
        add(raw_url, method_match.group(1) if method_match else "GET")
    for method, raw_url, object_source in re.findall(
        r"axios\.(get|post)\(\s*['\"]([^'\"]+)['\"](?:\s*,\s*\{(.*?)\})?",
        javascript,
        flags=re.I | re.S,
    ):
        add(raw_url, method, parse_simple_js_object(object_source or ""))
    for method, raw_url in re.findall(
        r"\.open\(\s*['\"](GET|POST)['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        javascript,
        flags=re.I,
    ):
        add(raw_url, method)

    # Literal endpoint strings in bundles. Restrict to URL-like strings with
    # load/advice/consult/ajax hints to avoid treating selectors as URLs.
    for raw_url in re.findall(r"['\"]((?:https?://|/|\.\.?/)[^'\"]+)['\"]", javascript):
        lowered = raw_url.lower()
        if any(hint in lowered for hint in ("advice", "consult", "ajax", "load-more", "loadmore")) and (
            "/" in raw_url or ".php" in lowered
        ):
            add(raw_url, "POST" if re.search(r"post", javascript[max(0, javascript.find(raw_url)-150):javascript.find(raw_url)+150], re.I) else "GET")

    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for target in targets:
        signature = json.dumps(target, sort_keys=True, ensure_ascii=False)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(target)
    return deduped

def parse_simple_js_object(source: str) -> dict[str, str]:
    """Parse literal key/value pairs from a small JavaScript object.

    Dynamic values are retained as empty strings so later code can fill known
    identifiers such as lawyerID from the profile row.
    """
    result: dict[str, str] = {}
    for match in re.finditer(
        r"(?:^|,)\s*['\"]?([A-Za-z_][\w-]*)['\"]?\s*:\s*([^,}]+)",
        source,
    ):
        key = match.group(1)
        raw = match.group(2).strip()
        quoted = re.fullmatch(r"['\"](.*?)['\"]", raw, flags=re.S)
        if quoted:
            value = quoted.group(1)
        elif re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
            value = raw
        elif raw.lower() in {"true", "false", "null"}:
            value = raw.lower()
        else:
            value = ""
        result[key] = clean_text(value)
    return result


def discover_load_more_targets(html: str, base_url: str, extra_javascript: str = "") -> list[dict[str, object]]:
    """Discover pagination/AJAX targets from the load-more element and scripts.

    The function intentionally avoids site-specific CSS classes. It checks href,
    data-* attributes, onclick handlers, forms, fetch(), $.get(), $.post(), and
    common $.ajax URL declarations.
    """
    soup = BeautifulSoup(html, "lxml")
    targets: list[dict[str, object]] = []

    def add_target(raw_url: str, method: str = "GET", payload: Optional[dict[str, str]] = None) -> None:
        raw_url = clean_text(raw_url).strip("'\"")
        if not raw_url or raw_url.startswith(("#", "javascript:", "mailto:", "tel:")):
            return
        url = urljoin(base_url, raw_url)
        parsed = urlparse(url)
        base_parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base_parsed.netloc:
            return
        targets.append(
            {
                "url": url,
                "method": method.upper(),
                "payload": dict(payload or {}),
            }
        )

    load_nodes: list[Tag] = []
    for tag in soup.find_all(["a", "button", "div", "span", "input"]):
        text = clean_text(tag.get("value", "") or tag.get_text(" ", strip=True))
        if LOAD_MORE_TEXT in text:
            load_nodes.append(tag)

    url_attrs = ("href", "data-url", "data-href", "data-endpoint", "data-api", "formaction")
    for node in load_nodes:
        payload: dict[str, str] = {}
        current: Optional[Tag] = node
        for _ in range(4):
            if current is None:
                break
            for attr, value in current.attrs.items():
                if not attr.startswith("data-"):
                    continue
                raw_key = attr[5:]
                key = raw_key.replace("-", "_")
                if isinstance(value, list):
                    value = " ".join(str(x) for x in value)
                value = clean_text(value)
                if value and key not in {"url", "href", "endpoint", "api", "method"}:
                    payload[key] = value
                    if raw_key in {"lawyer-id", "lawyer_id", "lawyerid"}:
                        payload.setdefault("lawyerID", value)
                        payload.setdefault("lawyerId", value)
            current = current.parent if isinstance(current.parent, Tag) else None

        method = clean_text(
            node.get("data-method", "") or node.get("formmethod", "") or "GET"
        ).upper()
        for attr in url_attrs:
            if node.get(attr):
                add_target(str(node.get(attr)), method, payload)

        if node.name == "button" and node.get("form"):
            form = soup.find("form", id=node.get("form"))
        else:
            form = node.find_parent("form")
        if isinstance(form, Tag) and form.get("action"):
            form_payload = payload.copy()
            for inp in form.select("input[name]"):
                form_payload[clean_text(inp.get("name"))] = clean_text(inp.get("value", ""))
            add_target(
                str(form.get("action")),
                clean_text(form.get("method", "GET")).upper(),
                form_payload,
            )

        onclick = clean_text(node.get("onclick", ""))
        if onclick:
            onclick_method = "POST" if re.search(r"\$\.post|method\s*[:=]\s*['\"]?post|type\s*[:=]\s*['\"]?post", onclick, re.I) else method
            for match in re.findall(r"['\"]((?:https?://|/)[^'\"]+)['\"]", onclick):
                add_target(match, onclick_method, payload)

    for script in soup.find_all("script"):
        code = script.string or script.get_text(" ", strip=False)
        lowered = code.lower()
        if not code or not (
            LOAD_MORE_TEXT in code
            or "loadmore" in lowered
            or "load_more" in lowered
            or ("advice" in lowered and ("ajax" in lowered or "fetch" in lowered))
        ):
            continue

        handled_calls: set[tuple[str, str]] = set()
        for method, raw_url, object_source in re.findall(
            r"\$\.(get|post)\(\s*['\"]([^'\"]+)['\"]\s*,\s*\{(.*?)\}",
            code,
            flags=re.I | re.S,
        ):
            add_target(raw_url, method.upper(), parse_simple_js_object(object_source))
            handled_calls.add((method.lower(), raw_url))
        for method, raw_url in re.findall(
            r"\$\.(get|post)\(\s*['\"]([^'\"]+)['\"]", code, flags=re.I
        ):
            if (method.lower(), raw_url) not in handled_calls:
                add_target(raw_url, method.upper())
        for raw_url in re.findall(r"fetch\(\s*['\"]([^'\"]+)['\"]", code, flags=re.I):
            add_target(raw_url, "GET")

        ajax_method = "POST" if re.search(
            r"(?:type|method)\s*:\s*['\"]POST['\"]", code, flags=re.I
        ) else "GET"
        for raw_url in re.findall(r"url\s*:\s*['\"]([^'\"]+)['\"]", code, flags=re.I):
            add_target(raw_url, ajax_method)

    # External bundles often contain the endpoint while the page only contains
    # an onclick function name. Carry data-* and hidden input values from the
    # load-more element into those external endpoints.
    context_payload: dict[str, str] = {}
    for node in load_nodes:
        current: Optional[Tag] = node
        for _ in range(4):
            if current is None:
                break
            for attr, value in current.attrs.items():
                if not attr.startswith("data-"):
                    continue
                key = attr[5:].replace("-", "_")
                if isinstance(value, list):
                    value = " ".join(str(x) for x in value)
                text = clean_text(value)
                if text and key not in {"url", "href", "endpoint", "api", "method"}:
                    context_payload.setdefault(key, text)
            current = current.parent if isinstance(current.parent, Tag) else None
        form = node.find_parent("form")
        if isinstance(form, Tag):
            for inp in form.select("input[name]"):
                context_payload.setdefault(clean_text(inp.get("name")), clean_text(inp.get("value", "")))

    for target in extract_js_targets(extra_javascript, base_url):
        merged = context_payload.copy()
        merged.update({str(k): str(v) for k, v in dict(target.get("payload") or {}).items()})
        target["payload"] = merged
        targets.append(target)

    # Preserve order while removing duplicates.
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for target in targets:
        signature = json.dumps(target, sort_keys=True, ensure_ascii=False)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(target)
    return deduped


def build_pagination_strategies(
    html: str,
    advice_url: str,
    lawyer_id: str,
    extra_javascript: str = "",
) -> list[PaginationStrategy]:
    """Build likely direct-HTTP pagination strategies, explicit targets first."""
    strategies: list[PaginationStrategy] = []

    def add(
        label: str,
        method: str,
        url: str,
        counter_key: str,
        counter_mode: str,
        payload: Optional[dict[str, str]] = None,
    ) -> None:
        strategies.append(
            PaginationStrategy(
                label=label,
                method=method.upper(),
                url=url,
                counter_key=counter_key,
                counter_mode=counter_mode,
                payload=dict(payload or {}),
            )
        )

    for index, target in enumerate(discover_load_more_targets(html, advice_url, extra_javascript), start=1):
        target_url = str(target["url"])
        method = str(target["method"])
        payload = {str(k): str(v) for k, v in dict(target.get("payload") or {}).items()}
        query = dict(parse_qsl(urlparse(target_url).query, keep_blank_values=True))

        if lawyer_id:
            id_keys = [
                key for key in payload
                if re.sub(r"[^a-z0-9_]", "", key.lower()) in LAWYER_ID_KEYS
                or any(token in key.lower() for token in ("lawyer", "consultant", "advisor", "profile", "expert"))
            ]
            if id_keys:
                for key in id_keys:
                    if not payload[key]:
                        payload[key] = lawyer_id
            else:
                # Dadrah's discovered endpoint may be GET or POST. Supplying the
                # public profile id as lawyerID is harmless for unrelated query
                # parameters and is required by older PHP handlers.
                payload["lawyerID"] = lawyer_id

        available_keys = list(query) + list(payload)
        existing_key = next(
            (key for key in available_keys if key.lower() in {x.lower() for x in (*PAGINATION_PAGE_KEYS, *PAGINATION_OFFSET_KEYS)}),
            "",
        )
        if existing_key:
            mode = "offset" if existing_key.lower() in {x.lower() for x in PAGINATION_OFFSET_KEYS} else "page"
            add(f"discovered-{index}-{existing_key}", method, target_url, existing_key, mode, payload)
        else:
            # Most Dadrah list pages use page_num or page; offset is kept as a fallback.
            for key, mode in (("page_num", "page"), ("page", "page"), ("offset", "offset")):
                candidate_payload = payload.copy()
                if method == "POST" and lawyer_id and not any(
                    name in candidate_payload for name in ("lawyerID", "lawyer_id", "lawyerId")
                ):
                    candidate_payload["lawyerID"] = lawyer_id
                add(f"discovered-{index}-{key}", method, target_url, key, mode, candidate_payload)

    # Server-side pagination fallbacks on the canonical /advices route.
    add("same-route-page-num", "GET", advice_url, "page_num", "page")
    add("same-route-page", "GET", advice_url, "page", "page")
    add("same-route-offset", "GET", advice_url, "offset", "offset")
    add("same-route-start", "GET", advice_url, "start", "offset")

    deduped: list[PaginationStrategy] = []
    seen: set[str] = set()
    for strategy in strategies:
        signature = json.dumps(
            {
                "method": strategy.method,
                "url": strategy.url,
                "key": strategy.counter_key,
                "mode": strategy.counter_mode,
                "payload": strategy.payload,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(strategy)
    return deduped


def strategy_request(
    strategy: PaginationStrategy,
    batch_number: int,
    batch_size: int,
) -> tuple[str, str, dict[str, str]]:
    value = batch_number if strategy.counter_mode == "page" else (batch_number - 1) * batch_size
    payload = strategy.payload.copy()
    if strategy.method == "GET":
        url = strategy.url
        for key, item in payload.items():
            if item != "":
                url = set_query_param(url, key, item)
        url = set_query_param(url, strategy.counter_key, value)
        return strategy.method, url, {}
    payload[strategy.counter_key] = str(value)
    return strategy.method, strategy.url, payload


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
        self.script_cache: dict[str, str] = {}

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

    async def request(
        self,
        method: str,
        url: str,
        *,
        data: Optional[dict[str, str]] = None,
        referer: str = "",
    ) -> httpx.Response:
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows: {url}")

        last_error: Optional[Exception] = None
        headers = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json, text/html, */*;q=0.8"}
        if referer:
            headers["Referer"] = referer
            parsed_referer = urlparse(referer)
            if parsed_referer.scheme and parsed_referer.netloc:
                headers["Origin"] = f"{parsed_referer.scheme}://{parsed_referer.netloc}"

        for attempt in range(1, self.args.retries + 1):
            try:
                logging.debug("HTTP strategy request: %s %s data=%s", method.upper(), url, data or {})
                response = await self.client.request(
                    method.upper(),
                    url,
                    data=data if method.upper() == "POST" else None,
                    headers=headers,
                )
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
        raise RuntimeError(
            f"Failed after {self.args.retries} attempts: {method.upper()} {url}: {last_error}"
        )

    async def fetch(self, url: str) -> httpx.Response:
        return await self.request("GET", url)

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

    async def page_javascript(self, html: str, page_url: str) -> str:
        """Fetch same-origin external JavaScript once and cache it."""
        chunks: list[str] = []
        total_bytes = 0
        for script_url in external_script_urls(html, page_url)[:20]:
            if script_url in self.script_cache:
                code = self.script_cache[script_url]
            else:
                try:
                    response = await self.request("GET", script_url, referer=page_url)
                    code = response.text if response.status_code == 200 else ""
                except PermissionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logging.debug("External script fetch failed %s: %s", script_url, exc)
                    code = ""
                self.script_cache[script_url] = code
            if not code:
                continue
            # Keep relevant bundles, but include small scripts even when minified
            # names do not describe their purpose.
            lowered = code.lower()
            if len(code) <= 350_000 or any(x in lowered for x in ("advice", "consult", "loadmore", "load_more", "ajax")):
                chunks.append(f"\n/* source: {script_url} */\n{code}")
                total_bytes += len(code.encode("utf-8", errors="ignore"))
            if total_bytes >= 2_000_000:
                break
        return "\n".join(chunks)

    async def fetch_all_advices_http(self, row: sqlite3.Row) -> list[Consultation]:
        advice_url = row["advice_url"]
        response = await self.fetch(advice_url)
        first_html = response_body_as_html(response)
        items = parse_advices_response(response)

        visible_text = clean_text(BeautifulSoup(first_html, "lxml").get_text(" ", strip=True))
        if LOAD_MORE_TEXT not in visible_text:
            return items
        if not items:
            raise ValueError("Load-more exists, but the first consultation batch could not be parsed")

        batch_size = len(items)
        initial_keys = {consultation_key(item) for item in items}
        javascript = await self.page_javascript(first_html, advice_url)
        strategies = build_pagination_strategies(
            first_html,
            advice_url,
            clean_text(row["lawyer_id"]),
            javascript,
        )

        accepted: Optional[PaginationStrategy] = None
        accepted_batch: list[Consultation] = []
        accepted_signature = ""
        diagnostics: list[dict[str, object]] = []

        for strategy in strategies:
            method, url, payload = strategy_request(strategy, 2, batch_size)
            diag: dict[str, object] = {
                "label": strategy.label,
                "method": method,
                "url": url,
                "payload": payload,
            }
            try:
                candidate_response = await self.request(
                    method,
                    url,
                    data=payload,
                    referer=advice_url,
                )
                candidate_items = parse_advices_response(candidate_response)
                fresh = [item for item in candidate_items if consultation_key(item) not in initial_keys]
                diag.update({
                    "status": candidate_response.status_code,
                    "content_type": candidate_response.headers.get("content-type", ""),
                    "body_length": len(candidate_response.content),
                    "parsed_items": len(candidate_items),
                    "fresh_items": len(fresh),
                    "body_prefix": clean_text(candidate_response.text[:500]),
                })
                if fresh:
                    accepted = strategy
                    accepted_batch = fresh
                    accepted_signature = hashlib.sha256(candidate_response.content).hexdigest()
                    logging.info(
                        "Detected consultation pagination for %s using %s (%s %s)",
                        row["name"] or row["lawyer_id"],
                        strategy.label,
                        method,
                        url,
                    )
                    diagnostics.append(diag)
                    break
            except PermissionError:
                raise
            except Exception as exc:  # noqa: BLE001
                diag["error"] = repr(exc)
                logging.debug("Pagination strategy %s failed: %s", strategy.label, exc)
            diagnostics.append(diag)

        if accepted is None:
            debug_dir = Path(self.args.debug_dir)
            debug_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^A-Za-z0-9_-]+", "_", urlparse(advice_url).path.strip("/")) or clean_text(row["lawyer_id"])
            (debug_dir / f"{slug}_advices.html").write_text(first_html, encoding="utf-8")
            (debug_dir / f"{slug}_scripts.js").write_text(javascript, encoding="utf-8")
            (debug_dir / f"{slug}_strategies.json").write_text(
                json.dumps(diagnostics, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if self.args.allow_partial_advices:
                logging.warning(
                    "Could not resolve load-more for %s; saving the first %d consultations because --allow-partial-advices is enabled",
                    row["name"] or row["lawyer_id"],
                    len(items),
                )
                return items
            raise RuntimeError(
                "The page has 'مشاهده بیشتر', but no direct HTTP strategy returned a new batch. "
                f"Diagnostics were saved under {debug_dir.resolve()}. The crawler inspected inline and external JavaScript, "
                "HTML fragments, and structured JSON; no Playwright fallback is used."
            )

        all_items = items + accepted_batch
        seen = {consultation_key(item) for item in all_items}

        for batch_number in range(3, self.args.max_advice_pages + 1):
            method, url, payload = strategy_request(accepted, batch_number, batch_size)
            response = await self.request(method, url, data=payload, referer=advice_url)
            response_signature = hashlib.sha256(response.content).hexdigest()
            page_items = parse_advices_response(response)
            fresh = [item for item in page_items if consultation_key(item) not in seen]
            if not fresh:
                break
            all_items.extend(fresh)
            seen.update(consultation_key(item) for item in fresh)

            body_html = response_body_as_html(response)
            has_more = LOAD_MORE_TEXT in clean_text(
                BeautifulSoup(body_html, "lxml").get_text(" ", strip=True)
            )
            if not has_more and len(fresh) < batch_size:
                break
            if response_signature == accepted_signature:
                break
            accepted_signature = response_signature
            await self.polite_sleep()

        return all_items

    async def crawl_advices(self) -> None:
        if self.args.skip_advices:
            logging.info("Skipping consultations because --skip-advices was supplied")
            return

        rows = self.db.pending_advices(self.args.max_lawyers)
        if not rows:
            logging.info("No pending consultation pages")
            return

        logging.info("Crawling consultations for %d lawyer(s) with HTTP + BeautifulSoup", len(rows))
        queue: asyncio.Queue[Optional[sqlite3.Row]] = asyncio.Queue()
        for row in rows:
            queue.put_nowait(row)
        for _ in range(self.args.advice_concurrency):
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
                    queue.task_done()
                    continue

                profile_url = row["profile_url"]
                advice_url = row["advice_url"]
                try:
                    items = await self.fetch_all_advices_http(row)
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
    parser.add_argument(
        "--max-advice-pages",
        type=int,
        default=2000,
        help="Maximum direct-HTTP consultation batches per lawyer",
    )
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--skip-advices", action="store_true")
    parser.add_argument(
        "--debug-dir",
        default="debug_dadrah",
        help="Directory for failed load-more HTML, JavaScript, and strategy reports",
    )
    parser.add_argument(
        "--allow-partial-advices",
        action="store_true",
        help="Save the first visible consultation batch when load-more cannot be resolved",
    )
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
