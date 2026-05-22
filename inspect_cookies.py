#!/usr/bin/env python3
"""Inspect cookies for /v1/responses requests AND find the available models."""
import json

HAR_FILE = r"D:\Desktop\consolex\console.x.ai.har"

with open(HAR_FILE, "r", encoding="utf-8") as f:
    har = json.load(f)

entries = har["log"]["entries"]

print("=" * 80)
print("ALL Cookie names sent on /v1/responses requests:")
print("=" * 80)
for i, e in enumerate(entries):
    if "/v1/responses" not in e["request"]["url"]:
        continue
    req = e["request"]
    print(f"\n--- Request #{i} ---")
    cookies = req.get("cookies", [])
    print(f"Parsed cookies count: {len(cookies)}")
    for c in cookies:
        val = c.get("value", "")
        print(f"  {c['name']} = {val[:80]}{'...' if len(val) > 80 else ''}")
    # Also check raw headers for cookie field
    for h in req.get("headers", []):
        if h["name"].lower() == "cookie":
            print(f"  RAW cookie header (len={len(h['value'])}): {h['value'][:300]}...")

print("\n" + "=" * 80)
print("Cookie names anywhere in the HAR (on x.ai domains):")
print("=" * 80)
all_cookies = {}
for e in entries:
    url = e["request"]["url"]
    if "x.ai" not in url:
        continue
    for c in e["request"].get("cookies", []):
        name = c["name"]
        if name not in all_cookies:
            all_cookies[name] = c["value"][:100]
for name, sample in sorted(all_cookies.items()):
    print(f"  {name} = {sample}")

print("\n" + "=" * 80)
print("Set-Cookie responses (login/session cookies):")
print("=" * 80)
for e in entries:
    url = e["request"]["url"]
    if "x.ai" not in url:
        continue
    for c in e["response"].get("cookies", []):
        print(f"  [{url[:60]}...] {c['name']} = {c.get('value','')[:80]}")

print("\n" + "=" * 80)
print("Looking for cookie names: auth, session, token in request headers:")
print("=" * 80)
seen_headers = set()
for e in entries[:20]:
    for h in e["request"].get("headers", []):
        if h["name"].lower() in seen_headers:
            continue
        seen_headers.add(h["name"].lower())
        if any(k in h["name"].lower() for k in ["cookie", "auth", "token", "session", "csrf"]):
            val = h["value"]
            print(f"  {h['name']}: {val[:300]}{'...' if len(val) > 300 else ''}")
