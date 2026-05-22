#!/usr/bin/env python3
"""Parse HAR file and extract relevant API requests for grok gateway analysis."""
import json
import sys
from urllib.parse import urlparse

HAR_FILE = r"D:\Desktop\consolex\console.x.ai.har"

def main():
    with open(HAR_FILE, "r", encoding="utf-8") as f:
        har = json.load(f)
    entries = har["log"]["entries"]
    print(f"Total entries: {len(entries)}")
    print("=" * 80)

    # Filter out static assets, tracking, telemetry
    skip_patterns = [
        ".js", ".css", ".woff", ".svg", ".png", ".jpg", ".jpeg", ".gif",
        ".ico", ".webp", ".map", ".json.gz", "/mp/track", "/_next/static",
        "sentry", "intercom", "growthbook", "stripe", "typekit",
        "/_next/data", "ingest.de", "/api/auth",
    ]

    interesting = []
    for e in entries:
        url = e["request"]["url"]
        method = e["request"]["method"]
        status = e["response"]["status"]
        if any(p in url for p in skip_patterns):
            continue
        # only x.ai domain
        if "x.ai" not in url:
            continue
        interesting.append(e)
        print(f"[{status}] {method} {url}")

    print(f"\nFiltered interesting entries: {len(interesting)}")

    # Look specifically for chat / completion endpoints
    print("\n" + "=" * 80)
    print("CHAT/COMPLETION-LIKE REQUESTS:")
    print("=" * 80)
    chat_like = []
    for e in interesting:
        url = e["request"]["url"].lower()
        if any(k in url for k in ["chat", "completion", "message", "stream", "playground", "model"]):
            chat_like.append(e)
            req = e["request"]
            res = e["response"]
            print(f"\n--- [{res['status']}] {req['method']} {req['url']}")
            # Print interesting headers
            for h in req.get("headers", []):
                if h["name"].lower() in ["cookie", "authorization", "x-csrf-token", "content-type", "x-statsig-id"]:
                    val = h["value"]
                    if len(val) > 200:
                        val = val[:200] + "...(truncated)"
                    print(f"    REQ HDR {h['name']}: {val}")
            # Print body
            body = req.get("postData", {}).get("text", "")
            if body:
                if len(body) > 2000:
                    print(f"    REQ BODY ({len(body)} chars): {body[:2000]}...(truncated)")
                else:
                    print(f"    REQ BODY: {body}")
            # Print response (text content for streaming)
            mime = res.get("content", {}).get("mimeType", "")
            text = res.get("content", {}).get("text", "")
            if text:
                if len(text) > 2000:
                    print(f"    RES ({mime}, {len(text)} chars): {text[:2000]}...(truncated)")
                else:
                    print(f"    RES ({mime}): {text}")
            else:
                print(f"    RES ({mime}): (no body / size={res.get('content',{}).get('size')})")
    print(f"\nChat-like entries: {len(chat_like)}")

if __name__ == "__main__":
    main()
