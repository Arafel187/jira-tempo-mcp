# 🧩 Task templates — parent issue + child subtasks from YAML

A task template describes a repeatable work item that expands into one
parent Jira issue plus an ordered list of child subtasks. Two MCP tools
use it: [`list_issue_templates`](api.md#-list_issue_templates) lists the
available templates and [`create_issue_from_template`](api.md#-create_issue_from_template)
creates the issue tree from one of them.

Built-in templates ship with the package (currently `standup-preparation`,
15 child tasks); user-defined templates extend or replace them.

---

## 📄 Template file format

Templates are YAML files. The file below shows every supported field:

```yaml
name: standup-preparation        # slug, unique in the registry: ^[a-z0-9][a-z0-9_-]*$
title: "{{ summary }}"           # parent summary, jinja2-rendered
description: >-                  # parent description, jinja2-rendered;
  Подготовка стенда к стендапу.{%- if user_description %} Контекст:  # empty -> duplicates the rendered title
  {{ user_description }}.{% endif %}
parent_issuetype: Task           # parent issue type (default Task)
child_issuetype: Sub-task        # child issue type (default Sub-task)
tasks:                           # ordered child subtasks (at least one)
  - tag: "[terraform]"           # optional prefix rendered before the summary
    summary: "Подготовить IaC-манифесты для нового стенда"  # jinja2-rendered
    description: "Создать и проверить Terraform-манифесты для ландшафта «{{ summary }}»."
  - summary: "Прогнать smoke-тесты на стенде"  # no description -> duplicates the summary
```

**Validation rules** (pydantic, enforced at load time):

| Field | Rule |
| --- | --- |
| `name` | Required, matches `^[a-z0-9][a-z0-9_-]*$`; unique across the registry |
| `title` | Required, non-empty |
| `tasks` | Required, at least one child; each child requires a non-empty `summary` |
| `tag` | Optional, single line (no newlines) |
| `parent_issuetype` / `child_issuetype` | Optional; default `Task` / `Sub-task` |

A legacy `project_key` field in a template file is **ignored** — the field
was removed from the schema because the target project is always provided
at call time (the `project_key` argument of `create_issue_from_template`).
Existing template files containing it keep loading.

---

## 🧩 Jinja2 render context

Descriptions and titles render through a sandboxed Jinja2 environment
(the same defence as report templates — dunder/globals escape is blocked).
Available variables:

| Variable | Type | Meaning |
| --- | --- | --- |
| `summary` | string | The caller's task description (the `summary` argument) |
| `user_description` | string | Optional extra context (the `description` argument); empty string when omitted |
| `project_key` | string | Target project key |
| `today` | string | Creation date, ISO `YYYY-MM-DD` |

Fallbacks: a child with no `description` duplicates its rendered summary;
a parent with no `description` duplicates the rendered title.

Rendering failures (undefined variable with an unknown filter, sandbox
escape) raise `TemplateRenderError` with the template name and the failing
field.

---

## 📁 User overrides — `JTM_TEMPLATES_DIR`

Set the `JTM_TEMPLATES_DIR` environment variable to a directory scanned
for `*.yaml` task templates:

- A user file whose `name` equals a built-in template's name **overrides**
  the built-in.
- Other user files are additions to the registry.
- Files whose name starts with `_` and non-`.yaml` files are ignored.
- A broken user file is skipped with a logged warning — it never takes
  down the server.

```bash
# Override the built-in standup-preparation with a leaner variant
JTM_TEMPLATES_DIR=~/.mcp/jira-tempo-mcp/task-templates
```

Without the variable (or pointing at an empty/missing directory) the
server serves built-in templates only.

---

## ✏️ Example

1. Create `~/.mcp/jira-tempo-mcp/task-templates/deploy-checklist.yaml`:

```yaml
name: deploy-checklist
title: "Deploy {{ summary }}"
description: "Deployment run for {{ summary }} on {{ today }}. {{ user_description }}"
tasks:
  - tag: "[pre]"
    summary: "Verify backups and free disk space"
  - tag: "[deploy]"
    summary: "Run the deployment pipeline"
    description: "Trigger the pipeline for {{ summary }} and watch the first stage."
  - tag: "[post]"
    summary: "Smoke-check the public endpoint"
```

2. Point the server at the directory and call:

```json
{
  "name": "create_issue_from_template",
  "arguments": {
    "template": "deploy-checklist",
    "project_key": "DEVOPS",
    "summary": "release 1.4 to staging",
    "description": "coordinate with QA first"
  }
}
```

3. Result: parent `Task DEVOPS-200` ("Deploy release 1.4 to staging", the
rendered description) plus three sequential `Sub-task` children linked to
it, in template order.

---

## 🔗 Related

- [API reference — `create_issue_from_template`](api.md#-create_issue_from_template)
- [API reference — `list_issue_templates`](api.md#-list_issue_templates)
- [Custom report templates](templates.md) (a separate, report-side system)