"""SSO-only account pool for upstream requests."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RETRYABLE_STATUS_CODES = {401, 403, 408, 409, 425, 429, 500, 502, 503, 504}
NON_SELECTABLE_STATUSES = {"disabled", "cooling", "invalid", "expired", "failed"}
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


def _normalize_sso(sso: str) -> str:
    token = (sso or "").strip()
    return token[4:] if token.startswith("sso=") else token


def referer_from_team_id(team_id: str) -> str:
    team = (team_id or "").strip()
    if not team:
        return ""
    return f"https://console.x.ai/team/{team}/chat-playground"


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS_CODES


def status_from_result(status_code: int | None) -> str:
    if status_code is not None and status_code < 400:
        return "active"
    if status_code in {401, 403}:
        return "invalid"
    if status_code == 429:
        return "cooling"
    return "failed"


def _is_sqlite_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SQLITE_SUFFIXES


def _connect_sqlite(path: str | Path) -> sqlite3.Connection:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(file_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            sso TEXT NOT NULL,
            team_id TEXT NOT NULL DEFAULT '',
            referer TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            last_checked_at REAL NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            use_count INTEGER NOT NULL DEFAULT 0,
            fail_count INTEGER NOT NULL DEFAULT 0,
            last_used_at REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_sso_team ON accounts(sso, team_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            sso TEXT NOT NULL DEFAULT '',
            team_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            status_code INTEGER,
            error TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'request'
        )
        """
    )
    return conn


def _normalize_record(item: dict[str, Any], idx: int) -> dict[str, Any] | None:
    sso = str(item.get("sso", "")).strip()
    if not sso:
        return None
    team_id = str(item.get("team_id", "")).strip()
    return {
        "name": str(item.get("name") or idx + 1),
        "sso": sso,
        "team_id": team_id,
        "referer": str(item.get("referer", "")).strip() or referer_from_team_id(team_id),
        "status": str(item.get("status", "pending")).strip() or "pending",
        "last_checked_at": float(item.get("last_checked_at", 0) or 0),
        "last_error": str(item.get("last_error", "")).strip(),
        "use_count": int(item.get("use_count", 0) or 0),
        "fail_count": int(item.get("fail_count", 0) or 0),
        "last_used_at": float(item.get("last_used_at", 0) or 0),
    }


def load_account_records(path: str) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not path:
        return []
    if _is_sqlite_path(file_path):
        if not file_path.exists():
            legacy_json = file_path.with_suffix(".json")
            if legacy_json.exists():
                records = load_account_records(str(legacy_json))
                if records:
                    write_account_records(str(file_path), records)
        with closing(_connect_sqlite(file_path)) as conn:
            rows = conn.execute(
                """
                SELECT name, sso, team_id, referer, status, last_checked_at, last_error,
                       use_count, fail_count, last_used_at
                FROM accounts
                ORDER BY id ASC
                """
            ).fetchall()
        records = []
        for idx, row in enumerate(rows):
            record = _normalize_record(dict(row), idx)
            if record is not None:
                records.append(record)
        return records

    if not file_path.exists():
        return []

    raw, accounts = _load_accounts_payload(file_path)
    del raw
    records = []
    for idx, item in enumerate(accounts):
        record = _normalize_record(item, idx)
        if record is not None:
            records.append(record)
    return records


def write_account_records(path: str, accounts: list[dict[str, Any]]) -> None:
    file_path = Path(path)
    records = []
    for idx, item in enumerate(accounts):
        record = _normalize_record(item, idx)
        if record is not None:
            records.append(record)

    if _is_sqlite_path(file_path):
        now = time.time()
        with closing(_connect_sqlite(file_path)) as conn:
            conn.execute("DELETE FROM accounts")
            for record in records:
                conn.execute(
                    """
                    INSERT INTO accounts (
                        name, sso, team_id, referer, status, last_checked_at, last_error,
                        use_count, fail_count, last_used_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["name"],
                        _normalize_sso(record["sso"]),
                        record["team_id"],
                        record["referer"],
                        record["status"],
                        record["last_checked_at"],
                        record["last_error"],
                        record["use_count"],
                        record["fail_count"],
                        record["last_used_at"],
                        now,
                        now,
                    ),
                )
            conn.commit()
        return

    _write_accounts_payload(file_path, records)


def record_account_event(
    path: str,
    account: Account,
    *,
    status: str,
    status_code: int | None,
    error: str = "",
    kind: str = "request",
) -> None:
    if not path or not _is_sqlite_path(path):
        return
    with closing(_connect_sqlite(path)) as conn:
        conn.execute(
            """
            INSERT INTO account_events (ts, name, sso, team_id, status, status_code, error, kind)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                account.name,
                _normalize_sso(account.sso),
                account.team_id,
                status,
                status_code,
                str(error or "")[:2000],
                kind,
            ),
        )
        conn.commit()


def load_account_events(path: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if not path or not _is_sqlite_path(path) or not Path(path).exists():
        return []
    with closing(_connect_sqlite(path)) as conn:
        rows = conn.execute(
            """
            SELECT ts, name, sso, team_id, status, status_code, error, kind
            FROM account_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


@dataclass(frozen=True)
class Account:
    name: str
    sso: str
    team_id: str = ""
    referer: str = ""
    status: str = "pending"
    last_checked_at: float = 0.0
    last_error: str = ""
    use_count: int = 0
    fail_count: int = 0
    last_used_at: float = 0.0

    @property
    def is_selectable(self) -> bool:
        return self.status.strip().lower() not in NON_SELECTABLE_STATUSES

    @property
    def cookie_header(self) -> str:
        token = _normalize_sso(self.sso)
        cookie = f"sso={token}; sso-rw={token}"
        team_id = self.team_id.strip()
        if team_id:
            cookie += f"; last-team-id={team_id}"
        return cookie


class AccountPool:
    def __init__(self, accounts: list[Account]) -> None:
        self.accounts = accounts
        self.selectable_accounts = [account for account in accounts if account.is_selectable]
        self._index = 0
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path: str, *, fallback_sso: str = "") -> "AccountPool":
        accounts: list[Account] = []
        for item in load_account_records(path):
            accounts.append(
                Account(
                    name=str(item["name"]),
                    sso=str(item["sso"]),
                    team_id=str(item["team_id"]),
                    referer=str(item["referer"]),
                    status=str(item["status"]),
                    last_checked_at=float(item["last_checked_at"]),
                    last_error=str(item["last_error"]),
                    use_count=int(item["use_count"]),
                    fail_count=int(item["fail_count"]),
                    last_used_at=float(item["last_used_at"]),
                )
            )
        if not accounts and fallback_sso.strip():
            accounts.append(Account(name="env", sso=fallback_sso.strip()))
        return cls(accounts)

    def __len__(self) -> int:
        return len(self.selectable_accounts)

    def next_account(self) -> Account:
        if not self.selectable_accounts:
            if self.accounts:
                raise RuntimeError("No selectable upstream SSO accounts configured")
            raise RuntimeError("No upstream SSO accounts configured")
        with self._lock:
            account = self.selectable_accounts[self._index % len(self.selectable_accounts)]
            self._index += 1
        return account


def _load_accounts_payload(path: Path) -> tuple[Any, list[dict[str, Any]]]:
    if not path.exists():
        return [], []
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(raw, dict):
        accounts = raw.get("accounts", [])
    else:
        accounts = raw
    if not isinstance(accounts, list):
        return raw, []
    return raw, [item for item in accounts if isinstance(item, dict)]


def _write_accounts_payload(path: Path, raw: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _same_account(item: dict[str, Any], account: Account) -> bool:
    if _normalize_sso(str(item.get("sso", ""))) != _normalize_sso(account.sso):
        return False
    item_team = str(item.get("team_id", "")).strip()
    account_team = account.team_id.strip()
    return item_team == account_team


def record_account_result(
    path: str,
    account: Account,
    *,
    status_code: int | None,
    error: str = "",
) -> bool:
    file_path = Path(path)
    if not path or not file_path.exists():
        return False

    accounts = load_account_records(path)
    now = time.time()
    changed = False
    success = status_code is not None and status_code < 400
    for item in accounts:
        if not _same_account(item, account):
            continue
        item["status"] = status_from_result(status_code)
        item["last_checked_at"] = now
        if success:
            item["last_error"] = ""
            item["last_used_at"] = now
            item["use_count"] = int(item.get("use_count", 0) or 0) + 1
        else:
            item["last_error"] = str(error or "")
            item["fail_count"] = int(item.get("fail_count", 0) or 0) + 1
        changed = True
        break

    if changed:
        write_account_records(path, accounts)
        record_account_event(
            path,
            account,
            status=status_from_result(status_code),
            status_code=status_code,
            error=error,
            kind="request",
        )
    return changed


__all__ = [
    "Account",
    "AccountPool",
    "is_retryable_status",
    "load_account_events",
    "load_account_records",
    "record_account_event",
    "record_account_result",
    "referer_from_team_id",
    "status_from_result",
    "write_account_records",
]
