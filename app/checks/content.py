import hashlib
from html.parser import HTMLParser

import httpx

from app.config import settings

THRESHOLD_RATIO = 0.30
CRITICAL_FIELDS = ("title", "h1")
THRESHOLD_FIELDS = ("link_count", "form_count", "text_length")
FIELD_LABELS = {
    "title": "Sayfa başlığı",
    "h1": "H1 metni",
    "meta_description": "Meta description",
    "link_count": "Bağlantı sayısı",
    "form_count": "Form sayısı",
    "text_length": "Görünür metin uzunluğu",
}


class _FingerprintParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None
        self.h1 = None
        self.meta_description = None
        self.link_count = 0
        self.form_count = 0
        self._text_parts = []
        self._in_title = False
        self._in_h1 = False
        self._h1_captured = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "h1" and not self._h1_captured:
            self._in_h1 = True
        elif tag == "meta" and (attrs_dict.get("name") or "").lower() == "description":
            self.meta_description = attrs_dict.get("content")
        elif tag == "a":
            self.link_count += 1
        elif tag == "form":
            self.form_count += 1
        elif tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1" and self._in_h1:
            self._in_h1 = False
            self._h1_captured = True
        elif tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or "") + data
        if self._in_h1:
            self.h1 = (self.h1 or "") + data
        if self._skip_depth == 0:
            self._text_parts.append(data)

    def fingerprint(self) -> dict:
        text = "".join(self._text_parts).strip()
        return {
            "title": self.title.strip() if self.title else None,
            "h1": self.h1.strip() if self.h1 else None,
            "meta_description": self.meta_description,
            "link_count": self.link_count,
            "form_count": self.form_count,
            "text_length": len(text),
        }


def extract_fingerprint(body: str) -> dict:
    parser = _FingerprintParser()
    parser.feed(body)
    return parser.fingerprint()


def compare_fingerprint(baseline: dict | None, current: dict) -> dict:
    if baseline is None:
        return {"changes": [], "critical_changed": False, "threshold_exceeded": []}

    changes = []
    critical_changed = False
    threshold_exceeded = []

    for field in ("title", "h1", "meta_description"):
        old, new = baseline.get(field), current.get(field)
        if old != new:
            changes.append(f"{FIELD_LABELS[field]} değişti: '{old}' → '{new}'")
            if field in CRITICAL_FIELDS:
                critical_changed = True

    for field in THRESHOLD_FIELDS:
        old, new = baseline.get(field), current.get(field)
        if not old:
            continue
        ratio = abs((new or 0) - old) / old
        if ratio > THRESHOLD_RATIO:
            changes.append(f"{FIELD_LABELS[field]} %{round(ratio * 100)} değişti: {old} → {new}")
            threshold_exceeded.append(field)

    return {"changes": changes, "critical_changed": critical_changed, "threshold_exceeded": threshold_exceeded}


async def check_content(url: str, expected_keyword: str | None, timeout: float = 10.0) -> dict:
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers={"User-Agent": settings.user_agent}
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return {"content_hash": None, "keyword_found": None, "fingerprint": None, "error": str(exc)}

    body = response.text
    content_hash = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
    keyword_found = expected_keyword.lower() in body.lower() if expected_keyword else None
    fingerprint = extract_fingerprint(body)
    return {"content_hash": content_hash, "keyword_found": keyword_found, "fingerprint": fingerprint, "error": None}
