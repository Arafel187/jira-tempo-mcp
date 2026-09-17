---
name: jira-tempo-reports
description: (JTM) Domain skill for the JTM: Jira Tempo Reports agent — VS Code picker flow and VS Code-specific behavior. The universal report matrix, work scenarios (including time tracking with a summary comment and task creation + decomposition), and the worklog-comment style contract live in JTM_AGENT.md in `copilot-integration/` (same directory as this skill file).
user-invocable: false
---

# jira-tempo-reports

This skill is the VS Code-specific companion to `JTM_AGENT.md` (in
`copilot-integration/` next to this skill file, or installed alongside
the agent in `~/.copilot/skills/jira-tempo-reports/`). It covers ONLY the
interactive picker flow (`vscode_askQuestions`) and the VS Code
behavior nuances — the report knowledge itself (report matrix,
parameter semantics, work scenarios — including the two write
scenarios, time tracking with a summary comment and task creation
+ decomposition —, the worklog-comment style contract, and fallback
rules) lives in `JTM_AGENT.md`. **Do not duplicate that
content here.**

## When to apply

- The `JTM: Jira Tempo Reports` agent is running inside VS Code
  Copilot Chat (picker UI available) and receives a report request.
- VS Code UI tools (`vscode_askQuestions`) are available.
- A clarification is needed on type / format / period / user before
  calling a `jira-tempo` MCP generator (report requests), or on the
  project key for task creation (§Scenario 6 of `JTM_AGENT.md`).
- A confirmation is needed before `create_issue_from_template` runs
  (it is not idempotent — a rerun duplicates the task tree).

## When NOT to apply

- VS Code UI is unavailable (headless CI, non-VS Code host, CLI
  mode) — fall back to prose clarifying questions (see
  `JTM_AGENT.md` §Parameter semantics; max 2 questions with
  recommended defaults).
- The user already specified type + format + period + user in their
  first message — skip the picker and run the generator directly.
- The request is a Jira operation outside this agent's scope
  (`delete_worklog`, issue/comment/worklog updates, template file
  authoring), analytics beyond raw aggregation, or non-Jira data —
  see `JTM_AGENT.md` §Hard rules.

## Interactive picker flow

The agent makes **one** `vscode_askQuestions` call (up to 4 questions)
to keep the flow atomic. The picker replaces prose clarifying questions
when VS Code UI is available.

### Question 0 — quick-default one-click option (always present)

A `pick` (single-select) question with these options:

| Label (click) | Effect |
|---|---|
| **📊 Недельный отчёт (по умолчанию)** | Runs `generate_weekly_report(template="default", format="txt", username=<get_current_user>, date_from=<Mon>, date_to=<Sun>)` immediately. Skips follow-up questions. Handles the 80% case (single user, current week, basic report) in one click. |
| **🎯 Настроить параметры** | Shows follow-up questions (type, format, period, user, path). |
| **👥 Командный отчёт** | Shows users (multi-select) + type/format/period follow-ups for a team report. |

The first option is the one-click default. If the user wants "the
usual", they click once and the agent runs without further
interaction.

### Follow-up questions (only if "Настроить" or "Командный")

| # | Input type | Question | Default |
|---|---|---|---|
| 1 | `pick` | Тип отчёта (see `JTM_AGENT.md` §7-type matrix) | `basic` |
| 2 | `pick` | Формат (txt, md, json) | follows type |
| 3a | `input` | Период начала (ISO YYYY-MM-DD) | Monday of current work week |
| 3b | `input` | Период конца (ISO YYYY-MM-DD) | Sunday of current work week |
| 4 | `input` | Пользователь (Jira username; comma-separated for team) | `get_current_user` |
| 5 | `input` | Путь сохранения (абсолютный) | `REPORT_OUTPUT_DIR` from config |

Empty inputs fall back to the documented default; the agent states the
chosen default in the response.

### Picker behavior rules

- **Atomic.** One `vscode_askQuestions` call per clarification round —
  not a sequence of single-question dialogs.
- **Skip when resolved.** If the user named a period ("W29") or user
  ("for alice") in their message, do not re-ask those axes. The
  picker only covers axes the user left ambiguous.
- **No "are you sure?" loop.** Once the dialog closes, proceed.
- **Report the saved file path** after the generator runs.

## Clarifying questions (prose fallback)

When VS Code UI is unavailable (headless, CLI, non-VS Code host), fall
back to prose clarifying questions. The substantive axes, defaults,
and the 2-question grouping live in `JTM_AGENT.md` §Parameter
semantics — do not duplicate the matrix here. Apply those defaults;
ask at most 2 questions, each with a recommended default the user can
accept silently.

## Hard rules

The hard rules (only `jira-tempo` MCP tools; writes scoped to
`create_worklog` with a style-contract comment and issue creation;
no secrets; state the file path; fallback explicit; match type to
audience) live in `JTM_AGENT.md` §Hard rules and in the
`JTM: Jira Tempo Reports` agent body. This skill does not re-state
them — apply both sources, with `JTM_AGENT.md` as the authority for
report composition and the agent body as the authority for VS Code
behavior.
