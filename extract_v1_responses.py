#!/usr/bin/env python3
"""Extract the 4 /v1/responses requests in full detail."""
import json

HAR_FILE = r"D:\Desktop\consolex\console.x.ai.har"

with open(HAR_FILE, "r", encoding="utf-8") as f:
    har = json.load(f)

entries = har["log"]["entries"]
target_entries = [e for e in entries if "/v1/responses" in e["request"]["url"]]

out = []
out.append(f"Found {len(target_entries)} /v1/responses entries\n")
out.append("=" * 80)

for i, e in enumerate(target_entries):
    req = e["request"]
    res = e["response"]
    out.append(f"\n\n### REQUEST #{i+1}: {req['method']} {req['url']}")
    out.append(f"Started: {e['startedDateTime']}")
    out.append(f"Status: {res['status']}")
    out.append("\n--- Request Headers ---")
    for h in req.get("headers", []):
        out.append(f"  {h['name']}: {h['value']}")
    out.append("\n--- Request Cookies (parsed) ---")
    for c in req.get("cookies", []):
        out.append(f"  {c['name']}={c['value']}")
    out.append("\n--- Request Body ---")
    body = req.get("postData", {}).get("text", "")
    if body:
        out.append(body)
    else:
        out.append("(empty)")
    out.append("\n--- Response Headers ---")
    for h in res.get("headers", []):
        out.append(f"  {h['name']}: {h['value']}")
    out.append("\n--- Response Body ---")
    mime = res.get("content", {}).get("mimeType", "")
    text = res.get("content", {}).get("text", "")
    size = res.get("content", {}).get("size", 0)
    out.append(f"(mime={mime} size={size})")
    if text:
        # show first 5000 chars and last 1000
        if len(text) > 8000:
            out.append(text[:4000])
            out.append("\n...(truncated middle)...\n")
            out.append(text[-3000:])
        else:
            out.append(text)
    out.append("\n" + "=" * 80)

with open(r"D:\Desktop\consolex\v1_responses_dump.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))

print(f"Wrote dump with {len(target_entries)} entries")
