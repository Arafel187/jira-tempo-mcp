# 🌐 API — MCP tools

The server exposes 19 tools over the Model Context Protocol. Each tool is
defined in `src/jira_tempo_mcp/server.py` and dispatched through a table
(`_TOOL_HANDLERS`).

---

## 🌐 Tool index

| Tool | Group | Purpose |
| --- | --- | --- |
| [`list_worklogs`](#-list_worklogs) | Worklogs | List worklogs for a date range or single day |
| [`get_worklog`](#-get_worklog) | Worklogs | Get a single worklog by Tempo ID |
| [`create_worklog`](#-create_worklog) | Worklogs | Track time on a Jira issue |
| [`delete_worklog`](#-delete_worklog) | Worklogs | Delete a worklog by ID |
| [`get_issue`](#-get_issue) | Issues | Get Jira issue metadata (9 fields, incl. description) |
| [`create_issue`](#-create_issue) | Issues | Create a new issue in a project (optionally a subtask) |
| [`add_issue_comment`](#-add_issue_comment) | Issues | Add a comment to an existing issue |
| [`list_issue_templates`](#-list_issue_templates) | Issues | List available task templates (builtin + user overrides) |
| [`create_issue_from_template`](#-create_issue_from_template) | Issues | Create a parent issue plus child subtasks from a task template |
| [`list_favorite_issues`](#-list_favorite_issues) | Issues | List favorite issues for the current user |
| [`list_issues_by_jql`](#-list_issues_by_jql) | Issues | Search issues by JQL query |
| [`get_current_user`](#-get_current_user) | Users | Get authenticated user info |
| [`search_users`](#-search_users) | Users | Search Jira users by name or email |
| [`list_user_tasks`](#-list_user_tasks) | Users | Get tasks assigned to a user |
| [`generate_weekly_report`](#-generate_weekly_report) | Reports | Generate a weekly report (`txt`/`md`/`json`) |
| [`generate_team_report`](#-generate_team_report) | Reports | Generate a team report for multiple users |
| [`generate_tasks_report`](#-generate_tasks_report) | Reports | Generate a tasks report grouped by status |
| [`list_report_templates`](#-list_report_templates) | Reports | List available report templates |
| [`preview_report_template`](#-preview_report_template) | Reports | Preview a template with sample data |

---

## 📝 `list_worklogs`

List Tempo worklogs for a date range (or a single day). Only actually
tracked time is returned — planned time is excluded.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `date_from` | string | no | Start date (ISO `YYYY-MM-DD`). Defaults to today. |
| `date_to` | string | no | End date (ISO `YYYY-MM-DD`). Defaults to `date_from`. |

**Example call:**

```json
{
  "name": "list_worklogs",
  "arguments": {
    "date_from": "2026-06-16",
    "date_to": "2026-06-20"
  }
}
```

**Returns:** one line per worklog:

```text
Worklogs 2026-06-16 .. 2026-06-20 (5 entries):
- 2026-06-16 | PROJECT-100 | 1h 30m | id=12345 | Implemented login flow
- 2026-06-17 | PROJECT-101 | 2h | id=12346 | Code review
```

---

## 🔍 `get_worklog`

Get a single Tempo worklog by its Tempo internal ID.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `worklog_id` | string | yes | Tempo worklog ID |

**Example call:**

```json
{
  "name": "get_worklog",
  "arguments": { "worklog_id": "12345" }
}
```

**Returns:** key/value lines with all worklog fields:

```text
Worklog 12345:
  tempoWorklogId: 12345
  issueKey: PROJECT-100
  timeSpentSeconds: 5400
  startDate: 2026-06-16
  comment: Implemented login flow
```

---

## ⏱️ `create_worklog`

Track (log) time on a Jira issue via Tempo. The worklog is attributed to
the token owner unless `author_account_id` is given.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `issue_key` | string | yes | Jira issue key (e.g. `PROJECT-100`) |
| `time_spent` | string | yes | Human duration: `1h 30m`, `2h`, `45m`, `1d 2h` |
| `comment` | string | no | Optional worklog comment |
| `date_started` | string | no | Date in `YYYY-MM-DD` format (e.g. `2026-06-19`). Full ISO datetimes are also accepted and normalized to a date. Defaults to today. |
| `author_account_id` | string | no | Optional Tempo worker key. Defaults to token owner. |
| `attributes` | object | no | Optional Tempo work attributes (e.g. `{"_Специализация_": "Devops", "_Форматработы_": "Удаленно"}`). **Required on some installations** — if you get `VALIDATION_FAILED`, provide them. |

> 💡 **Tip:** Duration units: `w` (week = 5d), `d` (day = 8h), `h` (hour), `m` (minute).

**Example call:**

```json
{
  "name": "create_worklog",
  "arguments": {
    "issue_key": "PROJECT-100",
    "time_spent": "1h 30m",
    "comment": "Implemented login flow",
    "date_started": "2026-06-19",
    "attributes": { "_Специализация_": "Devops", "_Форматработы_": "Удаленно" }
  }
}
```

**Returns:** the confirmation line plus the full worklog details:

```text
Tracked 1h 30m on PROJECT-100 at 2026-06-19. Worklog ID: 12345. Comment: Implemented login flow
---
Worklog details:
Worklog 12345:
  Time spent: 1h 30m (5400s)
  Issue: PROJECT-100 — Implemented login flow
  Comment: Implemented login flow
  Started: 2026-06-19
  Attributes:
    Специализация: Devops
    Форматработы: Удаленно
```

---

## 🗑️ `delete_worklog`

Delete a Tempo worklog by its ID. Use for undo/correction of mis-tracked
time.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `worklog_id` | string | yes | Tempo worklog ID to delete |

**Example call:**

```json
{
  "name": "delete_worklog",
  "arguments": { "worklog_id": "12345" }
}
```

**Returns:**

```text
Deleted worklog 12345.
```

---

## 📋 `get_issue`

Get Jira issue metadata: summary, description, status, project, priority,
assignee, due date, issue type, and components (9 fields).

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `issue_key` | string | yes | Jira issue key (e.g. `PROJECT-100`) |

**Example call:**

```json
{
  "name": "get_issue",
  "arguments": { "issue_key": "PROJECT-100" }
}
```

**Returns:**

```text
PROJECT-100: Implement login flow
Status: In Progress
Project: Web Platform
Priority: High
Assignee: Ivan Golikhin
Due date: 2026-06-20
Issue type: Task
Components: Backend, API
Description: Login fails for LDAP users after session timeout.
```

---

## 🆕 `create_issue`

Create a new Jira issue in a project. Optionally set an issue type and a
parent issue key (for subtasks or epic links). Maps to
`POST /rest/api/2/issue`.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `project_key` | string | yes | Target project key (e.g. `DEVOPS`). |
| `summary` | string | yes | Issue summary (title). Non-empty. |
| `description` | string | no | Issue description. Defaults to empty. |
| `issuetype` | string | no | Issue type name (e.g. `Task`, `Sub-task`). Defaults to `Task`. |
| `parent_key` | string | no | Parent issue key (e.g. `DEVOPS-100`) for subtasks or epic links. When set, the `parent` field is included in the create payload. |

**Example call:**

```json
{
  "name": "create_issue",
  "arguments": {
    "project_key": "DEVOPS",
    "summary": "Fix flaky integration test suite",
    "description": "The suite fails randomly on CI.",
    "issuetype": "Task"
  }
}
```

**Returns:**

```text
Created Task DEVOPS-200 in DEVOPS.
Issue ID: 10001
```

With `parent_key`:

```text
Created Sub-task DEVOPS-201 in DEVOPS (parent DEVOPS-100).
Issue ID: 10002
```

---

## 💬 `add_issue_comment`

Add a comment to an existing Jira issue. Maps to
`POST /rest/api/2/issue/{key}/comment`.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `issue_key` | string | yes | Jira issue key (e.g. `DEVOPS-100`) |
| `comment` | string | yes | Comment text. Non-empty. |

**Example call:**

```json
{
  "name": "add_issue_comment",
  "arguments": {
    "issue_key": "DEVOPS-100",
    "comment": "Root cause found: stale cache in the auth layer."
  }
}
```

**Returns:**

```text
Added comment 10500 to DEVOPS-100.
```

---

## 🧩 `list_issue_templates`

List available task templates (builtin + user overrides from
`JTM_TEMPLATES_DIR`). Each entry carries the template name, the parent
title pattern, the child subtask count, and the parent/child issue types.

**Parameters:** none.

**Example call:**

```json
{
  "name": "list_issue_templates",
  "arguments": {}
}
```

**Returns:**

```text
Task templates (1):
- stand-preparation: title='{{ summary }}', children=15, parent_issuetype=Task, child_issuetype=Sub-task
```

See [task-templates.md](task-templates.md) for the template file format.

---

## 🧩 `create_issue_from_template`

Create a parent Jira issue plus its child subtasks from a task template.
The parent is created first; children are created **sequentially** in
template order, each linked to the parent. On the first child failure,
creation **stops** and the report lists what was created so far — earlier
children are NOT rolled back. A parent failure aborts the whole call
before any child is attempted.

Template titles, descriptions, and tags are jinja2-rendered with the
call arguments (see [task-templates.md](task-templates.md)).

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `template` | string | yes | Task template name (e.g. `stand-preparation`). |
| `project_key` | string | yes | Target project key (e.g. `DEVOPS`). |
| `summary` | string | yes | The user's task description — rendered into the parent title (`{{ summary }}`) and available to child descriptions. |
| `description` | string | no | Optional extra context — available to template descriptions as `{{ user_description }}`. |

**Example call:**

```json
{
  "name": "create_issue_from_template",
  "arguments": {
    "template": "stand-preparation",
    "project_key": "DEVOPS",
    "summary": "Новый стенд ландшафта",
    "description": "пилотный стенд"
  }
}
```

**Returns:**

```text
Created parent Task DEVOPS-200.
Created children (15/15):
  + DEVOPS-201 (created)
  + DEVOPS-202 (created)
  ...
All children created successfully.
```

On a child failure:

```text
Created parent Task DEVOPS-200.
Created children (2/4):
  + DEVOPS-201 (created)
  + DEVOPS-202 (created)
  x Run the deployment pipeline (failed: Jira/Tempo API error: API error 400 from ...)
Creation stopped at the first failure — earlier children were created and are NOT rolled back.
```

---

## ⭐ `list_favorite_issues`

List favorite issues for the current Jira user. Returns keys and summaries.

**Parameters:** none.

**Example call:**

```json
{
  "name": "list_favorite_issues",
  "arguments": {}
}
```

**Returns:**

```text
Favorite issues (3):
- PROJECT-100: Implement login flow
- PROJECT-101: Code review process
- PROJECT-102: Fix CI pipeline
```

---

## 📝 `generate_weekly_report`

Generate a weekly work report from Tempo worklogs and save it as a file.
Groups worklogs by issue, maps known issues to stable sections, and writes
`<prefix>_<YYYY-MM-DD>_<YYYY-MM-DD>.<fmt>` to the configured output
directory. Since v0.3.0 the `format` parameter selects output: `txt`
(default), `md` (Markdown), or `json` (structured JSON).

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `target_date` | string | no | Any date within the target week (ISO `YYYY-MM-DD`). Defaults to today. |
| `output_dir` | string | no | Output directory. Defaults to `REPORT_OUTPUT_DIR` env or `~/.mcp/jira-tempo-mcp/reports/`. Must be inside the allowed root. |
| `template` | string | no | Template name (e.g. `default`, `weekly_summary`). Defaults to `REPORT_TEMPLATE` env or `default`. Use `list_report_templates` to see available templates. Only used when `format='txt'`. |
| `format` | string | no | Output format: `txt` (plain text, default), `md` (Markdown), `json` (structured JSON). File extension matches the format. |
| `username` | string | no | Optional Jira username to generate the report for (instead of the configured `JIRA_USER`). If provided, worklogs are filtered to this user. |

**Example call:**

```json
{
  "name": "generate_weekly_report",
  "arguments": { "target_date": "2026-06-19", "format": "md" }
}
```

**Returns:**

```text
Weekly report generated: /home/user/.mcp/jira-tempo-mcp/reports/golikhin_2026-06-15_2026-06-19.md
Reports directory: /home/user/.mcp/jira-tempo-mcp/reports
```

> 💡 **Tip:** See [reports.md](reports.md) for report customization (section mapping,
> stable order, non-issue sections).

---

## 👥 `generate_team_report`

Generate a team work report from Tempo worklogs for multiple Jira users.
Fetches worklogs per user with bounded concurrency (rate-limit safe), renders
per-user sections plus an aggregate summary, and writes
`team_<YYYY-MM-DD>_<YYYY-MM-DD>_<users_hash>.<fmt>` to the configured output
directory. Since v0.3.0 the `format` parameter selects output: `txt`
(default), `md` (Markdown), or `json`.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `users` | array<string> | no | Jira usernames to include. If not provided, uses `REPORT_TEAM_USERS` env var or the current user. |
| `date_from` | string | no | Start date (ISO `YYYY-MM-DD`). Defaults to Monday of the current week. |
| `date_to` | string | no | End date (ISO `YYYY-MM-DD`). Defaults to Friday of the current week. |
| `section_map` | object | no | Optional override for `REPORT_SECTION_MAP` (issue key → section title) |
| `template` | string | no | Template name. Defaults to `team_report`. Only used when `format='txt'`. |
| `output_dir` | string | no | Output directory. Defaults to `REPORT_TEAM_OUTPUT_DIR` or `REPORT_OUTPUT_DIR`. Must be inside the allowed root. |
| `format` | string | no | Output format: `txt` (plain text, default), `md` (Markdown), `json` (structured JSON). File extension matches the format. |

> 🛡️ **Rate-limiting:** concurrent Tempo requests are bounded by
> `TEMPO_MAX_CONCURRENT_REQUESTS` (default 3). A configurable delay
> (`TEMPO_REQUEST_DELAY_MS`, default 100 ms) is inserted between batches.
> On HTTP 429 the client retries with exponential backoff up to
> `TEMPO_MAX_RETRIES` (default 3) times.

**Example call:**

```json
{
  "name": "generate_team_report",
  "arguments": {
    "users": ["alice", "bob", "carol"],
    "date_from": "2026-06-15",
    "date_to": "2026-06-19",
    "format": "md"
  }
}
```

**Returns:**

```text
Team report: 3 users, 24h total. Written to /home/user/.mcp/jira-tempo-mcp/reports/team_2026-06-15_2026-06-19_a1b2c3.md
Reports directory: /home/user/.mcp/jira-tempo-mcp/reports
```

---

## 📊 `generate_tasks_report`

Generate a report of user tasks grouped by status and save it as a file.
For a single user: all tasks with full details (summary, due date,
priority, comments). For multiple users: only active tasks (status category
"In Progress"), grouped by user then status. Since v0.3.0 the `format`
parameter selects output: `md` (Markdown, default), `txt`, or `json`.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `users` | array<string> | no | Jira usernames to include. If not provided, uses `REPORT_TEAM_USERS` env var or the current user. |
| `active_only` | boolean | no | Only include active tasks. Forced `true` for multiple users. Defaults to `false`. |
| `output_dir` | string | no | Output directory. Defaults to `REPORT_OUTPUT_DIR` env or `~/.mcp/jira-tempo-mcp/reports/`. Must be inside the allowed root. |
| `format` | string | no | Output format: `md` (Markdown, default), `txt` (plain text), `json` (structured JSON). File extension matches the format. |

**Example call:**

```json
{
  "name": "generate_tasks_report",
  "arguments": { "users": ["golikhin"], "format": "md" }
}
```

**Returns:**

```text
Tasks report for 1 user(s) written to /home/user/.mcp/jira-tempo-mcp/reports/tasks_golikhin_2026-06-19.md
Reports directory: /home/user/.mcp/jira-tempo-mcp/reports
```

---

## 🎨 `list_report_templates`

List available report templates (builtin + custom). Returns each template's
name, provenance kind (`builtin` or `custom`), engine (`Jinja2` or `Python`),
and description. Custom templates are discovered from `REPORT_TEMPLATE_DIR`.

**Parameters:** none.

**Example call:**

```json
{
  "name": "list_report_templates",
  "arguments": {}
}
```

**Returns:**

```text
Report templates (4):
- default (builtin, Jinja2): Weekly report grouped by issue with stable sections
- team_report (builtin, Jinja2): Team report: per-user sections with issue breakdown
- weekly_summary (builtin, Jinja2): Compact weekly summary: total hours, top 5 issues
- my_custom (custom, Jinja2): My custom Jinja2 template
```

> 💡 **Tip:** See [reports.md#custom-templates](reports.md#-custom-templates) for how to
> add custom templates.

---

## 👁️ `preview_report_template`

Preview a report template rendered with **sample data** — no Jira/Tempo
calls are made. Useful for exploring templates before generating a real
report. Returns the rendered text without writing a file.

> 🆕 **New in v0.4.0.** This tool does not call Jira or Tempo — it uses
> built-in mock worklogs so you can preview any template offline.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `template_name` | string | yes | Template name (use `list_report_templates` to see available names) |
| `sample_data` | string | no | Sample-data profile: `default` (realistic week, several issues), `minimal` (single worklog), `empty` (no worklogs — tests empty-state rendering). Defaults to `default`. |

**Example call:**

```json
{
  "name": "preview_report_template",
  "arguments": { "template_name": "default", "sample_data": "minimal" }
}
```

**Returns:** the rendered template text:

```text
Weekly report: 2026-06-15 — 2026-06-19
Worker: preview-user
Total: 1h

Sections:
  DEVOPS-101 (Refactor Helm release workflow): 1h
    2026-06-15 — 1h — Kicked off the refactor.
```

---

## 👤 `get_current_user`

Get information about the authenticated user (PAT owner). Returns username,
display name, email, key, and active status. Useful for verifying which
account the server is running as.

**Parameters:** none.

**Example call:**

```json
{
  "name": "get_current_user",
  "arguments": {}
}
```

**Returns:**

```text
Current user:
  Username: golikhin
  Display name: Ivan Golikhin
  Email: i.golikhin@example.com
  Key: golikhin
  Active: True
```

---

## 🔎 `search_users`

Search Jira users by name, surname, username, or email fragment. Returns a
list of matching users with name, key, display name, email, and active
status.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | Search query — name, surname, or username fragment |
| `max_results` | integer | no | Max number of users to return. Defaults to `10`. |

**Example call:**

```json
{
  "name": "search_users",
  "arguments": { "query": "golikhin", "max_results": 5 }
}
```

**Returns:**

```text
Users matching 'golikhin' (1):
- golikhin (golikhin): Ivan Golikhin <i.golikhin@example.com> [active]
```

---

## 📋 `list_user_tasks`

Get tasks assigned to a Jira user. Returns up to 100 tasks ordered by last
updated, each with status, due date, summary, priority, issue type, project,
and the last 2 comments.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `username` | string | yes | Jira username (e.g. `golikhin`) |
| `status_filter` | array<string> | no | Optional list of status names to filter by |
| `max_results` | integer | no | Max number of tasks to return. Defaults to `100`. |

**Example call:**

```json
{
  "name": "list_user_tasks",
  "arguments": { "username": "golikhin", "status_filter": ["In Progress", "Open"] }
}
```

**Returns:**

```text
Tasks for golikhin (2):
- [DEVOPS-101] Refactor Helm release workflow | In Progress | priority=High | due=2026-06-20 | comments=2
    💬 tech-lead: Looks good, please add tests.
- [DEVOPS-102] Migrate Valkey chart | Open | priority=Medium | due=— | comments=0
```

---

## 🔍 `list_issues_by_jql`

Search Jira issues by a JQL query (read-only). Returns a formatted list of
issues with key, summary, status, priority, due date, and assignee. Max 100
results.

**Parameters:**

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `jql` | string | yes | JQL query string (e.g. `project = DEVOPS AND assignee = golikhin ORDER BY updated DESC`) |
| `fields` | string | no | Comma-separated field names to return. Defaults to `summary,status,priority,duedate,assignee,issuetype,project,created,updated`. |
| `max_results` | integer | no | Max results. Defaults to `50`. Capped at `100`. |
| `include_description` | boolean | no | Also return each issue's description. Defaults to `false` to keep list responses compact. |

**Example call:**

```json
{
  "name": "list_issues_by_jql",
  "arguments": {
    "jql": "project = DEVOPS AND assignee = golikhin ORDER BY updated DESC",
    "max_results": 5
  }
}
```

**Returns:**

```text
Issues matching JQL (2):
- [DEVOPS-101] Refactor Helm release workflow | In Progress | priority=High | due=2026-06-20 | assignee=golikhin
- [DEVOPS-102] Migrate Valkey chart | Open | priority=Medium | due=— | assignee=golikhin
```

With `include_description: true` each line is followed by an indented
description:

```text
Issues matching JQL (1):
- [DEVOPS-101] Refactor Helm release workflow | In Progress | priority=High | due=2026-06-20 | assignee=golikhin
    Description: Split the release workflow into reusable jobs.
```

---

## ❌ Error handling

All tools return a user-friendly error string on failure (never a raw
exception trace). Common error patterns:

| Error | Cause |
| --- | --- |
| `Invalid issue key '...'` | key does not match `^[A-Z][A-Z0-9]+-\d+$` |
| `Invalid date for ...` | date is not ISO `YYYY-MM-DD` |
| `Could not parse duration: '...'` | `time_spent` has no valid `w/d/h/m` tokens |
| `Jira/Tempo API error: 401 ...` | invalid or expired PAT |
| `output_dir '...' resolves outside the allowed root` | path traversal attempt |
| `Could not identify your Tempo worker key` | `JIRA_USER` mismatch or Tempo connectivity |

---

## ➡️ Next steps

- 📝 [reports.md](reports.md) — weekly report customization
- ⚙️ [configuration.md](configuration.md) — env vars that affect tool behavior
- 🏗️ [architecture.md](architecture.md) — how tools are dispatched
