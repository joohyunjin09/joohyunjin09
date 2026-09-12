"""GitHub calendar input, validated cache, and an explicitly labelled empty layout.

Only dates, levels and aggregate daily counts are persisted. Tokens, repository
names and API error bodies never enter the generated files or logs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LEVELS = {name: i for i, name in enumerate((
    "NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"
))}
QUERY = """query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}"""


@dataclass(frozen=True)
class Day:
    date: date
    count: int
    level: int


@dataclass(frozen=True)
class Calendar:
    user: str
    as_of: date
    days: tuple[Day, ...]
    source: str  # github, cache, layout; never pretend test/layout data is live.

    @property
    def start(self) -> date:
        return self.as_of - timedelta(days=364)

    @property
    def sunday(self) -> date:
        return self.start - timedelta(days=(self.start.weekday() + 1) % 7)

    @property
    def total(self) -> int:
        return sum(day.count for day in self.days)

    @property
    def seed(self) -> int:
        # Stable across machines and across live/cache reads of the same data.
        return int.from_bytes(hashlib.sha256(self.serialize().encode()).digest()[:8], "big")

    def position(self, day: Day) -> tuple[int, int]:
        return divmod((day.date - self.sunday).days, 7)

    def serialize(self) -> str:
        return json.dumps({
            "version": 1, "user": self.user, "as_of": self.as_of.isoformat(),
            "days": [[d.date.isoformat(), d.count, d.level] for d in self.days],
        }, ensure_ascii=False, separators=(",", ":")) + "\n"


def valid_user(user: str) -> str:
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", user):
        raise ValueError("Expected a GitHub username, not a URL or shell expression")
    return user


def make_calendar(user: str, as_of: date, rows: list, source: str) -> Calendar:
    """Require a complete 365-day window; missing data is not silently zeroed."""
    valid_user(user)
    if source not in {"github", "cache", "layout"}:
        raise ValueError("Invalid calendar source")
    if not isinstance(rows, list) or len(rows) != 365:
        raise ValueError("Calendar must contain exactly 365 days")
    days = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) != 3:
            raise ValueError("Invalid contribution row")
        stamp, count, level = row
        if not isinstance(stamp, str):
            raise ValueError("Invalid contribution date")
        stamp_date = date.fromisoformat(stamp)
        if type(count) is not int or not 0 <= count <= 1_000_000:
            raise ValueError("Invalid contribution count")
        if type(level) is not int or not 0 <= level <= 4:
            raise ValueError("Invalid contribution level")
        if (count == 0) != (level == 0):
            raise ValueError("Contribution count and level disagree")
        days.append(Day(stamp_date, count, level))
    days.sort(key=lambda day: day.date)
    start = as_of - timedelta(days=364)
    if [d.date for d in days] != [start + timedelta(days=i) for i in range(365)]:
        raise ValueError("Calendar contains missing, duplicate, future or out-of-window dates")
    return Calendar(user, as_of, tuple(days), source)


def empty_layout(user: str, as_of: date) -> Calendar:
    start = as_of - timedelta(days=364)
    return make_calendar(user, as_of, [
        [(start + timedelta(days=i)).isoformat(), 0, 0] for i in range(365)
    ], "layout")


def from_graphql(payload: dict, user: str, as_of: date) -> Calendar:
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("GitHub GraphQL returned an error")
    try:
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        rows = [[day["date"], day["contributionCount"], LEVELS[day["contributionLevel"]]]
                for week in weeks for day in week["contributionDays"]]
    except (TypeError, KeyError) as exc:
        raise ValueError("GitHub calendar schema is missing required fields") from exc
    start = as_of - timedelta(days=364)
    # Some API calendars include week-padding days outside the requested range.
    rows = [row for row in rows if start <= date.fromisoformat(row[0]) <= as_of]
    return make_calendar(user, as_of, rows, "github")


def fetch_calendar(user: str, as_of: date, token: str) -> Calendar:
    valid_user(user)
    start = as_of - timedelta(days=364)
    now = datetime.now(timezone.utc)
    if as_of > now.date():
        raise ValueError("Cannot fetch a future contribution snapshot")
    to = now.isoformat() if as_of == now.date() else f"{as_of}T23:59:59Z"
    body = json.dumps({"query": QUERY, "variables": {
        "login": user, "from": f"{start}T00:00:00Z", "to": to
    }}).encode()
    request = Request("https://api.github.com/graphql", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/vnd.github+json", "User-Agent": "slugcat-profile-generator/1"
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("Calendar response is too large")
            return from_graphql(json.loads(raw), user, as_of)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"GitHub calendar request failed (HTTP {exc.code})") from None
        except (URLError, TimeoutError, OSError):
            if attempt == 2:
                raise RuntimeError("GitHub calendar connection failed") from None
        time.sleep(1 + attempt)
    raise RuntimeError("Calendar retry budget exhausted")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def load_calendar(user: str, as_of: date, cache: Path, fetch: bool = False) -> tuple[Calendar, str]:
    """Keep the last good snapshot on an outage; explicitly report its real date."""
    valid_user(user)
    notice = ""
    if fetch:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            try:
                live = fetch_calendar(user, as_of, token)
                # The caller saves the cache only after successful rendering/tests.
                return live, ""
            except (RuntimeError, ValueError, json.JSONDecodeError):
                notice = "GitHub calendar unavailable; trying the last validated snapshot."
        else:
            notice = "No GitHub token; trying the last validated snapshot."
    if cache.is_file():
        try:
            if cache.stat().st_size > 100_000:
                raise ValueError("Cache is too large")
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data["version"] != 1 or data["user"] != user:
                raise ValueError("Cache version or owner mismatch")
            stamp = date.fromisoformat(data["as_of"])
            if stamp > as_of:
                raise ValueError("Refusing a future cache snapshot")
            return make_calendar(user, stamp, data["days"], "cache"), notice
        except (ValueError, KeyError, TypeError, OSError):
            notice = "No usable calendar snapshot; rendering labelled layout-only terrain."
    return empty_layout(user, as_of), notice or "No calendar snapshot; rendering labelled layout-only terrain."
