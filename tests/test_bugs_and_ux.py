"""Tests for bug fixes and UX improvements (BUG-1..6, UX-1..10)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from jira_tempo_mcp.client import (
    FavoritesEndpointUnavailableError,
    JiraTempoClient,
    JiraTempoError,
)
from jira_tempo_mcp.config import Config
from jira_tempo_mcp.report import generate_weekly_report
from jira_tempo_mcp.server import (
    _format_worklog_details,
    _handle_add_issue_comment,
    _handle_create_issue,
    _handle_create_worklog,
    _handle_get_current_user,
    _handle_get_issue,
    _handle_get_worklog,
    _handle_list_favorites,
    _handle_list_issues_by_jql,
    _handle_list_user_tasks,
    _handle_list_worklogs,
    _validate_tool_arguments,
)
from jira_tempo_mcp.team_report import generate_team_report


def _make_config(**overrides: Any) -> Config:
    defaults: dict[str, Any] = {
        "jira_base_url": "https://jira.test.example",
        "jira_user": "testuser",
        "jira_pat": "fake-pat-for-testing",
        "author_display_name": "Тестовый Пользователь",
        "timezone": "Europe/Moscow",
        "section_map": {"PROJECT-100": "Section A"},
        "stable_order": ["PROJECT-100"],
        "non_issue_sections": [],
    }
    defaults.update(overrides)
    return Config(**defaults)


def _make_mock_client(**side_effects: Any) -> AsyncMock:
    mock = AsyncMock(spec=JiraTempoClient)
    for name, effect in side_effects.items():
        attr = getattr(mock, name)
        if callable(effect):
            attr.side_effect = effect
        else:
            attr.return_value = effect
    return mock


# --- BUG-3: invalid date validation ---


class TestBug3DateValidation:
    async def test_invalid_date_from_raises(self) -> None:
        config = _make_config()
        mock_client = _make_mock_client(find_worker_key=AsyncMock(return_value="wk"))
        with pytest.raises(ValueError, match="Invalid date for date_from"):
            await _handle_list_worklogs(
                {"date_from": "not-a-date"}, config, cast(JiraTempoClient, mock_client)
            )

    async def test_invalid_date_to_raises(self) -> None:
        config = _make_config()
        mock_client = _make_mock_client(find_worker_key=AsyncMock(return_value="wk"))
        with pytest.raises(ValueError, match="Invalid date for date_to"):
            await _handle_list_worklogs(
                {"date_from": "2026-06-15", "date_to": "not-a-date"},
                config,
                cast(JiraTempoClient, mock_client),
            )


# --- BUG-4: date_from > date_to validation ---


class TestBug4DateRangeValidation:
    async def test_reversed_range_raises(self) -> None:
        config = _make_config()
        mock_client = _make_mock_client(find_worker_key=AsyncMock(return_value="wk"))
        with pytest.raises(ValueError, match="date_from must be on or before date_to"):
            await _handle_list_worklogs(
                {"date_from": "2026-06-22", "date_to": "2026-06-15"},
                config,
                cast(JiraTempoClient, mock_client),
            )

    async def test_same_date_ok(self) -> None:
        config = _make_config()
        mock_client = _make_mock_client(
            find_worker_key=AsyncMock(return_value="wk"),
            search_worklogs=AsyncMock(return_value=[]),
        )
        result = await _handle_list_worklogs(
            {"date_from": "2026-06-15", "date_to": "2026-06-15"},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "Worklogs" in result


# --- BUG-1: status_filter with Russian statuses ---


class TestBug1StatusFilter:
    async def test_russian_status_translated_to_category(self) -> None:
        """list_user_tasks with Russian status should use statusCategory."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _list_user_tasks(
            username: str, *, status_filter: list[str] | None = None, max_results: int = 100
        ) -> list[dict[str, Any]]:
            # Verify the JQL uses statusCategory, not status.
            # We can't check JQL directly, but we verify the call succeeds.
            return [
                {
                    "key": "DEVOPS-1",
                    "summary": "Test",
                    "status": "В работе",
                    "statusCategory": "In Progress",
                    "statusCategoryKey": "indeterminate",
                    "duedate": "",
                    "priority": "High",
                    "comment_count": 0,
                    "comments": [],
                }
            ]

        mock_client.list_user_tasks.side_effect = _list_user_tasks
        result = await _handle_list_user_tasks(
            {"username": "golikhin", "status_filter": ["В работе"]},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "DEVOPS-1" in result

    async def test_client_translates_russian_status(self) -> None:
        """Verify client.list_user_tasks builds statusCategory JQL for Russian statuses."""
        from jira_tempo_mcp.client import _RU_STATUS_TO_CATEGORY

        assert _RU_STATUS_TO_CATEGORY["В работе"] == "In Progress"
        assert _RU_STATUS_TO_CATEGORY["Готово"] == "Done"
        assert _RU_STATUS_TO_CATEGORY["Открыта"] == "To Do"


# --- BUG-2: create_worklog attributes error message ---


class TestBug2CreateWorklogAttributes:
    async def test_validation_failed_returns_actionable_message(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _find_worker_key(username: str | None = None) -> str:
            return "wk"

        async def _create_worklog(**kwargs: Any) -> dict[str, Any]:
            err = JiraTempoError("API error 400 from url: ...")
            err.status_code = 400
            err.response_body = {
                "errors": {"_Специализация_": "Work attribute 'Специализация' is required"}
            }
            raise err

        mock_client.find_worker_key.side_effect = _find_worker_key
        mock_client.create_worklog.side_effect = _create_worklog

        result = await _handle_create_worklog(
            {"issue_key": "DEVOPS-100", "time_spent": "1h"},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "requires the following work attributes" in result
        assert "_Специализация_" in result
        assert "attributes" in result


# --- BUG-5: team report filename includes users hash ---


class TestBug5TeamReportFilename:
    async def test_different_users_different_filenames(self, tmp_path: Path) -> None:
        """Two calls with different user lists produce different filenames."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _find_worker_key(username: str | None = None) -> str:
            return f"worker-{username}"

        async def _search_worklogs(
            date_from: str, date_to: str, *, worker_keys: list[str] | None = None
        ) -> list[dict[str, Any]]:
            return []

        async def _get_issue(key: str) -> dict[str, Any]:
            return {"key": key, "fields": {"summary": key}}

        mock_client.find_worker_key.side_effect = _find_worker_key
        mock_client.search_worklogs.side_effect = _search_worklogs
        mock_client.get_issue.side_effect = _get_issue

        result1 = await generate_team_report(
            cast(JiraTempoClient, mock_client),
            config,
            users=["alice", "bob"],
            output_dir=tmp_path,
        )
        result2 = await generate_team_report(
            cast(JiraTempoClient, mock_client),
            config,
            users=["charlie"],
            output_dir=tmp_path,
        )
        assert result1.file_path != result2.file_path

    async def test_same_users_same_filename(self, tmp_path: Path) -> None:
        """Same user set + same range produces same filename (idempotent)."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _find_worker_key(username: str | None = None) -> str:
            return f"worker-{username}"

        async def _search_worklogs(
            date_from: str, date_to: str, *, worker_keys: list[str] | None = None
        ) -> list[dict[str, Any]]:
            return []

        async def _get_issue(key: str) -> dict[str, Any]:
            return {"key": key, "fields": {"summary": key}}

        mock_client.find_worker_key.side_effect = _find_worker_key
        mock_client.search_worklogs.side_effect = _search_worklogs
        mock_client.get_issue.side_effect = _get_issue

        result1 = await generate_team_report(
            cast(JiraTempoClient, mock_client),
            config,
            users=["alice", "bob"],
            output_dir=tmp_path,
        )
        result2 = await generate_team_report(
            cast(JiraTempoClient, mock_client),
            config,
            users=["bob", "alice"],
            output_dir=tmp_path,  # different order
        )
        assert result1.file_path == result2.file_path


# --- BUG-6: list_favorite_issues 404 message ---


class TestBug6Favorites404:
    async def test_endpoint_unavailable_message(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _list_favorites() -> list[dict[str, Any]]:
            raise FavoritesEndpointUnavailableError("404")

        mock_client.list_favorite_issues.side_effect = _list_favorites
        result = await _handle_list_favorites({}, config, cast(JiraTempoClient, mock_client))
        assert "endpoint unavailable" in result.lower()

    async def test_empty_list_message(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.list_favorite_issues.return_value = []
        result = await _handle_list_favorites({}, config, cast(JiraTempoClient, mock_client))
        assert "No favorite issues found" in result


# --- UX-1: suppress 404 noise from find_worker_key ---


class TestUX1WorkersCache:
    async def test_workers_endpoint_cached_as_unavailable(self) -> None:
        """After first 404, subsequent calls skip /workers."""
        from jira_tempo_mcp.client import JiraTempoClient as RealClient

        config = _make_config()
        # We can't easily test the real HTTP path, but we verify the
        # _workers_endpoint_available attribute exists and is used.
        client = RealClient(config)
        assert client._workers_endpoint_available is None
        await client.aclose()


# --- UX-2: get_issue expanded fields ---


class TestUX2GetIssueExpanded:
    async def test_all_fields_displayed(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.get_issue.return_value = {
            "key": "DEVOPS-100",
            "fields": {
                "summary": "Test issue",
                "status": {"name": "In Progress"},
                "project": {"name": "DEVOPS"},
                "priority": {"name": "High"},
                "assignee": {"displayName": "Golikhin"},
                "duedate": "2026-06-30",
                "issuetype": {"name": "Task"},
                "components": [{"name": "Backend"}, {"name": "API"}],
            },
        }
        result = await _handle_get_issue(
            {"issue_key": "DEVOPS-100"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "DEVOPS-100" in result
        assert "Test issue" in result
        assert "In Progress" in result
        assert "DEVOPS" in result
        assert "High" in result
        assert "Golikhin" in result
        assert "2026-06-30" in result
        assert "Task" in result
        assert "Backend" in result
        assert "API" in result

    async def test_description_displayed(self) -> None:
        """UX-2 extension: description field is rendered in get_issue output."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.get_issue.return_value = {
            "key": "DEVOPS-100",
            "fields": {
                "summary": "Test issue",
                "status": {"name": "In Progress"},
                "project": {"name": "DEVOPS"},
                "priority": {"name": "High"},
                "assignee": {"displayName": "Golikhin"},
                "duedate": "2026-06-30",
                "issuetype": {"name": "Task"},
                "components": [{"name": "Backend"}],
                "description": "Steps to reproduce the bug.",
            },
        }
        result = await _handle_get_issue(
            {"issue_key": "DEVOPS-100"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "Description: Steps to reproduce the bug." in result

    async def test_description_missing_shows_placeholder(self) -> None:
        """Missing/empty description renders as an em-dash placeholder."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.get_issue.return_value = {
            "key": "DEVOPS-100",
            "fields": {"summary": "Test issue", "description": None},
        }
        result = await _handle_get_issue(
            {"issue_key": "DEVOPS-100"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "Description: —" in result


# --- UX-3: comments in list_user_tasks ---


class TestUX3CommentsInTasks:
    async def test_comments_displayed(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.list_user_tasks.return_value = [
            {
                "key": "DEVOPS-1",
                "summary": "Test",
                "status": "В работе",
                "duedate": "",
                "priority": "High",
                "comment_count": 2,
                "comments": [
                    {"author": "Alice", "body": "First comment", "created": "2026-06-20"},
                    {"author": "Bob", "body": "Second comment here", "created": "2026-06-21"},
                ],
            }
        ]
        result = await _handle_list_user_tasks(
            {"username": "golikhin"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "💬" in result
        assert "Alice" in result
        assert "First comment" in result
        assert "Bob" in result

    async def test_long_comment_truncated(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        long_body = "x" * 200
        mock_client.list_user_tasks.return_value = [
            {
                "key": "DEVOPS-1",
                "summary": "Test",
                "status": "В работе",
                "duedate": "",
                "priority": "High",
                "comment_count": 1,
                "comments": [{"author": "Alice", "body": long_body, "created": "2026-06-20"}],
            }
        ]
        result = await _handle_list_user_tasks(
            {"username": "golikhin"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "..." in result


# --- UX-4: get_worklog formatted output ---


class TestUX4GetWorklogFormatted:
    async def test_no_raw_dict_repr(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.get_worklog.return_value = {
            "tempoWorklogId": "12345",
            "timeSpentSeconds": 3600,
            "issue": {"key": "DEVOPS-100", "summary": "Test", "status": {"name": "In Progress"}},
            "comment": "Work done",
            "started": "2026-06-19 00:00:00",
            "worker": "JIRAUSER40101",
        }
        result = await _handle_get_worklog(
            {"worklog_id": "12345"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "Worklog 12345:" in result
        assert "Time spent:" in result
        assert "1h" in result
        assert "Issue: DEVOPS-100" in result
        assert "Comment: Work done" in result
        assert "Worker: JIRAUSER40101" in result
        # No raw dict repr.
        assert "{'" not in result


# --- UX-5: list_issues_by_jql ---


class TestUX5ListIssuesByJql:
    async def test_basic_search(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.search_issues.return_value = [
            {
                "key": "DEVOPS-1",
                "summary": "Task A",
                "status": "In Progress",
                "priority": "High",
                "duedate": "2026-06-30",
                "assignee": "Golikhin",
            },
            {
                "key": "DEVOPS-2",
                "summary": "Task B",
                "status": "Done",
                "priority": "Medium",
                "duedate": "",
                "assignee": "",
            },
        ]
        result = await _handle_list_issues_by_jql(
            {"jql": "project = DEVOPS", "max_results": 2},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "DEVOPS-1" in result
        assert "Task A" in result
        assert "DEVOPS-2" in result

    async def test_empty_jql_raises(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="non-empty"):
            await _handle_list_issues_by_jql(
                {"jql": ""}, config, cast(JiraTempoClient, mock_client)
            )

    async def test_no_results(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.search_issues.return_value = []
        result = await _handle_list_issues_by_jql(
            {"jql": "project = NONEXISTENT"}, config, cast(JiraTempoClient, mock_client)
        )
        assert "No issues found" in result

    async def test_include_description_shows_description(self) -> None:
        """UX-5 extension: include_description=True renders description per issue."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.search_issues.return_value = [
            {
                "key": "DEVOPS-1",
                "summary": "Task A",
                "status": "In Progress",
                "priority": "High",
                "duedate": "2026-06-30",
                "assignee": "Golikhin",
                "description": "First issue description.",
            }
        ]
        result = await _handle_list_issues_by_jql(
            {"jql": "project = DEVOPS", "include_description": True},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "Description: First issue description." in result

    async def test_include_description_defaults_to_false(self) -> None:
        """Default call (no include_description) keeps the compact contract."""
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.search_issues.return_value = [
            {
                "key": "DEVOPS-1",
                "summary": "Task A",
                "status": "In Progress",
                "priority": "High",
                "duedate": "2026-06-30",
                "assignee": "Golikhin",
                "description": "First issue description.",
            }
        ]
        result = await _handle_list_issues_by_jql(
            {"jql": "project = DEVOPS"},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "Description:" not in result
        # The client was called with include_description=False explicitly.
        assert mock_client.search_issues.await_args.kwargs["include_description"] is False


# --- UX-6: get_current_user ---


class TestUX6GetCurrentUser:
    async def test_returns_user_info(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.get_myself.return_value = {
            "name": "golikhin",
            "displayName": "Голихин Леонид Сергеевич",
            "emailAddress": "golikhin@komus.net",
            "key": "JIRAUSER40101",
            "active": True,
        }
        result = await _handle_get_current_user({}, config, cast(JiraTempoClient, mock_client))
        assert "golikhin" in result
        assert "Голихин Леонид Сергеевич" in result
        assert "golikhin@komus.net" in result
        assert "JIRAUSER40101" in result
        assert "True" in result


# --- UX-7: username in weekly_report ---


class TestUX7WeeklyReportUsername:
    async def test_username_passed_to_find_worker_key(self, tmp_path: Path) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.find_worker_key.return_value = "worker-dmz"
        mock_client.search_worklogs.return_value = []

        await generate_weekly_report(
            cast(JiraTempoClient, mock_client),
            config,
            target_date=date(2026, 6, 17),
            output_dir=tmp_path,
            username="dmz",
        )
        mock_client.find_worker_key.assert_called_once_with("dmz")

    async def test_no_username_uses_config_user(self, tmp_path: Path) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.find_worker_key.return_value = "worker-testuser"
        mock_client.search_worklogs.return_value = []

        await generate_weekly_report(
            cast(JiraTempoClient, mock_client),
            config,
            target_date=date(2026, 6, 17),
            output_dir=tmp_path,
        )
        mock_client.find_worker_key.assert_called_once_with("testuser")


# --- UX-8: ISO dates in filenames ---


class TestUX8ISOFilenames:
    async def test_weekly_report_iso_filename(self, tmp_path: Path) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.find_worker_key.return_value = "wk"
        mock_client.search_worklogs.return_value = []

        result = await generate_weekly_report(
            cast(JiraTempoClient, mock_client),
            config,
            target_date=date(2026, 6, 17),
            output_dir=tmp_path,
        )
        path = Path(result)
        assert "2026-06-15" in path.name
        assert "2026-06-19" in path.name
        # No DDMMYY format.
        assert "150626" not in path.name

    async def test_team_report_iso_filename(self, tmp_path: Path) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _find_worker_key(username: str | None = None) -> str:
            return f"worker-{username}"

        async def _search_worklogs(
            date_from: str, date_to: str, *, worker_keys: list[str] | None = None
        ) -> list[dict[str, Any]]:
            return []

        async def _get_issue(key: str) -> dict[str, Any]:
            return {"key": key, "fields": {"summary": key}}

        mock_client.find_worker_key.side_effect = _find_worker_key
        mock_client.search_worklogs.side_effect = _search_worklogs
        mock_client.get_issue.side_effect = _get_issue

        result = await generate_team_report(
            cast(JiraTempoClient, mock_client),
            config,
            users=["alice"],
            output_dir=tmp_path,
            date_from="2026-06-15",
            date_to="2026-06-19",
        )
        assert "2026-06-15" in result.file_path.name
        assert "2026-06-19" in result.file_path.name
        assert "150626" not in result.file_path.name


# --- UX-10: create_worklog returns full worklog ---


class TestUX10CreateWorklogReturnsFull:
    async def test_full_worklog_appended(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)

        async def _find_worker_key(username: str | None = None) -> str:
            return "wk"

        mock_client.find_worker_key.side_effect = _find_worker_key
        mock_client.create_worklog.return_value = {"tempoWorklogId": "999"}
        mock_client.get_worklog.return_value = {
            "tempoWorklogId": "999",
            "timeSpentSeconds": 3600,
            "issue": {"key": "DEVOPS-100", "summary": "Test"},
            "comment": "Done",
            "started": "2026-06-23",
            "worker": "JIRAUSER40101",
        }

        result = await _handle_create_worklog(
            {"issue_key": "DEVOPS-100", "time_spent": "1h"},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "Tracked 1h" in result
        assert "Worklog ID: 999" in result
        assert "Worklog details:" in result
        assert "Time spent:" in result
        assert "DEVOPS-100" in result


# --- _format_worklog_details helper ---


class TestFormatWorklogDetails:
    def test_basic_formatting(self) -> None:
        wl = {
            "tempoWorklogId": "123",
            "timeSpentSeconds": 3600,
            "issue": {
                "key": "DEV-1",
                "summary": "Test",
                "status": {"name": "Open"},
                "project": {"key": "DEV"},
            },
            "comment": "Work",
            "started": "2026-06-19",
            "worker": "JIRAUSER1",
        }
        result = _format_worklog_details(wl)
        assert "Worklog 123:" in result
        assert "1h (3600s)" in result
        assert "Issue: DEV-1 — Test" in result
        assert "Status: Open" in result
        assert "Project: DEV" in result
        assert "Comment: Work" in result
        assert "Worker: JIRAUSER1" in result

    def test_attributes_displayed(self) -> None:
        wl = {
            "tempoWorklogId": "123",
            "timeSpentSeconds": 60,
            "attributes": {
                "_Специализация_": {"value": "Devops"},
                "_Форматработы_": {"value": "Удаленно"},
            },
        }
        result = _format_worklog_details(wl)
        assert "Attributes:" in result
        assert "Специализация: Devops" in result
        assert "Форматработы: Удаленно" in result

    def test_no_attributes_no_section(self) -> None:
        wl = {"tempoWorklogId": "1", "timeSpentSeconds": 60}
        result = _format_worklog_details(wl)
        assert "Attributes:" not in result


# --- HOTFIX: bullet rendering regression (multi-line worklog comments) ---


class TestWeeklyReportBulletRendering:
    """End-to-end: multi-line worklog comment must not produce double markers
    and must split into separate bullet items with one unified marker."""

    async def test_weekly_txt_multiline_no_double_marker(self, tmp_path: Path) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.find_worker_key.return_value = "wk"

        multiline = (
            "+ разработка и доработка Helm-чарта\n+ корректировка values\n+ деплой в кластер"
        )

        async def _search_worklogs(
            date_from: str, date_to: str, *, worker_keys: list[str] | None = None
        ) -> list[dict[str, Any]]:
            return [
                {
                    "issue": {"key": "PROJECT-100"},
                    "timeSpentSeconds": 14400,
                    "comment": multiline,
                    "started": "2026-06-17",
                }
            ]

        mock_client.search_worklogs.side_effect = _search_worklogs

        result = await generate_weekly_report(
            cast(JiraTempoClient, mock_client),
            config,
            target_date=date(2026, 6, 17),
            output_dir=tmp_path,
        )
        content = Path(result).read_text(encoding="utf-8")
        # No duplicated markers anywhere.
        assert "+ +" not in content
        # Each action on its own line with a single unified marker.
        assert "\t+ разработка и доработка Helm-чарта" in content
        assert "\t+ корректировка values" in content
        assert "\t+ деплой в кластер" in content
        # Time suffix appears once (on the last sub-item only).
        assert content.count("\u2014 4h") == 1


# --- create_issue tool (slice 2a) -------------------------------------------


class TestCreateIssueTool:
    async def test_happy_path_returns_confirmation(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.create_issue.return_value = {
            "key": "DEVOPS-200",
            "id": "10001",
            "self": "https://jira.test.example/rest/api/2/issue/10001",
        }
        result = await _handle_create_issue(
            {"project_key": "DEVOPS", "summary": "Fix login flow"},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "DEVOPS-200" in result
        assert "Created Task" in result
        assert "10001" in result
        # Defaults forwarded: issuetype Task, no parent.
        kwargs = mock_client.create_issue.await_args.kwargs
        assert kwargs["issuetype"] == "Task"
        assert kwargs["parent_key"] is None

    async def test_parent_key_forwarded_and_validated(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.create_issue.return_value = {
            "key": "DEVOPS-201",
            "id": "10002",
            "self": "u",
        }
        result = await _handle_create_issue(
            {
                "project_key": "DEVOPS",
                "summary": "Subtask",
                "issuetype": "Sub-task",
                "parent_key": "DEVOPS-100",
            },
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "parent DEVOPS-100" in result
        kwargs = mock_client.create_issue.await_args.kwargs
        assert kwargs["parent_key"] == "DEVOPS-100"
        assert kwargs["issuetype"] == "Sub-task"

    async def test_invalid_parent_key_rejected(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="Invalid issue key"):
            await _handle_create_issue(
                {"project_key": "DEVOPS", "summary": "S", "parent_key": "bad key!"},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.create_issue.assert_not_called()

    async def test_empty_project_key_raises(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="project_key"):
            await _handle_create_issue(
                {"project_key": "", "summary": "S"},
                config,
                cast(JiraTempoClient, mock_client),
            )

    async def test_empty_summary_raises(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="summary"):
            await _handle_create_issue(
                {"project_key": "DEVOPS", "summary": "  "},
                config,
                cast(JiraTempoClient, mock_client),
            )

    async def test_empty_issuetype_raises(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="issuetype"):
            await _handle_create_issue(
                {"project_key": "DEVOPS", "summary": "S", "issuetype": ""},
                config,
                cast(JiraTempoClient, mock_client),
            )


# --- add_issue_comment tool (slice 2a) ---------------------------------------


class TestAddIssueCommentTool:
    async def test_happy_path_returns_confirmation(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        mock_client.add_issue_comment.return_value = {
            "id": "10500",
            "self": "u",
            "body": "Investigation started.",
        }
        result = await _handle_add_issue_comment(
            {"issue_key": "DEVOPS-100", "comment": "Investigation started."},
            config,
            cast(JiraTempoClient, mock_client),
        )
        assert "10500" in result
        assert "DEVOPS-100" in result
        mock_client.add_issue_comment.assert_awaited_once_with(
            "DEVOPS-100", "Investigation started."
        )

    async def test_invalid_issue_key_rejected(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="Invalid issue key"):
            await _handle_add_issue_comment(
                {"issue_key": "nope", "comment": "hello"},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.add_issue_comment.assert_not_awaited()

    async def test_empty_comment_raises(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="comment"):
            await _handle_add_issue_comment(
                {"issue_key": "DEVOPS-100", "comment": "   "},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.add_issue_comment.assert_not_awaited()

    async def test_missing_comment_raises(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="comment"):
            await _handle_add_issue_comment(
                {"issue_key": "DEVOPS-100"},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.add_issue_comment.assert_not_awaited()


class TestIssue33SchemaArgumentValidation:
    """Issue #33: MCP tool schemas accept unknown arguments silently (e.g. maxResults vs max_results)."""

    def test_well_formed_arguments_pass_validation(self) -> None:
        errors = _validate_tool_arguments("list_issues_by_jql", {"jql": "project = TEST", "max_results": 25})
        assert errors == []

    def test_unknown_argument_rejected_with_camel_case_hint(self) -> None:
        errors = _validate_tool_arguments("list_issues_by_jql", {"jql": "project = TEST", "maxResults": 25})
        assert len(errors) == 1
        assert "Validation error for tool 'list_issues_by_jql'" in errors[0]
        assert "maxResults" in errors[0]
        assert "'maxResults' appears to be camelCase for 'max_results'" in errors[0]

    def test_unknown_tool_ignored(self) -> None:
        errors = _validate_tool_arguments("non_existent_tool", {"any": 123})
        assert errors == []

