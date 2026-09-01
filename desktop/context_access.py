"""Bounded, query-selected hardware context for the LabCapsule AI runtime."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "knowledge" / "catalog.json"
MAX_MATCHES = 4
MAX_DETAIL_CHARS = 4000


class ContextCatalog:
    def __init__(self, catalog_path: str | Path = CATALOG_PATH):
        self.path = Path(catalog_path).resolve()
        self.root = self.path.parent.parent
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("schemaVersion") != 1 or not isinstance(raw.get("items"), list):
            raise ValueError("元件知识目录格式无效")
        self.items = raw["items"]

    def select(self, query: str) -> list[dict]:
        normalized = query.casefold()
        terms = set(re.findall(r"[a-z0-9_.+-]+|[\u4e00-\u9fff]{1,8}", normalized))
        ranked: list[tuple[int, dict]] = []
        for item in self.items:
            keywords = [str(word).casefold() for word in item.get("keywords", [])]
            haystack = " ".join((str(item.get("id", "")), str(item.get("kind", "")),
                                 str(item.get("summary", "")), *keywords)).casefold()
            score = sum(4 if word in normalized else 1 for word in keywords
                        if word in normalized)
            score += sum(1 for term in terms if len(term) > 1 and term in haystack)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))
        budget = MAX_DETAIL_CHARS
        selected: list[dict] = []
        for score, item in ranked[:MAX_MATCHES]:
            entry = {"id": item.get("id"), "kind": item.get("kind"),
                     "summary": item.get("summary"), "score": score}
            relative = item.get("detail")
            if relative and budget:
                detail_path = (self.root / str(relative)).resolve()
                detail_path.relative_to(self.root)
                if detail_path.is_file():
                    detail = detail_path.read_text(encoding="utf-8")[:budget]
                    entry["detail"] = detail
                    budget -= len(detail)
            selected.append(entry)
        return selected


def compact_ai_context(query: str, live_context: dict,
                       catalog: ContextCatalog | None = None) -> dict:
    """Keep live evidence while adding only question-relevant static knowledge."""
    output = dict(live_context)
    try:
        matches = (catalog or ContextCatalog()).select(query)
    except (OSError, ValueError, json.JSONDecodeError):
        matches = []
    if matches:
        output["knowledge"] = matches
    return output
