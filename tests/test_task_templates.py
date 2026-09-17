"""Tests for the task-template system (parent issue + child subtasks from YAML).

Covers:
- Schema validation (valid + invalid YAML shapes)
- Built-in template loading (standup-preparation)
- list_issue_templates handler
- create_issue_from_template handler: happy path via mock transport,
  partial failure (child N fails -> created-so-far + failed flag, no rollback)
- Override directory precedence (user file replaces built-in by name)
- Jinja2 rendering of summary into child descriptions
- Registry precedence via build_task_template_registry
"""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from jira_tempo_mcp.client import JiraTempoClient, JiraTempoError
from jira_tempo_mcp.config import Config
from jira_tempo_mcp.server import (
    _handle_create_issue_from_template,
    _handle_list_issue_templates,
)
from jira_tempo_mcp.task_templates import (
    TaskTemplate,
    build_task_template_registry,
    discover_task_template_overrides,
    load_builtin_task_templates,
    parse_task_template,
    render_context,
)


def _make_config(**overrides: Any) -> Config:
    defaults: dict[str, Any] = {
        "jira_base_url": "https://jira.test.example",
        "jira_user": "testuser",
        "jira_pat": "fake-pat-for-testing",
        "timezone": "Europe/Moscow",
    }
    defaults.update(overrides)
    return Config(**defaults)


_VALID_TEMPLATE_YAML = """
name: demo-template
title: "{{ summary }}"
description: "Parent for {{ summary }}{%- if user_description %} — {{ user_description }}{% endif %}"
project_key: null
parent_issuetype: Task
child_issuetype: Sub-task
tasks:
  - tag: "[alpha]"
    summary: "First child for {{ summary }}"
    description: "Detailed: {{ user_description }}"
  - summary: "Second child"
"""

# --- Schema validation -------------------------------------------------------


class TestTaskTemplateSchema:
    def test_valid_template_parses(self) -> None:
        tpl = parse_task_template(
            {
                "name": "demo",
                "title": "{{ summary }}",
                "tasks": [{"summary": "Child A"}],
            },
            source="<test>",
        )
        assert tpl.name == "demo"
        assert tpl.parent_issuetype == "Task"
        assert tpl.child_issuetype == "Sub-task"
        assert len(tpl.tasks) == 1
        assert tpl.tasks[0].tag == ""
        assert tpl.tasks[0].description == ""

    def test_invalid_yaml_name_pattern_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid task template"):
            parse_task_template(
                {"name": "Bad Name!", "title": "t", "tasks": [{"summary": "s"}]},
                source="<test>",
            )

    def test_missing_tasks_rejected(self) -> None:
        with pytest.raises(ValueError, match="tasks"):
            parse_task_template({"name": "demo", "title": "t"}, source="<test>")

    def test_empty_tasks_rejected(self) -> None:
        with pytest.raises(ValueError, match="tasks"):
            parse_task_template(
                {"name": "demo", "title": "t", "tasks": []}, source="<test>"
            )

    def test_child_missing_summary_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid task template"):
            parse_task_template(
                {"name": "demo", "title": "t", "tasks": [{"tag": "[x]"}]},
                source="<test>",
            )

    def test_legacy_project_key_field_tolerated(self) -> None:
        """A legacy `project_key` in a template file is ignored, not an error.

        The field was removed from the schema (never read by the handler);
        existing template files that still carry it must keep loading.
        """
        tpl = parse_task_template(
            {
                "name": "demo",
                "title": "t",
                "project_key": "DEVOPS",
                "tasks": [{"summary": "s"}],
            },
            source="<test>",
        )
        assert tpl.name == "demo"
        assert len(tpl.tasks) == 1

    def test_tag_with_newline_rejected(self) -> None:
        with pytest.raises(ValueError, match="tag"):
            parse_task_template(
                {
                    "name": "demo",
                    "title": "t",
                    "tasks": [{"summary": "s", "tag": "line1\nline2"}],
                },
                source="<test>",
            )


# --- Built-in templates -------------------------------------------------------


class TestBuiltinTaskTemplates:
    def test_standup_preparation_loads(self) -> None:
        builtins = load_builtin_task_templates()
        assert "standup-preparation" in builtins
        tpl = builtins["standup-preparation"]
        assert isinstance(tpl, TaskTemplate)
        assert len(tpl.tasks) >= 14

    def test_standup_preparation_covers_expected_tags(self) -> None:
        builtins = load_builtin_task_templates()
        tpl = builtins["standup-preparation"]
        tags = [t.tag for t in tpl.tasks]
        assert tags.count("[terraform]") == 2
        assert tags.count("[ansible]") == 2
        assert tags.count("[kubernetes]") == 2
        assert "[jenkins]" in tags
        assert "[bitbucket]" in tags
        assert "[helpdesk]" in tags
        assert "[argocd]" in tags
        assert "[hybris]" in tags
        assert "[hybris-jenkins]" in tags
        assert "[IMK-Services]" in tags

    def test_build_registry_includes_builtins(self) -> None:
        registry = build_task_template_registry()
        assert "standup-preparation" in registry


# --- Jinja2 rendering ---------------------------------------------------------


class TestTaskTemplateRendering:
    def test_render_context_contains_expected_keys(self) -> None:
        ctx = render_context("Fix the build", "DEVOPS", user_description="urgent")
        assert ctx == {
            "summary": "Fix the build",
            "user_description": "urgent",
            "project_key": "DEVOPS",
            "today": ctx["today"],
        }
        assert len(ctx["today"]) == 10  # ISO date

    def test_summary_renders_into_child_descriptions(self) -> None:
        tpl = parse_task_template(
            {
                "name": "demo",
                "title": "Parent: {{ summary }}",
                "tasks": [
                    {"summary": "Child for {{ summary }}"},
                ],
            },
            source="<test>",
        )
        parent, _desc, children = tpl.render(render_context("deploy nginx", "DEVOPS"))
        assert parent == "Parent: deploy nginx"
        assert children[0][0] == "Child for deploy nginx"

    def test_missing_child_description_duplicates_summary(self) -> None:
        """Owner rule: no description -> duplicate the rendered summary."""
        tpl = parse_task_template(
            {
                "name": "demo",
                "title": "t",
                "tasks": [{"summary": "Only a summary {{ summary }}"}],
            },
            source="<test>",
        )
        _parent, _desc, children = tpl.render(render_context("XYZ", "DEVOPS"))
        assert children[0][0] == "Only a summary XYZ"
        assert children[0][1] == "Only a summary XYZ"

    def test_tag_prefix_rendered_into_summary(self) -> None:
        tpl = parse_task_template(
            {
                "name": "demo",
                "title": "t",
                "tasks": [{"tag": "[terraform]", "summary": "Create IaC"}],
            },
            source="<test>",
        )
        _parent, _desc, children = tpl.render(render_context("s", "DEVOPS"))
        assert children[0][0] == "[terraform] Create IaC"

    def test_sandbox_escape_rejected(self) -> None:
        from jira_tempo_mcp.task_templates import TemplateRenderError

        tpl = parse_task_template(
            {
                "name": "evil",
                "title": "{{ ''.__class__.__init__.__globals__ }}",
                "tasks": [{"summary": "s"}],
            },
            source="<test>",
        )
        with pytest.raises(TemplateRenderError, match="sandbox escape"):
            tpl.render(render_context("s", "DEVOPS"))

    def test_broken_expression_raises_render_error(self) -> None:
        from jira_tempo_mcp.task_templates import TemplateRenderError

        tpl = parse_task_template(
            {"name": "demo", "title": "{{ undefined_var | bad_filter }}", "tasks": [{"summary": "s"}]},
            source="<test>",
        )
        with pytest.raises(TemplateRenderError, match="failed to render"):
            tpl.render(render_context("s", "DEVOPS"))

    def test_user_description_flows_into_parent_description(self) -> None:
        tpl = parse_task_template(
            {
                "name": "demo",
                "title": "t",
                "description": "Context: {{ user_description }}",
                "tasks": [{"summary": "s"}],
            },
            source="<test>",
        )
        parent, desc, _children = tpl.render(
            render_context("s", "DEVOPS", user_description="pilot only")
        )
        assert desc == "Context: pilot only"
        assert parent == "t"


# --- Registry precedence -------------------------------------------------------


class TestTaskTemplateRegistry:
    def test_overrides_empty_dir_yields_nothing(self, tmp_path: Any) -> None:
        assert discover_task_template_overrides(str(tmp_path)) == {}

    def test_overrides_missing_dir_yields_nothing(self, tmp_path: Any) -> None:
        assert discover_task_template_overrides(str(tmp_path / "nope")) == {}

    def test_overrides_empty_config_yields_nothing(self) -> None:
        assert discover_task_template_overrides("") == {}

    def test_overrides_tilde_in_config_dir_expanded(self, tmp_path: Any) -> None:
        """A leading `~` in the override dir is expanded to $HOME."""
        home = os.environ["HOME"]
        try:
            os.environ["HOME"] = str(tmp_path)
            (tmp_path / ".config" / "task-templates").mkdir(parents=True)
            (tmp_path / ".config" / "task-templates" / "homed.yaml").write_text(
                _VALID_TEMPLATE_YAML, encoding="utf-8"
            )
            found = discover_task_template_overrides("~/.config/task-templates")
        finally:
            os.environ["HOME"] = home
        # The tilde path resolved under the temp $HOME and the file was found
        # there — proves expanduser() ran (a literal `~/.config/...` relative
        # path would not exist on disk).
        assert "demo-template" in found

    def test_user_file_adds_template(self, tmp_path: Any) -> None:
        (tmp_path / "extra.yaml").write_text(_VALID_TEMPLATE_YAML, encoding="utf-8")
        found = discover_task_template_overrides(str(tmp_path))
        assert "demo-template" in found
        assert found["demo-template"].child_issuetype == "Sub-task"

    def test_invalid_user_file_skipped_not_fatal(self, tmp_path: Any) -> None:
        (tmp_path / "broken.yaml").write_text("name: [unclosed\n", encoding="utf-8")
        (tmp_path / "good.yaml").write_text(_VALID_TEMPLATE_YAML, encoding="utf-8")
        found = discover_task_template_overrides(str(tmp_path))
        assert list(found) == ["demo-template"]

    def test_non_yaml_files_ignored(self, tmp_path: Any) -> None:
        (tmp_path / "readme.txt").write_text("not a template", encoding="utf-8")
        (tmp_path / "_private.yaml").write_text(_VALID_TEMPLATE_YAML, encoding="utf-8")
        assert discover_task_template_overrides(str(tmp_path)) == {}

    def test_user_override_replaces_builtin_by_name(self, tmp_path: Any) -> None:
        """A user file with the same template name replaces the built-in."""
        override_yaml = """
name: standup-preparation
title: "OVERRIDE {{ summary }}"
tasks:
  - summary: "Only one child"
"""
        (tmp_path / "standup-preparation.yaml").write_text(override_yaml, encoding="utf-8")
        registry = build_task_template_registry(str(tmp_path))
        tpl = registry["standup-preparation"]
        assert tpl.title == "OVERRIDE {{ summary }}"
        assert len(tpl.tasks) == 1

    def test_registry_without_override_dir_keeps_builtin(self) -> None:
        registry = build_task_template_registry("")
        tpl = registry["standup-preparation"]
        assert len(tpl.tasks) >= 14


# --- list_issue_templates handler ----------------------------------------------


class TestListIssueTemplatesTool:
    async def test_lists_builtin_template_with_child_count(self) -> None:
        config = _make_config()
        result = await _handle_list_issue_templates(
            {}, config, cast(JiraTempoClient, AsyncMock(spec=JiraTempoClient))
        )
        assert "Task templates (1):" in result
        assert "standup-preparation" in result
        assert "children=15" in result

    async def test_lists_user_override_too(self, tmp_path: Any) -> None:
        (tmp_path / "extra.yaml").write_text(_VALID_TEMPLATE_YAML, encoding="utf-8")
        config = _make_config(task_template_dir=str(tmp_path))
        result = await _handle_list_issue_templates(
            {}, config, cast(JiraTempoClient, AsyncMock(spec=JiraTempoClient))
        )
        assert "Task templates (2):" in result
        assert "demo-template" in result
        assert "standup-preparation" in result


# --- create_issue_from_template handler (mock transport) ------------------------


def _client_with_transport(handler: Any) -> JiraTempoClient:
    config = _make_config()
    client = JiraTempoClient(config)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=30.0,
        verify=True,
        follow_redirects=False,
    )
    return client


class TestCreateIssueFromTemplateTool:
    async def test_happy_path_creates_parent_and_children(self, tmp_path: Any) -> None:
        """Simple 2-child template: parent + 2 children created in order."""
        (tmp_path / "demo-template.yaml").write_text(_VALID_TEMPLATE_YAML, encoding="utf-8")
        config = _make_config(task_template_dir=str(tmp_path))
        created: list[dict[str, Any]] = []
        counter = {"n": 100}

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            payload = _json.loads(request.content.decode("utf-8"))
            fields = payload["fields"]
            counter["n"] += 1
            key = f"DEVOPS-{counter['n']}"
            created.append({"fields": fields})
            return httpx.Response(201, json={"id": str(counter["n"]), "key": key, "self": "u"})

        client = _client_with_transport(handler)
        try:
            result = await _handle_create_issue_from_template(
                {
                    "template": "demo-template",
                    "project_key": "devops",
                    "summary": "Deploy nginx",
                    "description": "pilot",
                },
                config,
                client,
            )
        finally:
            await client.aclose()

        assert len(created) == 3  # parent + 2 children
        # Parent payload: title from template, issuetype Task.
        assert created[0]["fields"]["summary"] == "Deploy nginx"
        assert created[0]["fields"]["issuetype"] == {"name": "Task"}
        assert "pilot" in created[0]["fields"]["description"]
        # Children: tag prefix + summary; parent_key wired to the parent.
        assert created[1]["fields"]["summary"] == "[alpha] First child for Deploy nginx"
        assert created[1]["fields"]["issuetype"] == {"name": "Sub-task"}
        assert created[1]["fields"]["parent"] == {"key": "DEVOPS-101"}
        assert created[2]["fields"]["parent"] == {"key": "DEVOPS-101"}
        # The second child has no description -> duplicates its summary.
        assert created[2]["fields"]["description"] == "Second child"
        # Output cites parent and both created children.
        assert "DEVOPS-101" in result
        assert "DEVOPS-102" in result
        assert "DEVOPS-103" in result
        assert "All children created successfully." in result

    async def test_builtin_standup_creates_15_children(self) -> None:
        """The built-in standup-preparation template: parent + 15 children."""
        config = _make_config()
        counter = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            counter["n"] += 1
            return httpx.Response(
                201,
                json={"id": str(counter["n"]), "key": f"DEVOPS-{counter['n']}", "self": "u"},
            )

        client = _client_with_transport(handler)
        try:
            result = await _handle_create_issue_from_template(
                {
                    "template": "standup-preparation",
                    "project_key": "DEVOPS",
                    "summary": "Новый стенд ландшафта",
                },
                config,
                client,
            )
        finally:
            await client.aclose()
        assert counter["n"] == 16  # 1 parent + 15 children
        assert "(15/15)" in result
        assert "All children created successfully." in result

    async def test_child_failure_stops_and_reports_partial(self, tmp_path: Any) -> None:
        """Child 3 fails -> 2 created, failed flag, no rollback, no 4th call."""
        simple_yaml = """
name: fail-demo
title: "P {{ summary }}"
tasks:
  - summary: "Child 1"
  - summary: "Child 2"
  - summary: "Child 3"
  - summary: "Child 4"
"""
        (tmp_path / "fail-demo.yaml").write_text(simple_yaml, encoding="utf-8")
        config = _make_config(task_template_dir=str(tmp_path))
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            fields = _json.loads(request.content.decode("utf-8"))["fields"]
            calls.append(fields["summary"])
            # Parent + first two children succeed; the third child fails.
            if len(calls) >= 4:
                return httpx.Response(400, json={"errorMessages": ["boom"]})
            return httpx.Response(
                201, json={"id": str(len(calls)), "key": f"DEVOPS-{len(calls)}", "self": "u"}
            )

        client = _client_with_transport(handler)
        try:
            result = await _handle_create_issue_from_template(
                {"template": "fail-demo", "project_key": "DEVOPS", "summary": "S"},
                config,
                client,
            )
        finally:
            await client.aclose()

        # Exactly 4 HTTP calls: parent + 2 successes + 1 failure. No 4th child.
        # Mock keys off the call counter: parent = call 1 -> DEVOPS-1,
        # so the two created children are DEVOPS-2 and DEVOPS-3.
        assert len(calls) == 4
        assert "Created children (2/4):" in result
        assert "DEVOPS-2 (created)" in result
        assert "DEVOPS-3 (created)" in result
        assert "Child 3 (failed" in result
        assert "NOT rolled back" in result
        assert "Child 4" not in result  # never attempted

    async def test_unknown_template_rejected(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="Unknown task template 'nope'"):
            await _handle_create_issue_from_template(
                {"template": "nope", "project_key": "DEVOPS", "summary": "S"},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.create_issue.assert_not_called()

    async def test_empty_summary_rejected(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="summary"):
            await _handle_create_issue_from_template(
                {"template": "standup-preparation", "project_key": "DEVOPS", "summary": "  "},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.create_issue.assert_not_called()

    async def test_empty_project_key_rejected(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="project_key"):
            await _handle_create_issue_from_template(
                {"template": "standup-preparation", "project_key": "", "summary": "S"},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.create_issue.assert_not_called()

    async def test_empty_template_name_rejected(self) -> None:
        config = _make_config()
        mock_client = AsyncMock(spec=JiraTempoClient)
        with pytest.raises(ValueError, match="template"):
            await _handle_create_issue_from_template(
                {"template": "", "project_key": "DEVOPS", "summary": "S"},
                config,
                cast(JiraTempoClient, mock_client),
            )
        mock_client.create_issue.assert_not_called()

    async def test_parent_payload_without_key_aborts_no_orphans(self) -> None:
        """Parent response missing `key` -> abort before any child is created.

        Regression for the silent-orphan bug: without this check the handler
        created all children unlinked (parent field omitted) and reported
        "Created parent ?". Now the parent step counts as a failure and the
        call aborts per the stop-on-first-failure contract.
        """
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json as _json

            fields = _json.loads(request.content.decode("utf-8"))["fields"]
            calls.append(fields["summary"])
            # Parent create succeeds but returns no `key` (defect case).
            return httpx.Response(201, json={"id": "1", "self": "u"})

        client = _client_with_transport(handler)
        try:
            with pytest.raises(JiraTempoError, match="did not return an issue key"):
                await _handle_create_issue_from_template(
                    {
                        "template": "standup-preparation",
                        "project_key": "DEVOPS",
                        "summary": "S",
                    },
                    _make_config(),
                    client,
                )
        finally:
            await client.aclose()
        # Exactly one HTTP call: the parent. No children were attempted.
        assert len(calls) == 1

    async def test_parent_failure_aborts_whole_call(self) -> None:
        """A parent-creation failure aborts before any child is attempted."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"errorMessages": ["parent rejected"]})

        client = _client_with_transport(handler)
        try:
            with pytest.raises(JiraTempoError, match="400"):
                await _handle_create_issue_from_template(
                    {
                        "template": "standup-preparation",
                        "project_key": "DEVOPS",
                        "summary": "S",
                    },
                    _make_config(),
                    client,
                )
        finally:
            await client.aclose()
