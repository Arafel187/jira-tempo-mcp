"""Pagination tests for JiraTempoClient methods that use Jira startAt/total paging.

These tests mock the HTTP transport (httpx.MockTransport) so the client's
REAL pagination loop is exercised against synthetic multi-page responses —
no real network, no credentials, no AsyncMock of the client itself.

Covers:
- search_issues   (Jira /rest/api/2/search — {issues, startAt, maxResults, total} envelope)
- list_user_tasks (Jira /rest/api/2/search — same envelope, JQL assignee)
- search_users    (Jira /rest/api/2/user/search — bare list, no envelope)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from jira_tempo_mcp.client import JiraTempoClient, JiraTempoError
from jira_tempo_mcp.config import Config


def _make_config() -> Config:
    return Config(
        jira_base_url="https://jira.test.example",
        jira_user="testuser",
        jira_pat="fake-pat-for-testing",
        timezone="Europe/Moscow",
    )


def _client_with_transport(handler) -> JiraTempoClient:
    """Build a real JiraTempoClient whose httpx calls are routed to `handler`.

    `handler` is a callable(request: httpx.Request) -> httpx.Response.
    """
    client = JiraTempoClient(_make_config())
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=30.0,
        verify=True,
        follow_redirects=False,
    )
    return client


def _issue(key: str) -> dict[str, Any]:
    """Minimal Jira issue dict that search_issues / list_user_tasks can parse."""
    return {
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "status": {"name": "Open"},
            "priority": {"name": "Medium"},
            "issuetype": {"name": "Task"},
            "project": {"name": "P", "key": "P"},
            "duedate": "",
            "created": "",
            "updated": "",
        },
    }


# --- search_issues: {issues, startAt, maxResults, total} envelope -------------


@pytest.mark.asyncio
async def test_search_issues_single_page_returns_all() -> None:
    """total <= page size: one request, all issues returned."""
    issues = [_issue(f"PROJ-{i}") for i in range(3)]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/api/2/search")
        params = dict(request.url.params)
        assert params["startAt"] == "0"
        return httpx.Response(
            200,
            json={"issues": issues, "startAt": 0, "maxResults": 100, "total": 3},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.search_issues("project = PROJ")
    finally:
        await client.aclose()
    assert len(result) == 3
    assert [r["key"] for r in result] == ["PROJ-0", "PROJ-1", "PROJ-2"]


@pytest.mark.asyncio
async def test_search_issues_multi_page_accumulates() -> None:
    """total > page size: accumulates across pages with correct startAt progression."""
    all_issues = [_issue(f"PROJ-{i}") for i in range(7)]
    seen_start_at: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        start_at = int(params["startAt"])
        seen_start_at.append(params["startAt"])
        # page_size is capped_max = min(max_results, 100) = 5 here.
        page = all_issues[start_at : start_at + 5]
        return httpx.Response(
            200,
            json={"issues": page, "startAt": start_at, "maxResults": 5, "total": 7},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.search_issues("project = PROJ", max_results=5)
    finally:
        await client.aclose()
    assert len(result) == 5  # capped at max_results=5
    assert [r["key"] for r in result] == ["PROJ-0", "PROJ-1", "PROJ-2", "PROJ-3", "PROJ-4"]
    # First request always starts at 0.
    assert seen_start_at[0] == "0"


@pytest.mark.asyncio
async def test_search_issues_multi_page_no_cap_returns_all() -> None:
    """With a large max_results, pagination walks all pages without early stop."""
    all_issues = [_issue(f"PROJ-{i}") for i in range(7)]
    seen_start_at: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_at = int(dict(request.url.params)["startAt"])
        seen_start_at.append(dict(request.url.params)["startAt"])
        page = all_issues[start_at : start_at + 5]
        return httpx.Response(
            200,
            json={"issues": page, "startAt": start_at, "maxResults": 5, "total": 7},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.search_issues("project = PROJ", max_results=100)
    finally:
        await client.aclose()
    assert len(result) == 7
    assert [r["key"] for r in result] == [f"PROJ-{i}" for i in range(7)]
    # Pages requested at startAt 0 and 5; third page not needed because 5+2 >= 7.
    assert seen_start_at == ["0", "5"]


@pytest.mark.asyncio
async def test_search_issues_empty_result() -> None:
    """total == 0: single request, returns empty list."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issues": [], "startAt": 0, "maxResults": 100, "total": 0})

    client = _client_with_transport(handler)
    try:
        result = await client.search_issues("project = NOPE")
    finally:
        await client.aclose()
    assert result == []


# --- search_issues: include_description flag ---------------------------------


@pytest.mark.asyncio
async def test_search_issues_include_description_true() -> None:
    """include_description=True adds description to fields and to mapped issues."""
    seen_fields: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_fields.append(dict(request.url.params)["fields"])
        issue = dict(_issue("PROJ-0"))
        issue["fields"] = {
            **issue["fields"],  # type: ignore[dict-item]
            "description": "Full issue description text.",
        }
        return httpx.Response(
            200,
            json={"issues": [issue], "startAt": 0, "maxResults": 100, "total": 1},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.search_issues("project = PROJ", include_description=True)
    finally:
        await client.aclose()
    assert "description" in seen_fields[0]
    assert len(result) == 1
    assert result[0]["description"] == "Full issue description text."


@pytest.mark.asyncio
async def test_search_issues_include_description_default_false() -> None:
    """Default call: no description in fields param, no description in mapped issues."""
    seen_fields: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_fields.append(dict(request.url.params)["fields"])
        issue = dict(_issue("PROJ-0"))
        # Server returns description even when it was not requested —
        # the mapping must NOT include it when the flag is False.
        issue["fields"] = {
            **issue["fields"],  # type: ignore[dict-item]
            "description": "Should be dropped.",
        }
        return httpx.Response(
            200,
            json={"issues": [issue], "startAt": 0, "maxResults": 100, "total": 1},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.search_issues("project = PROJ")
    finally:
        await client.aclose()
    assert "description" not in seen_fields[0]
    assert len(result) == 1
    assert "description" not in result[0]


# --- list_user_tasks: same /search envelope, JQL assignee -------------------


@pytest.mark.asyncio
async def test_list_user_tasks_single_page() -> None:
    issues = [_issue(f"USR-{i}") for i in range(2)]

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        assert "assignee" in params["jql"]
        return httpx.Response(
            200,
            json={"issues": issues, "startAt": 0, "maxResults": 100, "total": 2},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.list_user_tasks("alice")
    finally:
        await client.aclose()
    assert len(result) == 2
    assert [r["key"] for r in result] == ["USR-0", "USR-1"]


@pytest.mark.asyncio
async def test_list_user_tasks_multi_page_accumulates() -> None:
    """A user with more tasks than the server page size gets all of them, up to the cap.

    The client requests page_size=max_results (bounded to 100), but the server
    here returns only 2 per request (its own ceiling), so the client must follow
    the startAt/total paging until the cap is reached. max_results=4 == total so
    accumulation is observed across two pages.
    """
    all_issues = [_issue(f"USR-{i}") for i in range(4)]
    seen_start_at: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_at = int(dict(request.url.params)["startAt"])
        seen_start_at.append(dict(request.url.params)["startAt"])
        page = all_issues[start_at : start_at + 2]
        return httpx.Response(
            200,
            json={"issues": page, "startAt": start_at, "maxResults": 2, "total": 4},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.list_user_tasks("alice", max_results=4)
    finally:
        await client.aclose()
    assert len(result) == 4
    assert [r["key"] for r in result] == ["USR-0", "USR-1", "USR-2", "USR-3"]
    # Pages requested at startAt 0 and 2; third not needed (2+2 >= 4).
    assert seen_start_at == ["0", "2"]


@pytest.mark.asyncio
async def test_list_user_tasks_cap_stops_pagination() -> None:
    """max_results is a hard total cap — pagination stops once it is reached.

    Regression guard for code-review #2: previously max_results was only the
    page size with no upper bound, so the client could page forever. Now an
    explicit small cap must truncate the result and never request a third page.
    """
    all_issues = [_issue(f"USR-{i}") for i in range(6)]
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start_at = int(dict(request.url.params)["startAt"])
        requested_pages.append(dict(request.url.params)["startAt"])
        page = all_issues[start_at : start_at + 2]
        return httpx.Response(
            200,
            json={"issues": page, "startAt": start_at, "maxResults": 2, "total": 6},
        )

    client = _client_with_transport(handler)
    try:
        result = await client.list_user_tasks("alice", max_results=2)
    finally:
        await client.aclose()
    # Cap honoured: exactly 2 returned, and only the first page was fetched.
    assert len(result) == 2
    assert [r["key"] for r in result] == ["USR-0", "USR-1"]
    assert requested_pages == ["0"]


@pytest.mark.asyncio
async def test_list_user_tasks_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issues": [], "startAt": 0, "maxResults": 100, "total": 0})

    client = _client_with_transport(handler)
    try:
        result = await client.list_user_tasks("nobody")
    finally:
        await client.aclose()
    assert result == []


# --- search_users: bare-list response shape (no envelope) --------------------


@pytest.mark.asyncio
async def test_search_users_single_page() -> None:
    users = [
        {"name": "alice", "key": "ALICE", "displayName": "Alice", "active": True},
        {"name": "bob", "key": "BOB", "displayName": "Bob", "active": True},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rest/api/2/user/search")
        return httpx.Response(200, json=users)

    client = _client_with_transport(handler)
    try:
        result = await client.search_users("a")
    finally:
        await client.aclose()
    assert len(result) == 2
    assert result[0]["name"] == "alice"


@pytest.mark.asyncio
async def test_search_users_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _client_with_transport(handler)
    try:
        result = await client.search_users("zzz")
    finally:
        await client.aclose()
    assert result == []


# --- create_issue: POST /rest/api/2/issue ------------------------------------


@pytest.mark.asyncio
async def test_create_issue_happy_path() -> None:
    """POST payload carries project/summary/issuetype; response is normalized."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            201,
            json={
                "id": "10001",
                "key": "DEVOPS-200",
                "self": "https://jira.test.example/rest/api/2/issue/10001",
            },
        )

    client = _client_with_transport(handler)
    try:
        result = await client.create_issue("devops", "Fix login flow")
    finally:
        await client.aclose()
    assert seen["path"].endswith("/rest/api/2/issue")
    fields = seen["payload"]["fields"]
    assert fields["project"] == {"key": "DEVOPS"}  # uppercased
    assert fields["summary"] == "Fix login flow"
    assert fields["issuetype"] == {"name": "Task"}  # default
    assert "parent" not in fields  # no parent_key -> no parent field
    assert result == {
        "key": "DEVOPS-200",
        "id": "10001",
        "self": "https://jira.test.example/rest/api/2/issue/10001",
    }


@pytest.mark.asyncio
async def test_create_issue_with_parent_includes_parent_field() -> None:
    """parent_key set -> 'parent': {'key': ...} present in the payload."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(201, json={"id": "10002", "key": "DEVOPS-201", "self": "u"})

    client = _client_with_transport(handler)
    try:
        result = await client.create_issue(
            "DEVOPS",
            "Subtask: fix flaky test",
            description="Stabilise the suite",
            issuetype="Sub-task",
            parent_key="devops-100",
        )
    finally:
        await client.aclose()
    fields = seen["payload"]["fields"]
    assert fields["parent"] == {"key": "DEVOPS-100"}  # uppercased
    assert fields["issuetype"] == {"name": "Sub-task"}
    assert fields["description"] == "Stabilise the suite"
    assert result["key"] == "DEVOPS-201"


@pytest.mark.asyncio
async def test_create_issue_empty_project_raises() -> None:
    """Empty project_key is rejected client-side without an HTTP call."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(201, json={"id": "1", "key": "X-1", "self": "u"})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(JiraTempoError, match="project_key must be a non-empty"):
            await client.create_issue("  ", "Some summary")
    finally:
        await client.aclose()
    assert calls == []  # no HTTP request reached the transport


@pytest.mark.asyncio
async def test_create_issue_empty_summary_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "1", "key": "X-1", "self": "u"})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(JiraTempoError, match="summary must be a non-empty"):
            await client.create_issue("DEVOPS", "")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_issue_empty_issuetype_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": "1", "key": "X-1", "self": "u"})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(JiraTempoError, match="issuetype must be a non-empty"):
            await client.create_issue("DEVOPS", "S", issuetype=" ")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_issue_api_error_propagates() -> None:
    """HTTP 400 from Jira surfaces as JiraTempoError with the redacted body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorMessages": ["issuetype not found"]})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(JiraTempoError, match="400"):
            await client.create_issue("DEVOPS", "S", issuetype="NoSuchType")
    finally:
        await client.aclose()


# --- add_issue_comment: POST /rest/api/2/issue/{key}/comment -----------------


@pytest.mark.asyncio
async def test_add_issue_comment_happy_path() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            201,
            json={
                "id": "10500",
                "self": "https://jira.test.example/rest/api/2/issue/10001/comment/10500",
                "body": "Investigation started.",
            },
        )

    client = _client_with_transport(handler)
    try:
        result = await client.add_issue_comment("DEVOPS-100", "Investigation started.")
    finally:
        await client.aclose()
    assert seen["path"].endswith("/rest/api/2/issue/DEVOPS-100/comment")
    assert seen["payload"] == {"body": "Investigation started."}
    assert result == {
        "id": "10500",
        "self": "https://jira.test.example/rest/api/2/issue/10001/comment/10500",
        "body": "Investigation started.",
    }


@pytest.mark.asyncio
async def test_add_issue_comment_empty_rejected() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(201, json={"id": "1", "self": "u", "body": "x"})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(JiraTempoError, match="comment must be a non-empty"):
            await client.add_issue_comment("DEVOPS-100", "   ")
    finally:
        await client.aclose()
    assert calls == []  # no HTTP request reached the transport


@pytest.mark.asyncio
async def test_add_issue_comment_api_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})

    client = _client_with_transport(handler)
    try:
        with pytest.raises(JiraTempoError, match="404"):
            await client.add_issue_comment("DEVOPS-999", "hello")
    finally:
        await client.aclose()
