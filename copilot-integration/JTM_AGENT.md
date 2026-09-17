# JTM Agent — Jira/Tempo Reports (universal knowledge)

## What this is

This file is the universal agent knowledge for the `jira-tempo` MCP server. Any AI agent reading it learns how to produce Jira/Tempo worklog reports predictably by calling the matching MCP generator, log time with a brief summary comment, and create or decompose issues from task templates. It is IDE-agnostic and works with VS Code Copilot Chat, Cursor, Claude Code, Continue, Aider, and any MCP-capable client. The MCP server is registered under the name `jira-tempo` (the repository is `jira-tempo-mcp`, but the server id is `jira-tempo`). All report generation goes through `jira-tempo` MCP tools — never direct REST/CLI to Jira or Tempo.

## Report types — the seven-type matrix

Pick the report type from user intent. The table is the decision matrix; the MCP generator column is the exact call to make.

| # | Type | Template | Format | MCP generator + parameters | Use when |
|---|------|----------|--------|----------------------------|---------|
| 1 | **basic** | `default` | `txt` | `generate_weekly_report(template="default", format="txt", username?, date_from, date_to)` | Weekly report grouped by issue with per-task work items and hours. The canonical default — one-click for the common case. |
| 2 | **summary** | `weekly_summary` | `txt` | `generate_weekly_report(template="weekly_summary", format="txt", username?, date_from, date_to)` | Compact: total hours, top-5 tasks, no per-issue detail. For stand-up, quick overview, or management. |
| 3 | **formatted** | `default` | `md` | `generate_weekly_report(template="default", format="md", username?, date_from, date_to)` | Markdown with tables and bold formatting. For wiki, presentations, or Confluence. |
| 4 | **structured** | `default` | `json` | `generate_weekly_report(format="json", username?, date_from, date_to)` | Structured JSON for downstream scripts, dashboards, or ETL. |
| 5 | **team** | `team_report` | `txt`/`md` | `generate_team_report(template="team_report", format="txt"\|"md", users?, date_from, date_to)` | Collective report for multiple users in one file. |
| 6 | **by-tasks** | — | `md` | `generate_tasks_report(format="md", users?, date_from, date_to)` | Report grouped by tasks (not by days). For task-centric review. |
| 7 | **custom-template** | `<custom>` | any | `generate_weekly_report(template=<custom-name>, format=<fmt>, username?, date_from, date_to)` | User-supplied template from `REPORT_TEMPLATE_DIR` (see §Custom templates). |

### Parameter semantics

| Parameter | Required? | Default | Notes |
|-----------|-----------|---------|-------|
| `username` | optional | `JIRA_USER` from MCP config | One user. Omit for the configured default user. |
| `users` | optional | `REPORT_TEAM_USERS` env var, or current user | List of usernames for team reports. |
| `date_from`, `date_to` | **required** | — | ISO date `YYYY-MM-DD`. If the user says "W29" or "this week", resolve to that week's Monday–Sunday. |
| `template` | optional | `default` for weekly, `team_report` for team | See §Built-in templates. |
| `format` | optional | `txt` | One of `txt`, `md`, `json`. |

### Built-in templates

| Template name | Produces |
|---------------|----------|
| `default` | Detailed report with day-by-day breakdown, task metadata, and hour sums. |
| `weekly_summary` | Short report grouped by tasks, no day breakdown. |
| `team_report` | Collective report for multiple users in one file. |

Discover available templates at runtime: call `list_report_templates`. Custom templates from `REPORT_TEMPLATE_DIR` also appear there.

## Tool inventory

The MCP server exposes **19 tools**. The report matrix above uses the generator tools; the rest support the scenarios below and the manual fallback.

| Group | Tools | Used by |
|---|---|---|
| Report generators | `generate_weekly_report`, `generate_team_report`, `generate_tasks_report` | Scenarios 1–3 |
| Report templates | `list_report_templates`, `preview_report_template` | Custom templates (type 7) |
| Worklog reads | `list_worklogs`, `get_worklog` | Scenario 4 (manual fallback) |
| Worklog writes | `create_worklog`, `delete_worklog` | Scenario 5 (`create_worklog` only; `delete_worklog` stays out of scope) |
| Issue reads | `get_issue`, `list_issues_by_jql`, `list_favorite_issues` | Scenario 4. `get_issue` always returns `description`; `list_issues_by_jql` appends it only with `include_description=true` (opt-in, default `false`) |
| Issue writes | `create_issue`, `add_issue_comment`, `list_issue_templates`, `create_issue_from_template` | Scenario 6 |
| Users / helpers | `search_users`, `list_user_tasks`, `get_current_user` | Defaults and enrichment |

Tool-level contracts (parameters, payloads, return shapes) live in `docs/api.md`; the task-template file format in `docs/task-templates.md`.

## Worklog comment style

When logging time (scenario 5), the worklog `comment` is a brief summary of the work done — the same register as the project's reports, not a session log. The contract:

- **≤5 bullets.** One line per bullet; drop anything the reader would skip.
- **Verb-led.** Every bullet starts with a verb («провёл», «исправил», «проверил»). No telegram-style fragments.
- **Plain professional language.** No jargon, no session shorthand, no internal codenames. Expand a non-universal abbreviation on first use.
- **No secrets.** Never include tokens, credentials, or URLs with embedded auth.
- **User's language.** Match the language the user works in.

The agent composes the comment from the work actually done; it never pastes raw conversation or tool output into the comment.

## Work scenarios

### Scenario 1 — Single user, ordinary weekly report

User: "Weekly report for alice for W29."

1. Resolve dates: W29 2026 → `date_from=2026-07-13`, `date_to=2026-07-19` (Mon–Sun).
2. Call `generate_weekly_report(template="default", format="txt", username="alice", date_from="2026-07-13", date_to="2026-07-19")`.
3. Report the saved file's absolute path to the user.

### Scenario 2 — Multiple users, individual reports

User: "Weekly reports for W29 for alice, bob, carol."

1. Clarify the type once (applies to all N reports). Default: `basic`.
2. For each user, call `generate_weekly_report(...)` separately → N files.
3. Report all N file paths.

### Scenario 3 — Multiple users, collective/team report

User: "Team report for W29."

1. Clarify: team report (one file) vs N individual reports. Default to team report when the user said "team", "collective", or "summary".
2. Call `generate_team_report(template="team_report", format="txt", users=["alice","bob","carol"], date_from, date_to)`.
3. Report the single file path.

### Scenario 4 — Non-standard request (fallback to manual composition)

The user asks for something no generator produces in one call: an arbitrary JQL filter, non-standard grouping (by project, sprint, or issue type), combining worklogs with `get_issue` metadata the generator does not include, or a period not aligned to a week.

**Fallback rule:** fall back to manual composition using raw MCP tools ONLY when ALL of these are true:

1. The request cannot be satisfied by any single generator call (types 1–7), AND
2. The request cannot be decomposed into a sequence of generator calls (e.g. one `generate_weekly_report` per user, then concatenated), AND
3. The user explicitly needs the non-standard shape (a hard requirement, not a preference).

When falling back:

1. Call `list_worklogs(date_from, date_to)` for raw worklogs.
2. Call `get_issue(issue_key)` for each unique issue to enrich metadata. `get_issue` always returns `description` (9 fields).
3. If a JQL filter is needed, call `list_issues_by_jql(jql, max_results)`. Descriptions are opt-in there: pass `include_description=true` to append each issue's description; the default `false` keeps list responses compact.
4. The agent MAY also use these read-only tools to enrich the report: `get_worklog` (single worklog detail), `list_favorite_issues` (user's favorite issues), `list_user_tasks` (assigned tasks for a user), `search_users` (find user accounts by query). Manual report composition stays read-only — writes (`create_worklog`, issue creation) belong to §Scenario 5–6, never to a report being composed.
5. Compose the report manually, preserving the structure of the closest built-in template.
6. Save the file to the same `REPORT_OUTPUT_DIR` the generators use, or the user-specified path.
7. **State explicitly in the response** that manual composition was used, and why no generator fit.

### Scenario 5 — Time tracking with a summary comment

User: «затрекай 3 часа на ABC-123, работал с агентами над ревью чарта».

1. Parse the request: issue key (`ABC-123`), duration (`time_spent` — accept «3 часа», `3h`, `2h 30m`, `45m`; convert to Tempo units: `w`=5d, `d`=8h, `h`, `m`), optional date (`date_started`, default today; «за вчера» → yesterday's date).
2. Compose the `comment` per §Worklog comment style — a brief bullet summary of the work actually done, in the user's language.
3. Call `create_worklog(issue_key, time_spent, comment)`.
4. Report the confirmation (issue, duration, worklog id). On `VALIDATION_FAILED` the installation requires Tempo `attributes` — ask the user for the attribute values instead of guessing.

Worked example:

```text
User: «затрекай 3 часа на ABC-123, работал с агентами над ревью чарта»

Parse: issue_key=ABC-123, time_spent="3h", date_started=<today>.
Comment (per §Worklog comment style):
  - Провёл ревью Helm-чарта вместе с агентами
  - Исправил замечания по структуре шаблонов
  - Проверил рендер чарта после правок

create_worklog:
  {"name": "create_worklog",
   "arguments": {"issue_key": "ABC-123", "time_spent": "3h",
                 "comment": "- Провёл ревью Helm-чарта вместе с агентами\n- Исправил замечания по структуре шаблонов\n- Проверил рендер чарта после правок"}}

→ "Tracked 3h on ABC-123 at 2026-09-17. Worklog ID: 12345."
Reply: «Затрекал 3h на ABC-123 (worklog 12345)».
```

### Scenario 6 — Task creation + decomposition

The user describes a task in free form («подготовь новый стенд для пилота») and expects a Jira issue — with subtasks when a template covers the task shape.

1. Parse a summary (the short task title) and optional extra context (becomes `description`). Ask one clarifying question if `project_key` is unknown — there is no safe default.
2. Call `list_issue_templates()` → available templates (name, title pattern, child count, issue types).
3. **Does a template fit the task shape?**
   - **Yes** → `create_issue_from_template(template, project_key, summary, description?)`. Report the parent key and the created children in template order.
   - **No** → fall back to `create_issue(project_key, summary, description?, issuetype?)` — parent only.
4. **Fallback notice (mandatory):** state explicitly that no template fit and the issue was created without subtasks. Do NOT invent ad-hoc subtask structures.
5. Propose the extension path: save a new YAML template to `JTM_TEMPLATES_DIR` (file format: `docs/task-templates.md`) so the next task of this shape gets a proper decomposition. The agent does not author template files itself.
6. **Non-idempotency warning (mandatory):** template creation is not idempotent — re-running the same call creates a duplicate parent and duplicate children. Never rerun to "fix" a partial result; on a child failure the tool reports created-so-far with no rollback — relay that state and let the user decide on cleanup.

## Clarifying questions

When the user request is ambiguous, ask at most 2 questions, each with a recommended default the user can accept silently. The substantive axes:

| Axis | Question | Default |
|------|----------|---------|
| **Type + format** | "Which type (basic, summary, formatted, structured, team, by-tasks, custom) and format (txt, md, json)?" | `basic` + `txt` — the canonical weekly format. `summary` if the user said "short" / "for management" / "top-5". |
| **Period + users** | "Which period and which user(s)?" | Period: current work week Mon–Sun. Users: current authenticated user (`get_current_user` or `JIRA_USER` from config). |
| **Task creation (§Scenario 6)** | "Which project (`project_key`)?" | No safe default — ask when not stated. The template match (§Scenario 6 step 3) resolves the rest. |

Save path is rarely asked — default to `REPORT_OUTPUT_DIR` and state the path in the response.

## Save paths

- **Default:** `REPORT_OUTPUT_DIR` from the MCP server config. The generator writes the file; the agent reports the absolute path.
- **User-specified path:** if the user gives an absolute path, pass it to the generator's output parameter if supported. Otherwise save to `REPORT_OUTPUT_DIR` and report the actual path back.
- The agent does NOT create directories manually to satisfy a custom layout. If the target directory does not exist, save to `REPORT_OUTPUT_DIR` and tell the user where the file landed.

## Custom templates

The MCP server supports custom templates via the `REPORT_TEMPLATE_DIR` env var. Templates can be:

- `.py` — requires `REPORT_TEMPLATE_ALLOW_PY=true` (code execution risk; only for trusted environments).
- `.j2` — Jinja2, safer, preferred for most use cases.

To use a custom template (type 7):

1. The user names a specific template.
2. Call `list_report_templates` to confirm it exists in `REPORT_TEMPLATE_DIR`.
3. Call `generate_weekly_report(template=<name>, format=<fmt>, ...)`.

The agent does NOT author template files. If the user wants a custom template that does not exist yet, tell them to create it manually in `REPORT_TEMPLATE_DIR` (a `.j2` file is recommended).

## Hard rules

- **Only `jira-tempo` MCP tools.** Never direct REST/CLI to Jira or Tempo. If the MCP server is unavailable, say so and point to installation — do not attempt raw HTTP.
- **Writes are scoped.** Two write flows only: `create_worklog` with a style-contract comment (§Scenario 5) and issue creation (§Scenario 6). Never `delete_worklog`; never update or delete issues, comments, or worklogs.
- **No secrets in output.** Never echo `JIRA_API_TOKEN`, `JIRA_PAT`, or `TEMPO_API_TOKEN`. If the user pastes a token, redact it, do not echo it back, and suggest rotation.
- **State the saved file's absolute path** in every report response. The user must never have to guess where the file went.
- **Fallback to manual composition is explicit.** When falling back, say so in the first line of the response — never silently compose a report by hand.

## Anti-patterns

- **Improvising report composition** when a generator fits. Always check the 7-type matrix first.
- **Asking 5+ questions.** Max 2, with defaults — the matrix and parameter table give enough to default most parameters.
- **Silently choosing the wrong type for the audience.** Match type to the stated audience (summary for management, basic for the canonical team format).
- **Hardcoding usernames.** Use `get_current_user` or the `username` parameter; never assume a specific user is the default.
- **Creating directories manually** to satisfy a custom save layout. Save to `REPORT_OUTPUT_DIR` and report the actual path instead.
- **Inventing ad-hoc subtask structures** when no issue template fits (§Scenario 6). Fall back to a parent-only `create_issue` with the explicit notice, and propose saving a template instead.
- **Verbose worklog comments** — a session log with 10+ lines violates the ≤5-bullet contract (§Worklog comment style).
- **Rerunning template creation** after a partial failure — duplicates the task tree. Report created-so-far; the user decides on cleanup.
