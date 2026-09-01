#!/usr/bin/env python3
"""Return bounded, query-selected LabCapsule context as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys


MAX_MATCHES = 4
MAX_DETAIL_CHARS = 4000


def _load_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} root must be an object")
    return value


def query_catalog(catalog_path: Path, query: str) -> list[dict]:
    catalog = _load_object(catalog_path)
    root = catalog_path.parent.parent
    normalized = query.casefold()
    terms = set(re.findall(r"[a-z0-9_.+-]+|[\u4e00-\u9fff]{1,8}", normalized))
    ranked: list[tuple[int, dict]] = []
    for item in catalog.get("items", []):
        haystack = " ".join([str(item.get("id", "")), str(item.get("kind", "")),
                             str(item.get("summary", "")),
                             *[str(word) for word in item.get("keywords", [])]]).casefold()
        score = sum(4 if word in normalized else 1 for word in item.get("keywords", [])
                    if str(word).casefold() in normalized)
        score += sum(1 for term in terms if len(term) > 1 and term in haystack)
        if score:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("id", ""))))
    output: list[dict] = []
    detail_budget = MAX_DETAIL_CHARS
    for score, item in ranked[:MAX_MATCHES]:
        result = {"id": item.get("id"), "kind": item.get("kind"),
                  "summary": item.get("summary"), "score": score}
        detail_value = item.get("detail")
        if detail_value and detail_budget:
            detail_path = (root / str(detail_value)).resolve()
            detail_path.relative_to(root.resolve())
            if detail_path.is_file():
                detail = detail_path.read_text(encoding="utf-8")[:detail_budget]
                result["detail"] = detail
                detail_budget -= len(detail)
        output.append(result)
    return output


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--device-json", type=Path)
    parser.add_argument("--experiment-json", type=Path)
    args = parser.parse_args()
    payload = {"schemaVersion": 1, "query": args.query,
               "matches": query_catalog(args.catalog.resolve(), args.query)}
    if args.device_json:
        payload["device"] = _load_object(args.device_json.resolve())
    if args.experiment_json:
        payload["experiment"] = _load_object(args.experiment_json.resolve())
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
