"""Usage data providers for the panel dashboard sidebar.

Providers prefer SSO / local session data, and optionally use API keys where
SSO is not available (OpenAI).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Rough per-tier weekly message estimates for Claude subscription tiers.
# These are conservative/approximate; users can still see raw counts when unknown.
_CLAUDE_TIER_WEEKLY_LIMITS: dict[str, int] = {
    "default_claude_pro": 1500,
    "default_claude_max_5x": 7500,
    "default_claude_max_20x": 30000,
    "default_claude_team": 10000,
    "default_claude_enterprise": 50000,
}


@dataclass(frozen=True)
class UsageStats:
    """Usage statistics for a single provider within a time window."""

    provider: str
    display_name: str
    window_days: int = 7
    messages: int = 0
    sessions: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    limit: int | None = None
    # Seconds until the window reset (rolling: time until oldest message ages out).
    time_remaining_seconds: int | None = None
    # Seconds for the full window (e.g. 7 * 86400 for weekly).
    window_total_seconds: int | None = None
    # Subscription / plan tier label for display.
    tier: str | None = None
    status: str = "ok"  # ok, warning, critical, unknown, unconfigured, empty
    error: str | None = None
    # Free-form note shown under the progress bar (e.g. data source).
    note: str | None = None

    @property
    def usage_fraction(self) -> float | None:
        """Return usage as a fraction of the limit, or None if no limit set."""
        if self.limit is None or self.limit <= 0:
            return None
        return min(1.0, self.messages / self.limit)

    @property
    def time_elapsed_fraction(self) -> float | None:
        """Fraction of the time window that has elapsed (0 = fresh, 1 = about to reset)."""
        if self.time_remaining_seconds is None or self.window_total_seconds is None:
            return None
        if self.window_total_seconds <= 0:
            return None
        elapsed = self.window_total_seconds - self.time_remaining_seconds
        return max(0.0, min(1.0, elapsed / self.window_total_seconds))


@dataclass
class _ClaudeSessionAggregate:
    sessions: int = 0
    messages: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    oldest_in_window: datetime | None = None
    timestamps: list[datetime] = field(default_factory=list)
    source: str = "session-meta"


def _read_claude_sessions(window_days: int = 7) -> _ClaudeSessionAggregate:
    """Aggregate session-meta files from the last N days, tracking oldest message."""
    agg = _ClaudeSessionAggregate()
    meta_dir = Path.home() / ".claude" / "usage-data" / "session-meta"
    if not meta_dir.is_dir():
        return agg

    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    for path in meta_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            start = data.get("start_time", "")
            if not start:
                continue
            ts = datetime.fromisoformat(start.replace("Z", "+00:00"))
            if ts < cutoff:
                continue
            agg.sessions += 1
            agg.messages += data.get("user_message_count", 0) + data.get(
                "assistant_message_count", 0
            )
            agg.tool_calls += sum(data.get("tool_counts", {}).values())
            agg.input_tokens += data.get("input_tokens", 0) or 0
            agg.output_tokens += data.get("output_tokens", 0) or 0
            agg.timestamps.append(ts)
            if agg.oldest_in_window is None or ts < agg.oldest_in_window:
                agg.oldest_in_window = ts
        except (json.JSONDecodeError, OSError, ValueError, KeyError):
            continue

    return agg


def _read_claude_stats_cache(window_days: int = 7) -> _ClaudeSessionAggregate:
    """Fallback: aggregate ~/.claude/stats-cache.json dailyActivity for the window."""
    agg = _ClaudeSessionAggregate(source="stats-cache")
    cache_path = Path.home() / ".claude" / "stats-cache.json"
    if not cache_path.is_file():
        return agg

    try:
        data = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return agg

    today = datetime.now(UTC).date()
    cutoff = today - timedelta(days=window_days)
    oldest_day: date | None = None

    for entry in data.get("dailyActivity", []):
        try:
            day = date.fromisoformat(entry.get("date", ""))
        except (ValueError, TypeError):
            continue
        if day < cutoff or day > today:
            continue
        agg.sessions += int(entry.get("sessionCount", 0) or 0)
        agg.messages += int(entry.get("messageCount", 0) or 0)
        agg.tool_calls += int(entry.get("toolCallCount", 0) or 0)
        if oldest_day is None or day < oldest_day:
            oldest_day = day

    if oldest_day is not None:
        agg.oldest_in_window = datetime.combine(
            oldest_day, datetime.min.time(), tzinfo=UTC
        )
    return agg


def _read_claude_subscription() -> dict[str, str | None]:
    """Read Claude subscription type and tier from the SSO credentials file."""
    cred_path = Path.home() / ".claude" / ".credentials.json"
    try:
        data = json.loads(cred_path.read_text())
        oauth = data.get("claudeAiOauth", {})
        return {
            "subscription": oauth.get("subscriptionType"),
            "tier": oauth.get("rateLimitTier"),
        }
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
        return {"subscription": None, "tier": None}


def fetch_claude_code_usage(
    window_days: int = 7,
    limit: int | None = None,
) -> UsageStats:
    """Claude Code activity from local session-meta (or stats-cache fallback)."""
    try:
        agg = _read_claude_sessions(window_days)
        if agg.messages == 0 and agg.sessions == 0:
            agg = _read_claude_stats_cache(window_days)
        sub = _read_claude_subscription()
    except Exception:
        return UsageStats(
            provider="claude_code",
            display_name="Claude Code",
            window_days=window_days,
            status="unknown",
            error="failed to read stats",
        )

    tier = sub.get("tier")
    if limit is None and tier:
        limit = _CLAUDE_TIER_WEEKLY_LIMITS.get(tier)

    window_total_seconds = window_days * 86400
    time_remaining_seconds: int | None = None
    if agg.oldest_in_window is not None:
        age = (datetime.now(UTC) - agg.oldest_in_window).total_seconds()
        time_remaining_seconds = max(0, int(window_total_seconds - age))
    else:
        time_remaining_seconds = window_total_seconds

    status = "ok"
    if agg.messages == 0 and agg.sessions == 0:
        status = "empty"
    elif limit is not None and limit > 0:
        fraction = agg.messages / limit
        if fraction >= 0.9:
            status = "critical"
        elif fraction >= 0.7:
            status = "warning"

    tier_label = None
    if sub.get("subscription"):
        tier_label = str(sub["subscription"]).title()
        if tier and "20x" in tier:
            tier_label += " 20x"
        elif tier and "5x" in tier:
            tier_label += " 5x"

    note: str | None = None
    if status == "empty":
        note = "no local activity tracked (account usage is not exposed via SSO)"
    elif agg.source == "stats-cache":
        note = "from stats-cache (session-meta empty)"

    return UsageStats(
        provider="claude_code",
        display_name="Claude Code",
        window_days=window_days,
        messages=agg.messages,
        sessions=agg.sessions,
        tool_calls=agg.tool_calls,
        input_tokens=agg.input_tokens,
        output_tokens=agg.output_tokens,
        limit=limit,
        time_remaining_seconds=time_remaining_seconds,
        window_total_seconds=window_total_seconds,
        tier=tier_label,
        status=status,
        note=note,
    )


def _gh_has_copilot() -> bool:
    """Detect Copilot availability for the authenticated gh user."""
    if shutil.which("gh") is None:
        return False
    try:
        ext = subprocess.run(
            ["gh", "extension", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if ext.returncode == 0 and "copilot" in ext.stdout.lower():
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    try:
        probe = subprocess.run(
            ["gh", "copilot", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if probe.returncode == 0 and "copilot" in probe.stdout.lower():
            return True
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        pass
    try:
        seats = subprocess.run(
            ["gh", "api", "/user/copilot_billing"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if seats.returncode == 0 and seats.stdout.strip().startswith("{"):
            return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def fetch_copilot_usage(window_days: int = 7, limit: int | None = None) -> UsageStats:
    """GitHub Copilot presence via gh CLI."""
    if shutil.which("gh") is None:
        return UsageStats(
            provider="copilot",
            display_name="Copilot",
            window_days=window_days,
            status="unconfigured",
            error="gh CLI not installed",
        )
    if not _gh_has_copilot():
        return UsageStats(
            provider="copilot",
            display_name="Copilot",
            window_days=window_days,
            status="unconfigured",
            error="no gh-copilot extension or subscription detected",
        )
    return UsageStats(
        provider="copilot",
        display_name="Copilot",
        window_days=window_days,
        status="unknown",
        tier="subscribed",
        note="per-seat usage not in public GH API",
    )


def _openai_usage_request(
    api_key: str,
    org_id: str | None,
    start_time: int,
) -> dict:
    """Call the OpenAI organization usage endpoint. Requires an admin key."""
    params = urllib.parse.urlencode(
        {
            "start_time": start_time,
            "bucket_width": "1d",
            "limit": 32,
        }
    )
    url = f"https://api.openai.com/v1/organization/usage/completions?{params}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {api_key}")
    if org_id:
        req.add_header("OpenAI-Organization", org_id)
    with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
        payload: dict = json.loads(resp.read().decode("utf-8"))
    return payload


def fetch_openai_usage(window_days: int = 7, limit: int | None = None) -> UsageStats:
    """OpenAI usage via OPENAI_API_KEY (admin key required for /organization/usage)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    org_id = os.environ.get("OPENAI_ORG_ID") or os.environ.get("OPENAI_ORGANIZATION")

    if not api_key:
        return UsageStats(
            provider="openai",
            display_name="OpenAI",
            window_days=window_days,
            status="unconfigured",
            error="set OPENAI_API_KEY (admin key) to enable",
        )

    start_time = int((datetime.now(UTC) - timedelta(days=window_days)).timestamp())
    try:
        payload = _openai_usage_request(api_key, org_id, start_time)
    except urllib.error.HTTPError as exc:
        body_tail = ""
        try:
            body_tail = exc.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        detail = f"HTTP {exc.code}"
        if body_tail:
            detail += f": {body_tail.strip()}"
        return UsageStats(
            provider="openai",
            display_name="OpenAI",
            window_days=window_days,
            status="unknown",
            error=detail,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return UsageStats(
            provider="openai",
            display_name="OpenAI",
            window_days=window_days,
            status="unknown",
            error=f"{exc.__class__.__name__}",
        )

    messages = 0
    input_tokens = 0
    output_tokens = 0
    for bucket in payload.get("data", []):
        for result in bucket.get("results", []):
            messages += int(result.get("num_model_requests", 0) or 0)
            input_tokens += int(result.get("input_tokens", 0) or 0)
            output_tokens += int(result.get("output_tokens", 0) or 0)

    window_total_seconds = window_days * 86400
    return UsageStats(
        provider="openai",
        display_name="OpenAI",
        window_days=window_days,
        messages=messages,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        limit=limit,
        window_total_seconds=window_total_seconds,
        time_remaining_seconds=window_total_seconds,
        tier=(org_id or "personal") if messages else (org_id or "personal"),
        status="ok" if messages or input_tokens or output_tokens else "empty",
        note=None if messages else "no usage in window",
    )


def fetch_all_usage(
    claude_limit: int | None = None,
    openai_limit: int | None = None,
    copilot_limit: int | None = None,
) -> list[UsageStats]:
    """Fetch usage from all providers."""
    return [
        fetch_claude_code_usage(limit=claude_limit),
        fetch_openai_usage(limit=openai_limit),
        fetch_copilot_usage(limit=copilot_limit),
    ]
