"""Task-template system — parent issue + child subtasks from YAML templates.

A task template describes a repeatable work item that expands into one
parent Jira issue plus an ordered list of child subtasks. Templates are
YAML files in two layers, mirroring the report-template pattern:

* **Built-in** — ``src/jira_tempo_mcp/templates/tasks/*.yaml`` shipped with
  the package (importlib.resources).
* **User overrides/additions** — ``*.yaml`` files in ``Config.task_template_dir``
  (env ``JTM_TEMPLATES_DIR``, optional). A user file whose ``name`` equals a
  built-in template's name overrides it.

Template fields are validated with pydantic; descriptions and titles render
through a sandboxed Jinja2 environment with the context:
``summary``, ``user_description``, ``project_key``, ``today``.
"""

from __future__ import annotations

import logging
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment
from jinja2.exceptions import SecurityError as JinjaSecurityError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# Package data path holding built-in task templates.
_BUILTIN_PACKAGE = "jira_tempo_mcp.templates"
_BUILTIN_SUBDIR = "tasks"

# Errors a YAML template may raise. Pydantic's ValidationError inherits from
# ValueError, so it is covered here too — one tuple keeps call sites simple.
TEMPLATE_ERRORS = (ValueError, yaml.YAMLError)

# Sandboxed Jinja2 environment shared by all render calls. autoescape=False
# because issue descriptions are plain text (Jira wiki markup), not HTML;
# SandboxedEnvironment blocks dunder/globals escape (same defence as the
# report-template loader, see tests/test_security.py).
_render_env: Environment = SandboxedEnvironment(autoescape=False)


class TemplateRenderError(ValueError):
    """Raised when a template field fails to render through Jinja2.

    Carries the template name and the failing field so the caller can report
    an actionable error instead of a raw jinja2 traceback.
    """


class TaskTemplateChild(BaseModel):
    """One child subtask entry inside a task template."""

    model_config = ConfigDict(frozen=True)

    summary: str = Field(min_length=1, description="Child summary; jinja2-rendered.")
    tag: str = Field(
        default="",
        description="Optional prefix rendered before the summary (e.g. '[terraform]').",
    )
    description: str = Field(
        default="",
        description="Optional child description; jinja2-rendered. "
        "When empty, the rendered summary is duplicated as the description.",
    )

    @field_validator("summary", "tag", "description")
    @classmethod
    def _strip_strings(cls, v: str) -> str:
        return v.strip()

    @field_validator("tag")
    @classmethod
    def _tag_no_newlines(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("tag must be a single line")
        return v


class TaskTemplate(BaseModel):
    """A validated task template: one parent issue plus child subtasks."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
        description="Template slug used for selection (unique across the registry).",
    )
    title: str = Field(
        min_length=1,
        description="Parent issue summary; jinja2-rendered (usually '{{ summary }}').",
    )
    description: str = Field(
        default="",
        description="Optional parent issue description; jinja2-rendered. "
        "When empty, the rendered title is duplicated as the description.",
    )
    parent_issuetype: str = Field(
        default="Task",
        min_length=1,
        description="Parent issue type name (e.g. 'Task').",
    )
    child_issuetype: str = Field(
        default="Sub-task",
        min_length=1,
        description="Child issue type name (e.g. 'Sub-task').",
    )
    tasks: list[TaskTemplateChild] = Field(
        min_length=1,
        description="Ordered child subtasks.",
    )

    @field_validator("name", "title", "parent_issuetype", "child_issuetype")
    @classmethod
    def _strip_strings(cls, v: str) -> str:
        return v.strip()

    @field_validator("tasks")
    @classmethod
    def _tasks_non_empty(cls, v: list[TaskTemplateChild]) -> list[TaskTemplateChild]:
        if not v:
            raise ValueError("tasks must contain at least one child")
        return v

    def render(self, context: dict[str, Any]) -> tuple[str, str, list[tuple[str, str]]]:
        """Render the template with the given context.

        Returns ``(parent_summary, parent_description, [(child_summary,
        child_description), ...])`` in template order. Each rendered child
        description falls back to the rendered child summary when the template
        provides none (owner decision: descriptions may duplicate the title).

        Raises :class:`TemplateRenderError` when any field fails to render.
        """
        parent_summary = self._render_field(self.title, "title", context)
        parent_description = (
            self._render_field(self.description, "description", context)
            if self.description
            else parent_summary
        )
        children: list[tuple[str, str]] = []
        for idx, child in enumerate(self.tasks):
            child_summary = self._render_field(child.summary, f"tasks[{idx}].summary", context)
            prefix = self._render_field(child.tag, f"tasks[{idx}].tag", context)
            full_summary = f"{prefix} {child_summary}".strip() if prefix else child_summary
            child_description = (
                self._render_field(child.description, f"tasks[{idx}].description", context)
                if child.description
                else full_summary
            )
            children.append((full_summary, child_description))
        return parent_summary, parent_description, children

    def _render_field(self, source: str, field: str, context: dict[str, Any]) -> str:
        """Render one jinja2 template string; map failures to TemplateRenderError."""
        try:
            return _render_env.from_string(source).render(**context).strip()
        except JinjaSecurityError as exc:
            raise TemplateRenderError(
                f"Template {self.name!r} field {field!r} attempted a sandbox escape: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — jinja2 raises various errors
            raise TemplateRenderError(
                f"Template {self.name!r} field {field!r} failed to render: {exc}"
            ) from exc


def render_context(
    summary: str,
    project_key: str,
    user_description: str = "",
    today: date | None = None,
) -> dict[str, str]:
    """Build the jinja2 render context for a task template.

    Keys: ``summary`` (the caller's task description), ``user_description``
    (optional extra context), ``project_key``, ``today`` (ISO date string).
    """
    return {
        "summary": summary,
        "user_description": user_description,
        "project_key": project_key,
        "today": (today or date.today()).isoformat(),
    }


def parse_task_template(data: dict[str, Any], *, source: str) -> TaskTemplate:
    """Validate a raw YAML mapping into a :class:`TaskTemplate`.

    ``source`` is used only in error messages (file path or '<builtin>').
    Raises ``ValueError`` (including pydantic ValidationError) on invalid data.
    """
    try:
        return TaskTemplate.model_validate(data)
    except ValueError as exc:
        raise ValueError(f"Invalid task template {source}: {exc}") from exc


def _load_yaml_file(path: Path) -> TaskTemplate:
    """Load and validate one YAML task-template file.

    Raises ``ValueError`` with the file path in the message on YAML or schema
    errors, and on duplicate ``name`` keys (PyYAML keeps the last duplicate;
    a duplicated name is almost always an editing mistake).
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in task template {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"Task template {path} must be a YAML mapping, got {type(raw).__name__}")
    return parse_task_template(raw, source=str(path))


def load_builtin_task_templates() -> dict[str, TaskTemplate]:
    """Load built-in task templates shipped with the package.

    Uses ``importlib.resources`` so templates load both from the source tree
    and from an installed wheel. Returns a mapping ``name -> TaskTemplate``.
    Unreadable/invalid built-ins are skipped with a logged warning (they are
    package data, not user input — a broken one should not kill the server).
    """
    templates: dict[str, TaskTemplate] = {}
    root = resources.files(_BUILTIN_PACKAGE).joinpath(_BUILTIN_SUBDIR)
    if not root.is_dir():
        logger.warning("Built-in task template dir %s not found", _BUILTIN_SUBDIR)
        return templates
    # Collect names first: importlib Traversable iterdir() is not sortable
    # under mypy strict (SupportsRichComparisonT), but the name strings are.
    entry_names = sorted(entry.name for entry in root.iterdir())
    for entry_name in entry_names:
        if not entry_name.endswith(".yaml"):
            continue
        entry = root.joinpath(entry_name)
        try:
            raw = yaml.safe_load(entry.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            logger.warning("Built-in task template %s failed to load: %s", entry_name, exc)
            continue
        if not isinstance(raw, dict):
            logger.warning("Built-in task template %s is not a mapping — skipped", entry_name)
            continue
        try:
            tpl = parse_task_template(raw, source=f"builtin:{entry_name}")
        except ValueError as exc:
            logger.warning("Built-in task template %s invalid: %s", entry_name, exc)
            continue
        templates[tpl.name] = tpl
    return templates


def discover_task_template_overrides(config_dir: str) -> dict[str, TaskTemplate]:
    """Scan the user override directory and load ``*.yaml`` task templates.

    Returns a mapping ``name -> TaskTemplate``. Files with duplicate names
    inside the same directory overwrite each other (last alphabetical wins);
    schema errors are logged and skipped — a bad user file must not take down
    the whole registry. An empty/missing ``config_dir`` yields an empty dict.
    A leading ``~`` is expanded (``Path.expanduser``) so an env value like
    ``~/.mcp/jira-tempo-mcp/task-templates`` resolves in .env / systemd /
    docker contexts where no shell expands it.
    """
    if not config_dir:
        return {}
    directory = Path(config_dir).expanduser()
    if not directory.is_dir():
        logger.warning("Task template dir %s does not exist — no overrides", directory)
        return {}
    templates: dict[str, TaskTemplate] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not path.name.endswith(".yaml") or path.name.startswith("_"):
            continue
        try:
            tpl = _load_yaml_file(path)
        except ValueError as exc:
            logger.warning("Skipping task template override: %s", exc)
            continue
        templates[tpl.name] = tpl
    return templates


def build_task_template_registry(config_dir: str = "") -> dict[str, TaskTemplate]:
    """Build the full task-template registry: built-ins + user overrides.

    User files override built-ins **by template name**: a user ``*.yaml``
    whose ``name`` equals a built-in name replaces it; other user files are
    additions. Registry keys are the template ``name`` field, not file stems.
    """
    registry = load_builtin_task_templates()
    registry.update(discover_task_template_overrides(config_dir))
    return registry


__all__ = [
    "TEMPLATE_ERRORS",
    "TaskTemplate",
    "TaskTemplateChild",
    "TemplateRenderError",
    "build_task_template_registry",
    "discover_task_template_overrides",
    "load_builtin_task_templates",
    "parse_task_template",
    "render_context",
]
