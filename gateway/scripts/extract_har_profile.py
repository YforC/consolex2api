#!/usr/bin/env python3
"""Extract upstream profile from console.x.ai HAR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _header_map(headers: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers:
        name = str(h.get("name", "")).lower()
        if not name:
            continue
        out[name] = str(h.get("value", ""))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract profile from HAR")
    parser.add_argument(
        "--har",
        default=r"D:\Desktop\consolex\console.x.ai.har",
        help="HAR file path",
    )
    parser.add_argument(
        "--out",
        default="gateway/har_profile.json",
        help="Output JSON path",
    )
    args = parser.parse_args()

    with open(args.har, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])
    matches = [e for e in entries if "/v1/responses" in e.get("request", {}).get("url", "")]
    if not matches:
        raise SystemExit("No /v1/responses request found in HAR")

    first = matches[0]["request"]
    headers = _header_map(first.get("headers", []))
    model_set: set[str] = set()
    for m in matches:
        body = m.get("request", {}).get("postData", {}).get("text", "")
        try:
            payload = json.loads(body)
        except ValueError:
            continue
        model = payload.get("model")
        if isinstance(model, str) and model:
            model_set.add(model)

    out_data = {
        "upstream_url": first.get("url", "https://console.x.ai/v1/responses"),
        "origin": headers.get("origin", "https://console.x.ai"),
        "referer": headers.get("referer", ""),
        "x_cluster": headers.get("x-cluster", "https://us-east-1.api.x.ai"),
        "user_agent": headers.get("user-agent", ""),
        "models": sorted(model_set),
        "sample_count": len(matches),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path} from {len(matches)} requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

