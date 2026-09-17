"""Jira + Tempo Timesheets API client.

All HTTP calls go through this module. Tokens are read from Config and never
logged. Errors are redacted before propagation.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from .config import Config

logger = logging.getLogger(__name__)


def _retry_backoff_seconds(attempt: int) -> float:
    """Exponential backoff (seconds) for HTTP retries.

    Sequence for attempts 0,1,2,...: 0.5, 1.0, 2.0, 4.0 — capped at 30s.
    """
    return float(min(0.5 * (2 ** attempt), 30.0))


class JiraTempoError(Exception):
    """Raised on API errors. Message never contains tokens or full URLs with auth.

    Optional ``status_code`` (HTTP status of the failing response) and
    ``response_body`` (parsed JSON or raw text) are populated by the request
    path when an HTTP response is available. They are real instance
    attributes declared via an explicit ``__init__`` rather than class-level
    annotations, so there is no ambiguity about whether they exist on a given
    instance (previously they were class-level annotations silently
    inherited by subclasses and required ``# type: ignore[attr-defined]`` at
    call sites). ``str(exc)`` remains the message alone, so existing code that
    does ``if "429" in str(exc)`` keeps working.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class WorkerKeyResolutionError(JiraTempoError):
    """Raised when the Tempo worker key cannot be resolved for the configured user."""


class FavoritesEndpointUnavailableError(JiraTempoError):
    """Raised when the Jira /user/favourites endpoint is unavailable (404/etc)."""


# Russian -> English statusCategory name mapping (BUG-1).
_RU_STATUS_TO_CATEGORY: dict[str, str] = {
    "В работе": "In Progress",
    "In Progress": "In Progress",
    "Открыта": "To Do",
    "To Do": "To Do",
    "Open": "To Do",
    "Готово": "Done",
    "Выполнена": "Done",
    "Решена": "Done",
    "Done": "Done",
    "Closed": "Done",
    "Закрыта": "Done",
    "Ожидание": "In Progress",
    "На рассмотрении": "In Progress",
    "In Review": "In Progress",
    "Заблокирована": "In Progress",
    "Blocked": "In Progress",
}


def _redact(url: str) -> str:
    """Strip any credentials from URL for safe logging."""
    if "://" in url and "@" in url.split("://", 1)[1]:
        scheme, rest = url.split("://", 1)
        host = rest.split("@", 1)[1]
        return f"{scheme}://***@{host}"
    return url


# Secret patterns that may appear in API error response bodies. Matches are
# replaced with ``***REDACTED***`` before the body reaches logs or exception
# messages. Covers GitHub tokens (ghp_/gho_/ghs_/ghu_/github_pat_), Vault
# (hvs.), Stripe/Anthropic/OpenAI (sk-), Slack (xox[bpoa]-), and Authorization
# header echoes (Bearer <token>).
_SECRET_BODY_RE = re.compile(
    r"(?:gh[pous]_|github_pat_)[A-Za-z0-9_]{8,}"
    r"|hvs\.[A-Za-z0-9._-]{8,}"
    r"|sk[-_][A-Za-z0-9_-]{15,}"
    r"|xox[bpoa]-[A-Za-z0-9-]{10,}"
    r"|Bearer\s+[A-Za-z0-9._\-]+"
)


def _redact_body(text: str) -> str:
    """Mask token-shaped substrings in an API response body before logging.

    Pairs with :func:`_redact` (which strips URL credentials): ``_redact``
    handles the request URL, ``_redact_body`` handles the response body.
    """
    return _SECRET_BODY_RE.sub("***REDACTED***", text)


class JiraTempoClient:
    """Async HTTP client for Jira REST API and Tempo Timesheets 4 API."""

    # UX-1: class-level cache shared across all instances within a process.
    # The MCP server creates a new JiraTempoClient per tool call, so an
    # instance-level cache is lost between calls and the /workers 404 noise
    # reappears every time. The /workers endpoint availability does not
    # change during a session, so a process-wide class cache is safe.
    _workers_endpoint_available: bool | None = None

    def __init__(self, config: Config) -> None:
        self._config = config
        # M1: explicit TLS verification + no redirects (defense-in-depth).
        # follow_redirects=False prevents PAT leakage via redirect to a different host.
        self._client = httpx.AsyncClient(
            timeout=config.http_timeout,
            verify=True,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> JiraTempoClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # --- auth headers ---

    def _jira_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.jira_pat}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _tempo_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.tempo_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # --- low-level request helper ---

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        # Retry transient failures on idempotent GET only (finding #11).
        # Non-GET methods never retry: a network error on POST is ambiguous
        # (the request may have reached the server) and retrying could create
        # duplicates (e.g. worklogs). Default http_max_retries=0 keeps the
        # original fail-fast behaviour.
        max_retries = self._config.http_max_retries
        idempotent = method.upper() == "GET"
        for attempt in range(max_retries + 1):
            try:
                resp = await self._client.request(
                    method, url, headers=headers, json=json, params=params
                )
            except httpx.RequestError as exc:
                if idempotent and attempt < max_retries:
                    delay = _retry_backoff_seconds(attempt)
                    logger.warning(
                        "Network error %s on %s %s (attempt %d/%d) — retrying in %.2fs",
                        exc.__class__.__name__,
                        method,
                        _redact(url),
                        attempt + 1,
                        max_retries,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise JiraTempoError(
                    f"Network error contacting Jira/Tempo: {exc.__class__.__name__}"
                ) from exc

            # Retry idempotent GET on HTTP 5xx before entering the error path.
            if (
                500 <= resp.status_code <= 599
                and idempotent
                and attempt < max_retries
            ):
                delay = _retry_backoff_seconds(attempt)
                logger.warning(
                    "HTTP %d from %s %s (attempt %d/%d) — retrying in %.2fs",
                    resp.status_code,
                    method,
                    _redact(url),
                    attempt + 1,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if resp.status_code >= 400:
                # Truncate to 200 chars and redact token-shaped substrings so
                # error logs / exception messages never leak a secret echoed by
                # the API in the response body.
                raw_body = resp.text[:200] if resp.text else ""
                body = _redact_body(raw_body)
                logger.error("API %s %s -> %s: %s", method, _redact(url), resp.status_code, body)
                try:
                    parsed_body: Any = resp.json()
                except ValueError:
                    # Malformed JSON body (json.JSONDecodeError is a subclass
                    # of ValueError) — fall back to raw response text.
                    parsed_body = resp.text
                raise JiraTempoError(
                    f"API error {resp.status_code} from {_redact(url)}: {body}",
                    status_code=resp.status_code,
                    response_body=parsed_body,
                )

            if resp.status_code == 204 or not resp.text:
                return None
            return resp.json()

        # Unreachable: the loop body always returns, raises, or continues
        # until the last attempt falls through to the error path above.
        # Kept for type-checkers; flagged so coverage does not expect it.
        raise JiraTempoError("retry loop exited without a result")  # pragma: no cover

    # --- paginated GET (Jira REST startAt/total) ---

    async def _paginated_get(
        self,
        url: str,
        params: dict[str, Any],
        *,
        results_key: str = "issues",
        page_size: int = 100,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all rows from a Jira REST endpoint that uses startAt/total paging.

        Jira /search returns ``{issues: [...], startAt, maxResults, total}``.
        Some endpoints (e.g. /user/search) return a bare list with no
        envelope; for those we page while the page is full and trust the
        server to return an empty/short final page.

        ``max_results`` caps the TOTAL number of rows returned across all
        pages (caller-requested cap), distinct from ``page_size`` (rows per
        HTTP request). Stops early once the cap is reached.
        """
        page_size = max(1, page_size)
        out: list[dict[str, Any]] = []
        start_at = 0
        while True:
            page_params = dict(params)
            page_params["startAt"] = start_at
            page_params["maxResults"] = page_size
            data = await self._request("GET", url, self._jira_headers(), params=page_params)
            page: list[Any] = []
            total: int | None = None
            if isinstance(data, list):
                # Bare-list response (no pagination envelope): each item is a row.
                page = [item for item in data if isinstance(item, dict)]
            elif isinstance(data, dict):
                chunk = data.get(results_key)
                if isinstance(chunk, list):
                    page = [item for item in chunk if isinstance(item, dict)]
                raw_total = data.get("total")
                if isinstance(raw_total, int):
                    total = raw_total
            out.extend(page)
            if max_results is not None and len(out) >= max_results:
                return out[:max_results]
            if not page:
                # Empty page -> done (also covers the empty-result case).
                break
            # Envelope shape: stop once we have reached `total`.
            if total is not None:
                if start_at + len(page) >= total:
                    break
            else:
                # Bare-list shape: stop when a page is short (underfull).
                if len(page) < page_size:
                    break
            start_at += len(page)
        return out

    # --- Jira issue ---

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Get issue metadata (key, summary, status, project, priority, assignee, duedate, issuetype, components, description)."""
        url = f"{self._config.jira_api_base}/issue/{issue_key}"
        fields = "summary,status,project,issuetype,priority,assignee,duedate,components,description"
        data = await self._request("GET", url, self._jira_headers(), params={"fields": fields})
        if not isinstance(data, dict):
            raise JiraTempoError(f"Unexpected response for issue {issue_key}")
        return data

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str = "",
        issuetype: str = "Task",
        parent_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a Jira issue via POST /rest/api/2/issue.

        project_key: target project (e.g. ``DEVOPS``).
        summary: issue summary (non-empty).
        description: optional issue description (Jira wiki markup or plain text).
        issuetype: issue type name (e.g. ``Task``, ``Sub-task``). Defaults to
            ``Task``.
        parent_key: optional parent issue key (e.g. ``DEVOPS-100``). When set,
            the ``parent`` field is included in the payload — Jira REST v2
            documents ``"parent": {"key": "PROJ-123"}`` and this covers both
            team-managed subtasks and company-managed epic/parent links.

        Returns a normalized dict: ``key``, ``id``, ``self`` (the fields Jira
        returns from the create endpoint).

        Raises :class:`JiraTempoError` for empty project/summary/issuetype
        (client-side validation) and on API errors.
        """
        if not isinstance(project_key, str) or not project_key.strip():
            raise JiraTempoError("project_key must be a non-empty string.")
        if not isinstance(summary, str) or not summary.strip():
            raise JiraTempoError("summary must be a non-empty string.")
        if not isinstance(issuetype, str) or not issuetype.strip():
            raise JiraTempoError("issuetype must be a non-empty string.")

        url = f"{self._config.jira_api_base}/issue"
        fields: dict[str, Any] = {
            "project": {"key": project_key.strip().upper()},
            "summary": summary,
            "issuetype": {"name": issuetype.strip()},
        }
        if description:
            fields["description"] = description
        if parent_key:
            if not isinstance(parent_key, str) or not parent_key.strip():
                raise JiraTempoError("parent_key must be a non-empty string when provided.")
            fields["parent"] = {"key": parent_key.strip().upper()}
        data = await self._request("POST", url, self._jira_headers(), json={"fields": fields})
        if not isinstance(data, dict):
            raise JiraTempoError("Unexpected response shape from issue creation")
        return {
            "key": data.get("key", ""),
            "id": data.get("id", ""),
            "self": data.get("self", ""),
        }

    async def add_issue_comment(self, issue_key: str, comment: str) -> dict[str, Any]:
        """Add a comment to a Jira issue via POST /rest/api/2/issue/{key}/comment.

        Returns a normalized dict: ``id`` (comment id), ``self`` (comment URL),
        ``body`` (stored comment text).

        Raises :class:`JiraTempoError` for an empty comment (client-side
        validation) and on API errors.
        """
        if not isinstance(comment, str) or not comment.strip():
            raise JiraTempoError("comment must be a non-empty string.")

        url = f"{self._config.jira_api_base}/issue/{issue_key}/comment"
        data = await self._request(
            "POST", url, self._jira_headers(), json={"body": comment}
        )
        if not isinstance(data, dict):
            raise JiraTempoError(f"Unexpected response shape for comment on {issue_key}")
        return {
            "id": data.get("id", ""),
            "self": data.get("self", ""),
            "body": data.get("body", ""),
        }

    # --- Tempo worklogs ---

    async def search_worklogs(
        self,
        date_from: str,
        date_to: str,
        *,
        worker_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search Tempo worklogs in a date range (ISO dates YYYY-MM-DD).

        Uses POST /worklogs/search (Tempo 4 API). Returns raw worklog objects.
        """
        url = f"{self._config.tempo_api_base}/worklogs/search"
        payload: dict[str, Any] = {"from": date_from, "to": date_to}
        if worker_keys:
            payload["worker"] = worker_keys
        data = await self._request("POST", url, self._tempo_headers(), json=payload)
        if data is None:
            return []
        if isinstance(data, dict) and "results" in data:
            return list(data["results"])
        if isinstance(data, list):
            return data
        raise JiraTempoError("Unexpected worklogs search response shape")

    async def get_worklog(self, worklog_id: str) -> dict[str, Any]:
        """Get a single Tempo worklog by its Tempo internal id."""
        url = f"{self._config.tempo_api_base}/worklogs/{worklog_id}"
        data = await self._request("GET", url, self._tempo_headers())
        if not isinstance(data, dict):
            raise JiraTempoError(f"Unexpected response for worklog {worklog_id}")
        return data

    async def create_worklog(
        self,
        *,
        issue_key: str,
        time_spent_seconds: int,
        date_started: str,  # ISO date, e.g. 2026-06-08 or 2026-06-08T10:00:00+03:00
        comment: str = "",
        author_account_id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a Tempo worklog.

        issue_key: Jira issue key (e.g. PROJECT-100).
        time_spent_seconds: duration in seconds.
        date_started: ISO date string. Tempo accepts ``YYYY-MM-DD`` or
            ``YYYY-MM-DDTHH:MM:SS.000+ZZZZ``. The ``started`` field is used
            (not ``startDate``) — Tempo's internal field name.
        comment: optional worklog comment.
        author_account_id: Tempo worker key; if None, server uses the token owner.
        attributes: optional Tempo work attributes (e.g.
            ``{"_Специализация_": "Devops", "_Форматработы_": "Удаленно"}``).
            Some Tempo installations require mandatory attributes — without
            them the API returns 400.

        Tempo's POST /worklogs endpoint does NOT accept ``issueKey`` — it
        requires ``originTaskId`` (the Jira internal numeric issue ID).
        This method resolves the issue key to the internal ID via Jira REST
        API automatically.
        """
        # Resolve Jira issue key → internal numeric ID.
        issue_url = f"{self._config.jira_api_base}/issue/{issue_key}"
        issue_data = await self._request(
            "GET", issue_url, self._jira_headers(), params={"fields": "summary"}
        )
        origin_task_id = issue_data.get("id") if isinstance(issue_data, dict) else None
        if not origin_task_id:
            raise JiraTempoError(f"Could not resolve internal issue ID for {issue_key!r}")

        url = f"{self._config.tempo_api_base}/worklogs"
        payload: dict[str, Any] = {
            "originTaskId": int(origin_task_id),
            "timeSpentSeconds": time_spent_seconds,
            "started": date_started,
            "comment": comment,
        }
        if author_account_id:
            payload["worker"] = author_account_id
        if attributes:
            payload["attributes"] = {k: {"value": v} for k, v in attributes.items()}
        data = await self._request("POST", url, self._tempo_headers(), json=payload)
        # Tempo POST /worklogs returns a list of created worklogs (even for
        # a single entry). Extract the first one.
        if isinstance(data, list) and data:
            result: dict[str, Any] = data[0]
            return result
        if isinstance(data, dict):
            return data
        raise JiraTempoError("Unexpected create worklog response")

    async def delete_worklog(self, worklog_id: str) -> None:
        """Delete a Tempo worklog by id."""
        url = f"{self._config.tempo_api_base}/worklogs/{worklog_id}"
        await self._request("DELETE", url, self._tempo_headers())

    # --- Tempo work attribute definitions ---

    async def get_work_attributes(self) -> list[dict[str, Any]]:
        """Get Tempo work attribute definitions.

        Returns a list of dicts with keys: ``key``, ``name``, ``type``,
        ``required`` (bool), and ``values`` (list[str], only for STATIC_LIST
        type). Returns an empty list if the endpoint is unavailable (404)
        or returns an unexpected shape — graceful degradation so callers
        can fall back to parsing the 400 error body.
        """
        url = f"{self._config.tempo_api_base}/work-attributes"
        try:
            data = await self._request("GET", url, self._tempo_headers())
        except JiraTempoError as exc:
            status = getattr(exc, "status_code", None)
            if status == 404:
                logger.warning("Tempo work-attributes endpoint unavailable (404)")
                return []
            raise
        if not isinstance(data, list):
            logger.warning("Unexpected work-attributes response shape: %s", type(data).__name__)
            return []

        result: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", item.get("id", "")))
            name = str(item.get("name", key))
            attr_type = str(item.get("type", item.get("valueType", "")))
            required = bool(item.get("required", False))
            values: list[str] = []
            # STATIC_LIST attributes expose possible values under "values".
            possible = item.get("values")
            if isinstance(possible, list):
                values = [
                    str(v.get("value", v)) if isinstance(v, dict) else str(v) for v in possible
                ]
            result.append(
                {
                    "key": key,
                    "name": name,
                    "type": attr_type,
                    "required": required,
                    "values": values,
                }
            )
        return result

    # --- Tempo worker key lookup ---

    async def find_worker_key(self, username: str | None = None) -> str:
        """Find Tempo worker key for a Jira username.

        Resolution order:
        1. TEMPO_WORKER_KEY env var (explicit override, skips API calls).
        2. Tempo 4 API: GET /workers?username=... — returns list of workers.
        3. Fallback for the PAT owner (``username`` is None or equals
           ``config.jira_user``): Jira REST API GET /myself — returns the
           ``key`` field (e.g. ``JIRAUSER40101``).
        4. Fallback for any other user: Jira REST API GET /user/search
           — returns a list of matching users with ``key`` fields.

        The /workers endpoint is missing or returns 404 on some Tempo
        installations (e.g. on-prem Jira Data Center with restricted REST
        modules). The Jira fallbacks keep worker-key resolution working
        without the Tempo Teams API.

        ``/myself`` only returns the key of the **authenticated user** (the
        PAT owner), so it is only valid for the default user. For any other
        username we use ``/user/search?username=...`` which returns the
        correct per-user ``key``.

        Raises WorkerKeyResolutionError if all strategies fail. This
        prevents silent empty-result bugs where list_worklogs returns []
        because the wrong key was used.
        """
        import os

        # 1. Explicit env override — highest priority, no API calls.
        env_key = os.getenv("TEMPO_WORKER_KEY", "").strip()
        if env_key:
            return env_key

        target = username or self._config.jira_user

        # 2. Tempo /workers endpoint (UX-1: skip if known-unavailable).
        #    Cache is class-level so it persists across per-call instances.
        if JiraTempoClient._workers_endpoint_available is not False:
            url = f"{self._config.tempo_api_base}/workers"
            try:
                data = await self._request(
                    "GET", url, self._tempo_headers(), params={"username": target}
                )
                JiraTempoClient._workers_endpoint_available = True
                if isinstance(data, list) and data:
                    first = data[0]
                    if isinstance(first, dict):
                        key = first.get("key") or first.get("accountId") or first.get("id")
                        if key is not None:
                            return str(key)
            except JiraTempoError:
                if JiraTempoClient._workers_endpoint_available is None:
                    JiraTempoClient._workers_endpoint_available = False
                    logger.info(
                        "Tempo /workers endpoint unavailable, using Jira REST "
                        "fallback for worker key resolution."
                    )

        # 3. Jira REST fallback.
        #    /myself returns the PAT owner's key — only valid for the
        #    default user. For any other username we must use /user/search
        #    so we resolve the correct per-user key.
        is_default_user = target == self._config.jira_user
        if is_default_user:
            myself_url = f"{self._config.jira_api_base}/myself"
            try:
                myself = await self._request("GET", myself_url, self._jira_headers())
            except JiraTempoError as exc:
                raise WorkerKeyResolutionError(
                    f"Could not resolve Tempo worker key for {target!r}: "
                    f"Tempo /workers endpoint unavailable and Jira /myself failed: {exc}. "
                    f"Set TEMPO_WORKER_KEY env var to the worker key (e.g. JIRAUSER12345)."
                ) from exc
            key = myself.get("key") if isinstance(myself, dict) else None
            if key:
                return str(key)
            raise WorkerKeyResolutionError(
                f"Could not resolve Tempo worker key for {target!r}: "
                f"Tempo /workers endpoint unavailable and Jira /myself returned no key. "
                f"Set TEMPO_WORKER_KEY env var to the worker key (e.g. JIRAUSER12345)."
            )

        # 4. Non-default user: Jira REST API user search — returns a list
        #    of matching users, each with a ``key`` field (e.g.
        #    ``JIRAUSER40101``) which Tempo accepts as a worker key.
        #    Paginated for consistency with search_users(): /user/search can
        #    return a bare list with no envelope, so without paging a large
        #    user directory could silently truncate before the exact match.
        search_url = f"{self._config.jira_api_base}/user/search"
        try:
            results = await self._paginated_get(
                search_url,
                {"username": target},
                results_key="values",
                page_size=100,
                max_results=1000,
            )
        except JiraTempoError as exc:
            raise WorkerKeyResolutionError(
                f"Could not resolve Tempo worker key for {target!r}: "
                f"Tempo /workers endpoint unavailable and Jira user search failed: {exc}. "
                f"Set TEMPO_WORKER_KEY env var to the worker key (e.g. JIRAUSER12345)."
            ) from exc

        if isinstance(results, list):
            # Prefer an exact match by username (``name``) or key.
            for user in results:
                if not isinstance(user, dict):
                    continue
                user_name = user.get("name", "")
                user_key = user.get("key", "")
                if user_name == target or user_key == target:
                    key = user.get("key")
                    if key:
                        return str(key)
            # No exact match — take the first result's key if present.
            if results and isinstance(results[0], dict):
                key = results[0].get("key")
                if key:
                    return str(key)

        raise WorkerKeyResolutionError(
            f"Could not resolve Tempo worker key for {target!r}: "
            f"Tempo /workers endpoint unavailable and Jira user search returned no match. "
            f"Set TEMPO_WORKER_KEY env var to the worker key (e.g. JIRAUSER12345)."
        )

    # --- favorites (optional convenience) ---

    async def list_favorite_issues(self) -> list[dict[str, Any]]:
        """List favorite issues for the current user via Jira REST API.

        Uses the /user/favourites endpoint for issues. Returns list of
        {key, summary} dicts. Raises FavoritesEndpointUnavailableError if the endpoint is unavailable (404/other error).
        """
        url = f"{self._config.jira_api_base}/user/favourites"
        try:
            data = await self._request("GET", url, self._jira_headers())
        except JiraTempoError as exc:
            raise FavoritesEndpointUnavailableError(
                f"Favorite issues endpoint unavailable: {exc}"
            ) from exc
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                key = item.get("key")
                fields = item.get("fields", {}) if isinstance(item.get("fields"), dict) else {}
                summary = fields.get("summary", "") if isinstance(fields, dict) else ""
                if key:
                    out.append({"key": key, "summary": summary})
        return out

    # --- User search & task listing ---

    async def search_users(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Search Jira users by name, surname, or username.

        Returns list of dicts with: name, key, displayName, emailAddress, active.
        """
        url = f"{self._config.jira_api_base}/user/search"
        # /user/search returns a bare list (no pagination envelope); page
        # until a short/empty page is returned so large user sets are not
        # silently truncated.
        users = await self._paginated_get(
            url,
            {"username": query},
            results_key="values",
            page_size=max(1, max_results),
            max_results=max_results,
        )
        return [
            {
                "name": u.get("name", ""),
                "key": u.get("key", ""),
                "displayName": u.get("displayName", ""),
                "emailAddress": u.get("emailAddress", ""),
                "active": u.get("active", True),
            }
            for u in users
        ]

    async def list_user_tasks(
        self,
        username: str,
        *,
        status_filter: list[str] | None = None,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Get tasks assigned to a user.

        Args:
            username: Jira username (e.g. 'golikhin').
            status_filter: if provided, only return tasks in these statuses.
            max_results: max number of tasks to return.

        Returns list of task dicts with: key, summary, status, statusCategory,
        duedate, priority, issuetype, project, projectKey, created, updated,
        comments (last 3), comment_count.
        """
        # JQL assignee accepts the Jira username directly (not the Jira key /
        # Tempo worker key). Quoting handles usernames with spaces.
        jql = f'assignee = "{username}"'
        if status_filter:
            # BUG-1: Translate Russian status names to language-independent
            # statusCategory names. If all filter values map successfully,
            # use statusCategory IN (...). If any value is unknown, fall back
            # to status IN (...) with the original values.
            mapped: list[str] = []
            all_mapped = True
            for s in status_filter:
                cat = _RU_STATUS_TO_CATEGORY.get(s)
                if cat is not None:
                    mapped.append(cat)
                else:
                    all_mapped = False
                    break
            if all_mapped and mapped:
                seen: set[str] = set()
                unique_cats: list[str] = []
                for c in mapped:
                    if c not in seen:
                        seen.add(c)
                        unique_cats.append(c)
                cats = ", ".join(f'"{c}"' for c in unique_cats)
                jql += f" AND statusCategory IN ({cats})"
            else:
                # At least one status_filter value has no entry in
                # _RU_STATUS_TO_CATEGORY, so statusCategory filtering cannot be
                # used. Log so the operator can see which statuses were not
                # covered and extend the mapping if needed.
                unmapped = [s for s in status_filter if _RU_STATUS_TO_CATEGORY.get(s) is None]
                logger.info(
                    "status_filter fallback to 'status IN (...)' — "
                    "unmapped status values: %s",
                    unmapped,
                )
                statuses = ", ".join(f'"{s}"' for s in status_filter)
                jql += f" AND status IN ({statuses})"
        jql += " ORDER BY updated DESC"

        url = f"{self._config.jira_api_base}/search"
        # Paginate via startAt/total so users with >page-size assigned issues
        # are not silently truncated. ``max_results`` is now the TOTAL cap across
        # pages; the per-request page size is bounded to 100 (the Jira /search
        # server ceiling) so an unbounded pagination loop cannot pull thousands
        # of issues. Mirrors search_issues() cap semantics. (#2)
        capped_page = min(max_results, 100)
        issues = await self._paginated_get(
            url,
            {
                "jql": jql,
                "fields": "summary,status,duedate,comment,priority,issuetype,project,created,updated",
            },
            results_key="issues",
            page_size=capped_page,
            max_results=max_results,
        )

        tasks: list[dict[str, Any]] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            fields = issue.get("fields", {})
            if not isinstance(fields, dict):
                fields = {}
            status_obj = fields.get("status", {})
            if not isinstance(status_obj, dict):
                status_obj = {}
            priority_obj = fields.get("priority", {})
            if not isinstance(priority_obj, dict):
                priority_obj = {}
            issuetype_obj = fields.get("issuetype", {})
            if not isinstance(issuetype_obj, dict):
                issuetype_obj = {}
            project_obj = fields.get("project", {})
            if not isinstance(project_obj, dict):
                project_obj = {}
            comments_obj = fields.get("comment", {})
            if not isinstance(comments_obj, dict):
                comments_obj = {}
            comment_list = comments_obj.get("comments", [])
            if not isinstance(comment_list, list):
                comment_list = []

            # Extract last 3 comments (most recent last in Jira API).
            recent_comments: list[dict[str, Any]] = []
            for c in comment_list[-3:]:
                if not isinstance(c, dict):
                    continue
                author_obj = c.get("author", {})
                author = author_obj.get("displayName", "?") if isinstance(author_obj, dict) else "?"
                body = c.get("body", "")
                created = c.get("created", "")
                recent_comments.append(
                    {
                        "author": author,
                        "body": str(body)[:200],
                        "created": created,
                    }
                )

            status_cat = status_obj.get("statusCategory", {})
            if not isinstance(status_cat, dict):
                status_cat = {}

            tasks.append(
                {
                    "key": issue.get("key", ""),
                    "summary": fields.get("summary", ""),
                    "status": status_obj.get("name", ""),
                    "statusCategory": status_cat.get("name", ""),
                    "statusCategoryKey": status_cat.get("key", ""),
                    "duedate": fields.get("duedate", ""),
                    "priority": priority_obj.get("name", ""),
                    "issuetype": issuetype_obj.get("name", ""),
                    "project": project_obj.get("name", ""),
                    "projectKey": project_obj.get("key", ""),
                    "created": fields.get("created", ""),
                    "updated": fields.get("updated", ""),
                    "comments": recent_comments,
                    "comment_count": len(comment_list),
                }
            )
        return tasks

    # --- JQL search (UX-5) ---

    async def search_issues(
        self,
        jql: str,
        fields: str = "summary,status,priority,duedate,assignee,issuetype,project,created,updated",
        max_results: int = 50,
        include_description: bool = False,
    ) -> list[dict[str, Any]]:
        """Search Jira issues via JQL (read-only GET /rest/api/2/search).

        include_description: opt-in flag — when True, ``description`` is added
        to the requested fields and included in each mapped issue. Defaults to
        False so list responses keep the compact contract (descriptions can be
        large and must not inflate list responses silently).
        """
        if not isinstance(jql, str) or not jql.strip():
            raise JiraTempoError("jql must be a non-empty string.")
        if include_description:
            fields = f"{fields},description"
        # Cap the TOTAL result size at 100, but page through startAt/total
        # so the cap is honoured without early truncation on large result sets.
        capped_max = min(max_results, 100)
        url = f"{self._config.jira_api_base}/search"
        raw_issues = await self._paginated_get(
            url,
            {"jql": jql, "fields": fields},
            results_key="issues",
            page_size=capped_max,
            max_results=capped_max,
        )
        issues: list[dict[str, Any]] = []
        for issue in raw_issues:
            if not isinstance(issue, dict):
                continue
            fields_obj = issue.get("fields", {})
            if not isinstance(fields_obj, dict):
                fields_obj = {}
            status_obj = fields_obj.get("status", {})
            if not isinstance(status_obj, dict):
                status_obj = {}
            priority_obj = fields_obj.get("priority", {})
            if not isinstance(priority_obj, dict):
                priority_obj = {}
            issuetype_obj = fields_obj.get("issuetype", {})
            if not isinstance(issuetype_obj, dict):
                issuetype_obj = {}
            project_obj = fields_obj.get("project", {})
            if not isinstance(project_obj, dict):
                project_obj = {}
            assignee_obj = fields_obj.get("assignee", {})
            if not isinstance(assignee_obj, dict):
                assignee_obj = {}
            mapped: dict[str, Any] = {
                "key": issue.get("key", ""),
                "summary": fields_obj.get("summary", ""),
                "status": status_obj.get("name", ""),
                "priority": priority_obj.get("name", ""),
                "duedate": fields_obj.get("duedate", ""),
                "assignee": assignee_obj.get("displayName", ""),
                "issuetype": issuetype_obj.get("name", ""),
                "project": project_obj.get("name", ""),
                "projectKey": project_obj.get("key", ""),
                "created": fields_obj.get("created", ""),
                "updated": fields_obj.get("updated", ""),
            }
            if include_description:
                mapped["description"] = fields_obj.get("description", "")
            issues.append(mapped)
        return issues

    # --- Current user (UX-6) ---

    async def get_myself(self) -> dict[str, Any]:
        """Get info about the authenticated user (PAT owner).

        Returns dict with: name, displayName, emailAddress, key, active.
        """
        url = f"{self._config.jira_api_base}/myself"
        data = await self._request("GET", url, self._jira_headers())
        if not isinstance(data, dict):
            raise JiraTempoError("Unexpected response from /myself")
        return {
            "name": data.get("name", ""),
            "displayName": data.get("displayName", ""),
            "emailAddress": data.get("emailAddress", ""),
            "key": data.get("key", ""),
            "active": data.get("active", True),
        }
