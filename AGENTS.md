# Repository Guidelines

## Project Structure & Module Organization
This repository is a script-first Python workspace for analyzing `console.x.ai` traffic captures.

- Core analyzers: `parse_har.py`, `inspect_cookies.py`, `extract_v1_responses.py`
- Connectivity checks: `smoke_test.py`, `smoke_test2.py`, `smoke_test3.py`
- Input artifacts: `console.x.ai.har`, `cookies_console_x_ai.json`
- Generated reports: `har_analysis.txt`, `v1_responses_dump.txt`

Keep new analysis utilities as single-purpose scripts in the repository root unless a clear module split is introduced.

## Build, Test, and Development Commands
Use Python 3.10+ in the project directory:

- `python parse_har.py`: filters HAR entries and prints chat/completion-like requests.
- `python inspect_cookies.py`: inspects request/response cookies in HAR traffic.
- `python extract_v1_responses.py`: dumps full `/v1/responses` request/response details.
- `python smoke_test.py`: basic POST smoke test using `urllib`.
- `python smoke_test2.py`: Chrome-fingerprint smoke test (`curl_cffi` required).
- `python smoke_test3.py`: proxy + `sso` cookie smoke test.
- `python -m py_compile *.py`: quick syntax validation before commit.

## Coding Style & Naming Conventions
Follow standard Python style:

- 4-space indentation, UTF-8, and module-level docstrings.
- `snake_case` for files, functions, and variables.
- Keep scripts deterministic and explicit about constants (URLs, file paths, model IDs).
- Prefer short, focused functions over large inline blocks.

## Testing Guidelines
There is no formal test framework yet; use smoke scripts as functional checks.

- Name exploratory tests as `smoke_test*.py`.
- Verify HTTP status, headers, and first streamed chunks.
- When changing request payloads or headers, rerun at least one smoke test and one parser script.

## Commit & Pull Request Guidelines
This directory currently has no visible Git metadata/history, so use Conventional Commits going forward:

- `feat: add model filter to parse_har`
- `fix: handle missing cookie fields in smoke_test2`

PRs should include a concise summary, changed files, commands run, and redacted output snippets when network calls are involved.

## Security & Configuration Tips
HAR and cookie files may contain credentials/session data.

- Never commit raw secrets or full cookie values.
- Redact tokens in shared logs.
- Prefer environment variables for sensitive overrides (proxy, cookie file path, endpoint).
