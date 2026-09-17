"""MCP server entrypoint — exposes Jira + Tempo tools to MCP clients.

Run as a stdio MCP server:
    python -m jira_tempo_mcp.server
or via the console script:
    jira-tempo-mcp
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytz
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import __version__
from .client import (
    FavoritesEndpointUnavailableError,
    JiraTempoClient,
    JiraTempoError,
    WorkerKeyResolutionError,
)
from .config import Config, load_config
from .report import generate_weekly_report
from .tasks_report import generate_tasks_report
from .team_report import generate_team_report
from .templates.loader import build_registry, resolve_template
from .utils import format_seconds_to_human, iso_now, parse_duration_to_seconds

logger = logging.getLogger("jira-tempo-mcp")

# Regex for validating Jira issue keys (m10).
_ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")

# --- Tool definitions ---

TOOLS: list[Tool] = [
    Tool(
        name="list_worklogs",
        description=(
            "List Tempo worklogs for a date range (or a single day). "
            "Returns worklogs with issue key, time spent, comment, and date. "
            "Only actually tracked time is returned — planned time is excluded."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "date_from": {
                    "type": "string",
                    "description": "Start date (ISO YYYY-MM-DD). Defaults to today.",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date (ISO YYYY-MM-DD). Defaults to date_from.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="get_worklog",
        description="Get a single Tempo worklog by its Tempo internal ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "worklog_id": {"type": "string", "description": "Tempo worklog ID"},
            },
            "required": ["worklog_id"],
        },
    ),
    Tool(
        name="create_worklog",
        description=(
            "Track (log) time on a Jira issue via Tempo. "
            "Provide issue key, duration (e.g. '1h 30m', '2h', '45m'), and optional comment. "
            "The worklog is attributed to the token owner unless author_account_id is given. "
            "On some Tempo installations, `attributes` with `_Специализация_` is **required**. "
            "If you get a VALIDATION_FAILED error, provide "
            '`attributes: {"_Специализация_": "<value>", "_Форматработы_": "<value>"}`.'
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key (e.g. PROJECT-100)",
                },
                "time_spent": {
                    "type": "string",
                    "description": "Human duration: '1h 30m', '2h', '45m', '1d 2h'",
                },
                "comment": {"type": "string", "description": "Optional worklog comment"},
                "date_started": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (e.g. 2026-06-19). Defaults to today.",
                },
                "author_account_id": {
                    "type": "string",
                    "description": "Optional Tempo worker key. Defaults to token owner.",
                },
                "attributes": {
                    "type": "object",
                    "description": 'Optional Tempo work attributes (e.g. {"_Специализация_": "Devops", "_Форматработы_": "Удаленно"}). Required on some installations.',
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["issue_key", "time_spent"],
        },
    ),
    Tool(
        name="delete_worklog",
        description="Delete a Tempo worklog by its ID. Use for undo/correction of mis-tracked time.",
        inputSchema={
            "type": "object",
            "properties": {
                "worklog_id": {"type": "string", "description": "Tempo worklog ID to delete"},
            },
            "required": ["worklog_id"],
        },
    ),
    Tool(
        name="get_issue",
        description=(
            "Get Jira issue metadata: summary, description, status, project, priority, "
            "assignee, duedate, issuetype, components."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key (e.g. PROJECT-100)",
                },
            },
            "required": ["issue_key"],
        },
    ),
    Tool(
        name="list_favorite_issues",
        description="List favorite issues for the current Jira user. Returns keys and summaries.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="generate_weekly_report",
        description=(
            "Generate a weekly work report from Tempo worklogs and save it as a file. "
            "Groups worklogs by issue, maps known issues to stable sections, and writes "
            "<prefix>_<YYYY-MM-DD>_<YYYY-MM-DD>.<fmt> to the configured output directory. "
            "Returns the path to the generated file. "
            "Since v0.2.0 a custom template can be selected via the 'template' parameter (txt only). "
            "Since v0.3.0 the 'format' parameter selects output: txt (default), md (Markdown), json."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target_date": {
                    "type": "string",
                    "description": "Any date within the target week (ISO YYYY-MM-DD). Defaults to today.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory. Defaults to REPORT_OUTPUT_DIR env or ./reports.",
                },
                "template": {
                    "type": "string",
                    "description": (
                        "Template name (e.g. 'default', 'weekly_summary'). "
                        "Defaults to REPORT_TEMPLATE env or 'default'. "
                        "Use list_report_templates to see available templates. "
                        "Only used when format='txt'."
                    ),
                },
                "format": {
                    "type": "string",
                    "enum": ["txt", "md", "json"],
                    "description": (
                        "Output format: 'txt' (plain text, default), 'md' (Markdown), 'json' (structured JSON). "
                        "File extension matches the format."
                    ),
                    "default": "txt",
                },
                "username": {
                    "type": "string",
                    "description": (
                        "Optional Jira username to generate the report for (instead of the "
                        "configured JIRA_USER). If provided, worklogs are filtered to this user."
                    ),
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="generate_team_report",
        description=(
            "Generate a team work report from Tempo worklogs for multiple Jira users. "
            "Fetches worklogs per user with bounded concurrency (rate-limit safe), "
            "renders per-user sections plus an aggregate summary, and writes "
            "team_<YYYY-MM-DD>_<YYYY-MM-DD>_<users_hash>.<fmt> to the configured output directory. "
            "Returns the file path and a short summary (per-user totals, top issues). "
            "Since v0.3.0 the 'format' parameter selects output: txt (default), md (Markdown), json."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Jira usernames to include in the team report. "
                        "If not provided, uses REPORT_TEAM_USERS env var or the current user."
                    ),
                },
                "date_from": {
                    "type": "string",
                    "description": "Start date (ISO YYYY-MM-DD). Defaults to Monday of the current week.",
                },
                "date_to": {
                    "type": "string",
                    "description": "End date (ISO YYYY-MM-DD). Defaults to Friday of the current week.",
                },
                "section_map": {
                    "type": "object",
                    "description": "Optional override for REPORT_SECTION_MAP (issue key -> section title).",
                },
                "template": {
                    "type": "string",
                    "description": "Template name. Defaults to 'team_report'. Only used when format='txt'.",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory. Defaults to REPORT_TEAM_OUTPUT_DIR or REPORT_OUTPUT_DIR.",
                },
                "format": {
                    "type": "string",
                    "enum": ["txt", "md", "json"],
                    "description": (
                        "Output format: 'txt' (plain text, default), 'md' (Markdown), 'json' (structured JSON). "
                        "File extension matches the format."
                    ),
                    "default": "txt",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="list_report_templates",
        description=(
            "List available report templates (builtin + custom). "
            "Returns each template's name and description. "
            "Custom templates are discovered from REPORT_TEMPLATE_DIR."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="preview_report_template",
        description=(
            "Preview a report template rendered with sample data. "
            "Useful for exploring templates before generating a real report. "
            "Returns the rendered text without writing a file. "
            "Does NOT call Jira/Tempo — uses built-in mock worklogs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "template_name": {
                    "type": "string",
                    "description": (
                        "Name of the template to preview "
                        "(use list_report_templates to see available names)."
                    ),
                },
                "sample_data": {
                    "type": "string",
                    "enum": ["default", "minimal", "empty"],
                    "description": (
                        "Preset sample-data profile: 'default' = realistic worklogs "
                        "(several issues, varied times), 'minimal' = a single worklog, "
                        "'empty' = no worklogs (tests empty-state rendering). "
                        "Defaults to 'default'."
                    ),
                    "default": "default",
                },
            },
            "required": ["template_name"],
        },
    ),
    Tool(
        name="search_users",
        description=(
            "Search Jira users by name, surname, username, or email fragment. "
            "Returns a list of matching users with name, key, displayName, "
            "emailAddress, and active status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — name, surname, or username fragment.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of users to return. Defaults to 10.",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="list_user_tasks",
        description=(
            "Get tasks assigned to a Jira user with status, due date, summary, "
            "priority, issue type, project, and recent comments (last 3). "
            "Returns up to 100 tasks ordered by last updated."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "username": {
                    "type": "string",
                    "description": "Jira username (e.g. 'golikhin').",
                },
                "status_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of status names to filter by.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of tasks to return. Defaults to 100.",
                    "default": 100,
                },
            },
            "required": ["username"],
        },
    ),
    Tool(
        name="list_issues_by_jql",
        description=(
            "Search Jira issues by JQL query (read-only). "
            "Returns a formatted list of issues with key, summary, status, priority, "
            "duedate, assignee, issuetype, and project. Max 100 results. "
            "Set include_description=true to also return each issue's description."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "jql": {
                    "type": "string",
                    "description": "JQL query string (e.g. 'project = DEVOPS AND assignee = golikhin ORDER BY updated DESC').",
                },
                "fields": {
                    "type": "string",
                    "description": (
                        "Comma-separated field names to return. "
                        "Defaults to 'summary,status,priority,duedate,assignee,issuetype,project,created,updated'."
                    ),
                    "default": "summary,status,priority,duedate,assignee,issuetype,project,created,updated",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results. Defaults to 50. Capped at 100.",
                    "default": 50,
                },
                "include_description": {
                    "type": "boolean",
                    "description": (
                        "Also return each issue's description. "
                        "Defaults to false to keep list responses compact."
                    ),
                    "default": False,
                },
            },
            "required": ["jql"],
        },
    ),
    Tool(
        name="get_current_user",
        description=(
            "Get info about the authenticated user (PAT owner). "
            "Returns username, display name, email, key, and active status."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="generate_tasks_report",
        description=(
            "Generate a report of user tasks grouped by status and save it as a file. "
            "For a single user: all tasks with full details (summary, due date, priority, comments). "
            "For multiple users: only active tasks (status category 'In Progress'), grouped by user then status. "
            "Returns the path to the generated file. "
            "Since v0.3.0 the 'format' parameter selects output: md (Markdown, default), txt (plain text), json."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "users": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Jira usernames to include in the report. "
                        "If not provided, uses REPORT_TEAM_USERS env var or the current user."
                    ),
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Only include active tasks. Forced True for multiple users.",
                    "default": False,
                },
                "output_dir": {
                    "type": "string",
                    "description": "Output directory. Defaults to REPORT_OUTPUT_DIR env or ./reports.",
                },
                "format": {
                    "type": "string",
                    "enum": ["md", "txt", "json"],
                    "description": (
                        "Output format: 'md' (Markdown, default), 'txt' (plain text), 'json' (structured JSON). "
                        "File extension matches the format."
                    ),
                    "default": "md",
                },
            },
            "required": [],
        },
    ),
]


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def _json_safe(obj: Any) -> Any:
    """Make any object JSON-serializable for MCP output."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return str(obj)


def _validate_issue_key(key: str) -> str:
    """Validate Jira issue key format. Raises ValueError if invalid."""
    if not _ISSUE_KEY_RE.match(key):
        raise ValueError(
            f"Invalid issue key {key!r}. Expected format: PROJECT-NUMBER (e.g. PROJECT-100)."
        )
    return key


def _validate_date(date_str: str, field_name: str) -> date:
    """Parse and validate an ISO date string. Raises ValueError if invalid."""
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise ValueError(
            f"Invalid date for {field_name}: {date_str!r}. Expected ISO format YYYY-MM-DD."
        ) from None


# Matches a numeric timezone offset WITHOUT a colon at end of string,
# e.g. "...+0300" or "...-0500". Used to normalise such offsets so that
# datetime.fromisoformat accepts them (it requires "+03:00").
_TZ_OFFSET_NO_COLON_RE = re.compile(r"([+-]\d{2})(\d{2})$")


def _parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime tolerantly.

    Handles variants that ``datetime.fromisoformat`` rejects on Python 3.11:
    a numeric offset without a colon (``+0300``) and a trailing ``Z``.
    Microseconds (``.000``) are already accepted on 3.11+.

    Raises :class:`ValueError` with an actionable message if the value
    cannot be parsed by any known shape.
    """
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    # Insert the colon a numeric offset lacks: "+0300" -> "+03:00".
    normalized = _TZ_OFFSET_NO_COLON_RE.sub(r"\1:\2", normalized)
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Could not parse date_started {value!r}: expected ISO-8601 "
            f"(e.g. '2026-06-19T10:00:00+03:00'). Details: {exc}"
        ) from exc


def _user_friendly_error(exc: Exception) -> str:
    """Map known exception types to user-friendly messages (m11)."""
    if isinstance(exc, WorkerKeyResolutionError):
        return f"Could not identify your Tempo worker key: {exc}. Check JIRA_USER or Tempo connectivity."
    if isinstance(exc, JiraTempoError):
        return f"Jira/Tempo API error: {exc}"
    if isinstance(exc, ValueError):
        return f"Invalid input: {exc}"
    if isinstance(exc, KeyError):
        return f"Missing required argument: {exc}"
    # Unexpected errors are NOT input-validation problems — they are likely
    # bugs in the MCP server. Signal this explicitly so the user does not
    # mistake an internal failure for bad input and retry the same call.
    return (
        f"[unexpected] {exc.__class__.__name__}: this is likely a bug in the "
        f"MCP server, not invalid input. Enable DEBUG logging (LOG_LEVEL=DEBUG) "
        f"for the full traceback."
    )


def _validate_output_dir(raw_dir: str, config: Config, *, team: bool = False) -> Path:
    """Validate an ``output_dir`` argument against path traversal.

    Resolves ``raw_dir`` and checks that the result lies **inside** the
    allowed report root: ``config.team_output_dir`` when ``team=True``,
    ``config.report_output_dir`` otherwise, falling back to
    ``~/.mcp/jira-tempo-mcp/reports``. Any path that resolves outside the
    root (e.g. ``../../etc``, absolute ``/tmp`` escapes, symlink chains) is
    rejected with a ``ValueError``.

    This containment check is the defence against an MCP caller writing
    reports (or overwriting files) in arbitrary locations on the host.
    The traversal-rejection path is covered by
    ``tests/test_security.py``.
    """
    resolved = Path(raw_dir).resolve()
    root = (config.team_output_dir if team else config.report_output_dir) or str(
        Path.home() / ".mcp" / "jira-tempo-mcp" / "reports"
    )
    allowed_root = Path(root).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError:
        raise ValueError(
            f"output_dir {raw_dir!r} resolves outside the allowed root {allowed_root}. "
            f"Path traversal is not permitted."
        ) from None
    return resolved


# --- Worklog formatting helper (UX-4, UX-10) ---


def _format_worklog_details(wl: dict[str, Any], indent: str = "  ") -> str:
    """Format a Tempo worklog dict as readable key/value lines (UX-4)."""
    wl_id = wl.get("tempoWorklogId") or wl.get("id") or wl.get("worklogId") or "?"
    seconds = wl.get("timeSpentSeconds", 0)
    issue = wl.get("issue")
    issue_key = "?"
    issue_summary = ""
    if isinstance(issue, dict):
        issue_key = issue.get("key", "?")
        issue_summary = issue.get("summary", "") or ""
    status = ""
    if isinstance(issue, dict):
        status_obj = issue.get("status", {})
        status = status_obj.get("name", "") if isinstance(status_obj, dict) else ""
    project = ""
    if isinstance(issue, dict):
        project_obj = issue.get("project", {})
        project = project_obj.get("key", "") if isinstance(project_obj, dict) else ""
    comment = wl.get("comment", "") or ""
    if isinstance(comment, dict):
        comment = comment.get("content", "") or ""
    started = wl.get("started") or wl.get("startDate") or ""
    created = wl.get("createdAt") or wl.get("created") or ""
    updated = wl.get("updatedAt") or wl.get("updated") or ""
    worker = wl.get("worker") or wl.get("workerKey") or ""
    location = ""
    loc_obj = wl.get("location")
    if isinstance(loc_obj, dict):
        location = loc_obj.get("name", "") or loc_obj.get("displayName", "") or ""
    elif isinstance(loc_obj, str):
        location = loc_obj

    lines = [f"Worklog {wl_id}:"]
    lines.append(f"{indent}Time spent: {format_seconds_to_human(int(seconds) or 0)} ({seconds}s)")
    issue_line = f"{indent}Issue: {issue_key}"
    if issue_summary:
        issue_line += f" — {issue_summary}"
    lines.append(issue_line)
    if status:
        lines.append(f"{indent}Status: {status}")
    if project:
        lines.append(f"{indent}Project: {project}")
    lines.append(f"{indent}Comment: {comment or '(none)'}")
    lines.append(f"{indent}Started: {started or '—'}")
    if created:
        lines.append(f"{indent}Created: {created}")
    if updated:
        lines.append(f"{indent}Updated: {updated}")
    if worker:
        lines.append(f"{indent}Worker: {worker}")
    if location:
        lines.append(f"{indent}Location: {location}")
    # Attributes (Tempo work attributes).
    attrs = wl.get("attributes")
    if isinstance(attrs, dict) and attrs:
        lines.append(f"{indent}Attributes:")
        for ak, av in attrs.items():
            # Tempo attribute values are {"value": "..."} or plain strings.
            val = av.get("value", "") or av.get("key", "") if isinstance(av, dict) else str(av)
            # Strip leading/trailing underscores from key for display.
            display_key = ak.strip("_")
            lines.append(f"{indent}  {display_key}: {val}")
    return "\n".join(lines)


# --- Tool handlers (m3: dispatch table) ---


async def _handle_list_worklogs(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    tz = pytz.timezone(config.timezone)
    today = datetime.now(tz).date()
    date_from = arguments.get("date_from") or today.isoformat()
    date_to = arguments.get("date_to") or date_from

    # BUG-3: validate date formats before API calls.
    parsed_from = _validate_date(date_from, "date_from")
    parsed_to = _validate_date(date_to, "date_to") if date_to != date_from else parsed_from
    # BUG-4: validate date_from <= date_to.
    if parsed_from > parsed_to:
        raise ValueError("date_from must be on or before date_to.")

    wk = await client.find_worker_key(config.jira_user)
    worker_keys = [wk]
    worklogs = await client.search_worklogs(date_from, date_to, worker_keys=worker_keys)

    rows = []
    for wl in worklogs:
        # m1: safe extraction with isinstance guard.
        key = wl.get("issueKey")
        if not key:
            issue = wl.get("issue")
            key = issue.get("key", "?") if isinstance(issue, dict) else "?"
        seconds = wl.get("timeSpentSeconds", 0)
        comment = wl.get("comment", "") or ""
        if isinstance(comment, dict):
            comment = comment.get("content", "")
        started = wl.get("started") or wl.get("startDate") or ""
        # m2: explicit fallback to "?" if all lookups return falsy.
        wl_id = wl.get("tempoWorklogId") or wl.get("id") or wl.get("worklogId") or "?"
        rows.append(
            f"- {started} | {key} | {format_seconds_to_human(seconds)} | id={wl_id}"
            + (f" | {comment}" if comment else "")
        )
    header = f"Worklogs {date_from} .. {date_to} ({len(worklogs)} entries):\n"
    return header + "\n".join(rows) if rows else header + "(none)"


async def _handle_get_worklog(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    wl_id = arguments["worklog_id"]
    wl = await client.get_worklog(wl_id)
    # UX-4: format as structured key/value, not raw dict repr.
    return _format_worklog_details(wl)


async def _handle_create_worklog(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    issue_key = _validate_issue_key(arguments["issue_key"])
    time_spent = arguments["time_spent"]
    seconds = parse_duration_to_seconds(time_spent)
    date_started = arguments.get("date_started") or iso_now(config.timezone)
    # Bug 1: Tempo API expects YYYY-MM-DD, not full ISO datetime.
    # Tolerant parse: handles "+0300" (no colon), trailing Z, and microseconds —
    # all shapes Jira/MCP clients send in practice (finding #22).
    if "T" in date_started:
        dt = _parse_iso_datetime(date_started)
        date_started = dt.strftime("%Y-%m-%d")
    comment = arguments.get("comment", "")
    # Bug 2: resolve worker key when author_account_id not provided.
    author = arguments.get("author_account_id")
    if not author:
        author = await client.find_worker_key(config.jira_user)
    # Bug 3: pass optional Tempo work attributes.
    attributes = arguments.get("attributes")
    try:
        result = await client.create_worklog(
            issue_key=issue_key,
            time_spent_seconds=seconds,
            date_started=date_started,
            comment=comment,
            author_account_id=author,
            attributes=attributes,
        )
    except JiraTempoError as exc:
        # BUG-2: catch VALIDATION_FAILED and return actionable message.
        # Change 3: dynamically query Tempo work-attribute definitions to
        # produce a richer hint with keys, types, and possible values.
        status_code = getattr(exc, "status_code", None)
        body = getattr(exc, "response_body", None)
        if status_code == 400:
            # Try to fetch the full attribute definitions for a richer hint.
            attr_defs: list[dict[str, Any]] = []
            # Endpoint unavailable — fall back to parsing the error body.
            with contextlib.suppress(JiraTempoError):
                attr_defs = await client.get_work_attributes()

            required_attrs = [a for a in attr_defs if a.get("required")]
            if required_attrs:
                req_lines = []
                for a in required_attrs:
                    key = a["key"]
                    name = a["name"]
                    atype = a["type"]
                    values = a.get("values", [])
                    line = f"  - {key} ({name}): required, type={atype}"
                    if values:
                        line += f", values: [{', '.join(values)}]"
                    req_lines.append(line)
                return (
                    "Worklog creation failed — Tempo requires the following work attributes:\n"
                    + "\n".join(req_lines)
                    + "\nProvide them via the 'attributes' parameter, e.g. "
                    'attributes: {"_Специализация_": "Devops", "_Форматработы_": "Удаленно"}.'
                )

            # Fallback: parse the 400 error body if attribute defs unavailable.
            if isinstance(body, dict):
                errors = body.get("errors") or {}
                if isinstance(errors, dict) and errors:
                    req_lines = [f"  - {k}: {v}" for k, v in errors.items()]
                    return (
                        "Worklog creation failed — Tempo requires the following work attributes:\n"
                        + "\n".join(req_lines)
                        + "\nProvide them via the 'attributes' parameter, e.g. "
                        'attributes: {"_Специализация_": "Devops", "_Форматработы_": "Удаленно"}.'
                    )
        raise
    wl_id = result.get("tempoWorklogId") or result.get("id", "?")
    msg = f"Tracked {format_seconds_to_human(seconds)} on {issue_key} at {date_started}. Worklog ID: {wl_id}"
    if comment:
        msg += f". Comment: {comment}"
    # UX-10: append full worklog details.
    try:
        full_wl = await client.get_worklog(str(wl_id))
        msg += "\n---\nWorklog details:\n" + _format_worklog_details(full_wl)
    except JiraTempoError:
        # If fetching the full worklog fails, the creation still succeeded.
        pass
    return msg


async def _handle_delete_worklog(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    wl_id = arguments["worklog_id"]
    await client.delete_worklog(wl_id)
    return f"Deleted worklog {wl_id}."


async def _handle_get_issue(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    key = _validate_issue_key(arguments["issue_key"])
    issue = await client.get_issue(key)
    fields = issue.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}
    summary = fields.get("summary", "")
    status_obj = fields.get("status", {})
    status = status_obj.get("name", "") if isinstance(status_obj, dict) else ""
    project_obj = fields.get("project", {})
    project = project_obj.get("name", "") if isinstance(project_obj, dict) else ""
    priority_obj = fields.get("priority", {})
    priority = priority_obj.get("name", "") if isinstance(priority_obj, dict) else ""
    assignee_obj = fields.get("assignee", {})
    assignee = assignee_obj.get("displayName", "") if isinstance(assignee_obj, dict) else ""
    duedate = fields.get("duedate", "") or "—"
    issuetype_obj = fields.get("issuetype", {})
    issuetype = issuetype_obj.get("name", "") if isinstance(issuetype_obj, dict) else ""
    components_list = fields.get("components", [])
    if not isinstance(components_list, list):
        components_list = []
    components = ", ".join(
        c.get("name", "") for c in components_list if isinstance(c, dict) and c.get("name")
    )
    description = fields.get("description", "") or "—"
    lines = [f"{key}: {summary}"]
    lines.append(f"Status: {status}")
    lines.append(f"Project: {project}")
    lines.append(f"Priority: {priority or '—'}")
    lines.append(f"Assignee: {assignee or '—'}")
    lines.append(f"Due date: {duedate}")
    lines.append(f"Issue type: {issuetype or '—'}")
    lines.append(f"Components: {components or '—'}")
    lines.append(f"Description: {description}")
    return "\n".join(lines)


async def _handle_list_favorites(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    try:
        favs = await client.list_favorite_issues()
    except FavoritesEndpointUnavailableError:
        return (
            "Favorite issues endpoint unavailable on this Jira installation. No favorites returned."
        )
    if not favs:
        return "No favorite issues found."
    lines = [f"- {f['key']}: {f['summary']}" for f in favs]
    return f"Favorite issues ({len(favs)}):\n" + "\n".join(lines)


async def _handle_generate_report(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    target = None
    if td := arguments.get("target_date"):
        # m8: validate date format with helpful error.
        target = _validate_date(td, "target_date")
    out_dir = None
    if raw_dir := arguments.get("output_dir"):
        out_dir = _validate_output_dir(raw_dir, config)

    # Template resolution (v0.2.0).
    registry = build_registry(config)
    template_name = arguments.get("template")
    template = None
    if template_name:
        template = registry.get(template_name)
        if template is None:
            raise ValueError(
                f"Unknown template {template_name!r}. "
                f"Available: {', '.join(registry.names()) or '(none)'}."
            )
    else:
        template = resolve_template(config, registry)

    # UX-7: optional username override.
    username = arguments.get("username")
    if username is not None and (not isinstance(username, str) or not username.strip()):
        raise ValueError("'username' must be a non-empty string.")

    path = await generate_weekly_report(
        client,
        config,
        target_date=target,
        output_dir=out_dir,
        template=template,
        registry=registry,
        fmt=arguments.get("format", "txt"),
        username=username,
    )
    return f"Weekly report generated: {path}\nReports directory: {Path(path).parent}"


async def _handle_generate_team_report(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    users = arguments.get("users")
    if not isinstance(users, list) or not users:
        users = config.team_users_resolved
        if not users:
            raise ValueError(
                "'users' must be a non-empty list of Jira usernames, or set "
                "REPORT_TEAM_USERS env var."
            )
    users = [str(u) for u in users]

    date_from = arguments.get("date_from")
    date_to = arguments.get("date_to")
    if date_from:
        _validate_date(date_from, "date_from")
    if date_to:
        _validate_date(date_to, "date_to")

    section_map = arguments.get("section_map")
    if section_map is not None and not isinstance(section_map, dict):
        raise ValueError("section_map must be an object (issue key -> section title).")

    out_dir = None
    if raw_dir := arguments.get("output_dir"):
        out_dir = _validate_output_dir(raw_dir, config, team=True)

    registry = build_registry(config)
    template_name = arguments.get("template", "team_report")
    template = registry.get(template_name)
    if template is None:
        raise ValueError(
            f"Unknown template {template_name!r}. "
            f"Available: {', '.join(registry.names()) or '(none)'}."
        )

    result = await generate_team_report(
        client,
        config,
        users,
        date_from=date_from,
        date_to=date_to,
        section_map=section_map,
        template=template,
        registry=registry,
        output_dir=out_dir,
        fmt=arguments.get("format", "txt"),
    )
    return f"{result.summary}\nReports directory: {result.file_path.parent}"


async def _handle_list_report_templates(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    registry = build_registry(config)
    templates = registry.all()
    if not templates:
        return "No report templates available."
    lines = [f"Report templates ({len(templates)}):"]
    for tpl in templates:
        # Provenance metadata: builtin vs custom, Jinja2 vs Python.
        # getattr fallback guards user-supplied TEMPLATE objects that may
        # not set kind/engine (the loader adapters always do).
        kind = getattr(tpl, "kind", "custom")
        engine = getattr(tpl, "engine", "unknown")
        lines.append(f"- {tpl.name} ({kind}, {engine}): {tpl.description}")
    return "\n".join(lines)


# --- Preview tool: sample data (mock worklogs, no Jira/Tempo calls) ---

# A fixed preview week so rendered output is deterministic across runs
# and timezones (the week does not depend on "today").
_PREVIEW_MONDAY = date(2026, 6, 15)
_PREVIEW_FRIDAY = date(2026, 6, 19)

# Mock worker key shared by every sample worklog.
_PREVIEW_WORKER = "preview-user"

# Issue titles for the default/minimal profiles. Keys that map to a
# section in REPORT_SECTION_MAP are intentionally absent here so the
# template's "unknown title -> key" fallback path is exercised too.
_PREVIEW_ISSUE_TITLES: dict[str, str] = {
    "DEVOPS-101": "Refactor Helm release workflow",
    "DEVOPS-102": "Migrate Valkey chart to v0.9",
    "DEVOPS-103": "Fix flaky integration test suite",
    "OPS-200": "On-call rotation handover",
}


def _make_sample_worklog(
    key: str | None,
    seconds: int,
    day: int,
    comment: str = "",
) -> dict[str, Any]:
    """Build a single mock Tempo worklog on the preview week.

    ``day`` is the day-of-month within June 2026 (15..19 = Mon..Fri).
    ``key`` is the issue key, or ``None`` for a worklog with no linked
    issue (exercises the no-task path where ``extract_issue_key`` returns
    ``None`` and templates skip the worklog).
    """
    wl: dict[str, Any] = {
        "issueKey": key,
        "timeSpentSeconds": seconds,
        "startDate": f"2026-06-{day:02d}",
        "started": f"2026-06-{day:02d} 10:00:00.000",
        "authorAccountId": _PREVIEW_WORKER,
    }
    if comment:
        wl["comment"] = comment
    return wl


def _sample_worklogs(profile: str) -> list[dict[str, Any]]:
    """Return mock Tempo worklogs for a preview-data profile.

    Profiles:
      * ``default`` — realistic week: 4 issues across Mon..Fri, varied
        durations, plus one no-task (standup) worklog with ``issueKey=None``
        that exercises the no-task fallback path.
      * ``minimal`` — a single 1h worklog.
      * ``empty`` — no worklogs (exercises empty-state rendering).
    """
    if profile == "empty":
        return []
    if profile == "minimal":
        return [
            _make_sample_worklog("DEVOPS-101", 3600, 15, "Kicked off the refactor."),
        ]
    # default — realistic multi-issue week.
    return [
        _make_sample_worklog("DEVOPS-101", 7200, 15, "Refactor Helm release workflow."),
        _make_sample_worklog("DEVOPS-101", 5400, 16, "Refactor Helm release workflow."),
        _make_sample_worklog("DEVOPS-102", 9000, 16, "Migrate Valkey chart to v0.9."),
        _make_sample_worklog("DEVOPS-103", 3600, 17, "Fix flaky integration test suite."),
        _make_sample_worklog("DEVOPS-103", 2700, 18, "Fix flaky integration test suite."),
        _make_sample_worklog("OPS-200", 1800, 15, "On-call rotation handover."),
        # No-task worklog (standup): issueKey=None exercises the no-task
        # fallback path — extract_issue_key returns None and templates skip
        # this worklog rather than crashing or inventing a section.
        _make_sample_worklog(None, 1800, 16, "Daily standup."),
    ]


async def _handle_preview_report_template(
    arguments: dict[str, Any], config: Config, _client: JiraTempoClient
) -> str:
    # _client is intentionally unused: preview never calls Jira/Tempo. The
    # leading underscore documents intent; the dispatch table in
    # _TOOL_HANDLERS passes it positionally, so renaming is safe.
    template_name = arguments.get("template_name")
    if not isinstance(template_name, str) or not template_name.strip():
        raise ValueError("'template_name' must be a non-empty string.")

    profile = arguments.get("sample_data", "default")
    if profile not in ("default", "minimal", "empty"):
        raise ValueError(f"'sample_data' must be one of default, minimal, empty — got {profile!r}.")

    registry = build_registry(config)
    template = registry.get(template_name)
    if template is None:
        raise ValueError(
            f"Unknown template {template_name!r}. "
            f"Available: {', '.join(registry.names()) or '(none)'}."
        )

    worklogs = _sample_worklogs(profile)
    rendered = template.render(
        worklogs,
        config,
        monday=_PREVIEW_MONDAY,
        friday=_PREVIEW_FRIDAY,
        issue_titles=dict(_PREVIEW_ISSUE_TITLES),
        author=config.report_author_header,
        # team_report consumes per-user groupings (per_user_worklogs +
        # users) instead of the flat worklogs list. default / weekly_summary
        # accept **kwargs and ignore these keys, so passing them is safe for
        # every builtin template and makes the team_report preview meaningful.
        per_user_worklogs={_PREVIEW_WORKER: worklogs},
        users=[(_PREVIEW_WORKER, "Preview User")],
    )
    # Guarantee a non-empty string even for empty-state templates that
    # render to "" (rare, but keeps the tool contract honest).
    return rendered or "(template rendered an empty string for this profile)"


async def _handle_search_users(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("'query' must be a non-empty string.")
    max_results = arguments.get("max_results", 10)
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("'max_results' must be a positive integer.")

    users = await client.search_users(query, max_results=max_results)
    if not users:
        return f"No users found for query {query!r}."

    lines = [f"Users matching {query!r} ({len(users)}):"]
    for u in users:
        active = "active" if u.get("active", True) else "inactive"
        lines.append(
            f"- {u['name']} ({u['key']}): {u['displayName']} <{u['emailAddress'] or '—'}> [{active}]"
        )
    return "\n".join(lines)


async def _handle_list_user_tasks(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    username = arguments.get("username")
    if not isinstance(username, str) or not username.strip():
        raise ValueError("'username' must be a non-empty string.")

    status_filter = arguments.get("status_filter")
    if status_filter is not None and (
        not isinstance(status_filter, list) or not all(isinstance(s, str) for s in status_filter)
    ):
        raise ValueError("'status_filter' must be a list of strings.")

    max_results = arguments.get("max_results", 100)
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("'max_results' must be a positive integer.")

    tasks = await client.list_user_tasks(
        username, status_filter=status_filter, max_results=max_results
    )
    if not tasks:
        return f"No tasks found for user {username!r}."

    lines = [f"Tasks for {username} ({len(tasks)}):"]
    for t in tasks:
        due = t.get("duedate", "") or "—"
        priority = t.get("priority", "") or "—"
        comments = t.get("comment_count", 0)
        lines.append(
            f"- [{t['key']}] {t['summary']} | {t['status']} | priority={priority} | due={due} | comments={comments}"
        )
        # UX-3: show last 1-2 comments indented under the task.
        if comments > 0:
            task_comments = t.get("comments", [])
            if isinstance(task_comments, list):
                for c in task_comments[-2:]:
                    if not isinstance(c, dict):
                        continue
                    author = c.get("author", "?")
                    body = str(c.get("body", ""))
                    # Truncate to 150 chars.
                    if len(body) > 150:
                        body = body[:150] + "..."
                    lines.append(f"    💬 {author}: {body}")
    return "\n".join(lines)


async def _handle_list_issues_by_jql(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    jql = arguments.get("jql")
    if not isinstance(jql, str) or not jql.strip():
        raise ValueError("'jql' must be a non-empty string.")
    fields = arguments.get(
        "fields",
        "summary,status,priority,duedate,assignee,issuetype,project,created,updated",
    )
    if not isinstance(fields, str) or not fields.strip():
        raise ValueError("'fields' must be a non-empty string.")
    max_results = arguments.get("max_results", 50)
    if not isinstance(max_results, int) or max_results < 1:
        raise ValueError("'max_results' must be a positive integer.")
    include_description = bool(arguments.get("include_description", False))

    issues = await client.search_issues(
        jql, fields=fields, max_results=max_results, include_description=include_description
    )
    if not issues:
        return f"No issues found for JQL: {jql}"

    lines = [f"Issues matching JQL ({len(issues)}):"]
    for issue in issues:
        due = issue.get("duedate", "") or "—"
        priority = issue.get("priority", "") or "—"
        assignee = issue.get("assignee", "") or "—"
        lines.append(
            f"- [{issue['key']}] {issue['summary']} | {issue['status']} | "
            f"priority={priority} | due={due} | assignee={assignee}"
        )
        if include_description:
            description = str(issue.get("description", "") or "—")
            lines.append(f"    Description: {description}")
    return "\n".join(lines)


async def _handle_get_current_user(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    user = await client.get_myself()
    lines = ["Current user:"]
    lines.append(f"  Username: {user.get('name', '—')}")
    lines.append(f"  Display name: {user.get('displayName', '—')}")
    lines.append(f"  Email: {user.get('emailAddress', '—') or '—'}")
    lines.append(f"  Key: {user.get('key', '—')}")
    lines.append(f"  Active: {user.get('active', '—')}")
    return "\n".join(lines)


async def _handle_generate_tasks_report(
    arguments: dict[str, Any], config: Config, client: JiraTempoClient
) -> str:
    users = arguments.get("users")
    if not isinstance(users, list) or not users:
        users = config.team_users_resolved
        if not users:
            raise ValueError(
                "'users' must be a non-empty list of Jira usernames, or set "
                "REPORT_TEAM_USERS env var."
            )
    users = [str(u) for u in users]

    active_only = bool(arguments.get("active_only", False))

    out_dir = None
    if raw_dir := arguments.get("output_dir"):
        out_dir = _validate_output_dir(raw_dir, config)

    result = await generate_tasks_report(
        client,
        config,
        users,
        active_only=active_only,
        output_dir=out_dir,
        fmt=arguments.get("format", "md"),
    )
    return f"{result.summary}\nReports directory: {result.file_path.parent}"


# Dispatch table (m3).
_TOOL_HANDLERS: dict[str, Any] = {
    "list_worklogs": _handle_list_worklogs,
    "get_worklog": _handle_get_worklog,
    "create_worklog": _handle_create_worklog,
    "delete_worklog": _handle_delete_worklog,
    "get_issue": _handle_get_issue,
    "list_favorite_issues": _handle_list_favorites,
    "generate_weekly_report": _handle_generate_report,
    "generate_team_report": _handle_generate_team_report,
    "list_report_templates": _handle_list_report_templates,
    "preview_report_template": _handle_preview_report_template,
    "search_users": _handle_search_users,
    "list_user_tasks": _handle_list_user_tasks,
    "list_issues_by_jql": _handle_list_issues_by_jql,
    "get_current_user": _handle_get_current_user,
    "generate_tasks_report": _handle_generate_tasks_report,
}


async def serve(config: Config) -> None:
    """Run the MCP server over stdio."""
    # Pass the app version so MCP clients see it in serverInfo (the SDK
    # otherwise surfaces only SERVER_VERSION, i.e. the MCP SDK release).
    server = Server("jira-tempo-mcp", version=__version__)

    # mypy: MCP SDK decorators are untyped — suppress until upstream adds hints.
    @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]  # MCP SDK decorators are untyped upstream
    async def _list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()  # type: ignore[untyped-decorator]  # MCP SDK decorators are untyped upstream
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        async with JiraTempoClient(config) as client:
            try:
                result = await handler(arguments, config, client)
            except Exception as exc:
                logger.exception("Tool %s failed", name)
                result = _user_friendly_error(exc)
            return [TextContent(type="text", text=result)]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Console script entrypoint."""
    config = load_config()
    _setup_logging(config.log_level)
    logger.info("Starting jira-tempo-mcp for %s", config.jira_base_url)
    asyncio.run(serve(config))


if __name__ == "__main__":
    main()
