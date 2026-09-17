# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] — 2026-09-17

### Added

- `list_issue_templates` MCP tool (`server.py` + `task_templates.py`) — lists available task templates (builtin + user overrides from `JTM_TEMPLATES_DIR`), each with name, parent title pattern, child count, and parent/child issue types.
- `create_issue_from_template` MCP tool — creates a parent Jira issue plus sequentially created child subtasks from a YAML task template; on the first child failure it stops and reports created-so-far (no rollback). Built-in template `stand-preparation` (15 child tasks) ships with the package; user overrides via `JTM_TEMPLATES_DIR`.
- `task_templates.py` module — pydantic-validated template schema, sandboxed Jinja2 rendering (`summary`/`user_description`/`project_key`/`today` context), `importlib.resources` built-in loading, and name-based override precedence.
- Docs: `docs/task-templates.md` / `docs/task-templates.ru.md` (template YAML format, `JTM_TEMPLATES_DIR` override, example), contracts for both tools in `docs/api.md` / `docs/api.ru.md`, tool-count references updated 17 → 19 (api, architecture, README feature tables).
- 32 tests covering schema validation, built-in loading, jinja2 rendering (incl. sandbox escape), registry precedence, and both new tools (happy path, partial failure, parent-failure abort, validation).
- `create_issue` MCP tool (`server.py` + `client.py`) — creates a Jira issue via `POST /rest/api/2/issue` with project key, summary, optional description/issuetype (default `Task`), and optional `parent_key` (included as the `parent` field for subtasks or epic links). Returns the normalized `{key, id, self}` from Jira.
- `add_issue_comment` MCP tool (`server.py` + `client.py`) — posts a comment via `POST /rest/api/2/issue/{key}/comment`; returns normalized `{id, self, body}`. Server-side and client-side validation rejects empty comments.
- 19 tests (mock-transport client tests + handler-level tests) covering happy paths, the parent-field payload, validation errors, and API-error propagation.
- Docs: both tools added to `docs/api.md` / `docs/api.ru.md` (tool index + full contracts), tool-count references updated 15 → 17 in `architecture.md` / `architecture.ru.md`, and both README feature tables extended.

### Fixed

- `create_issue_from_template` no longer creates silently orphaned children when Jira's parent-create response lacks an issue `key` — the call aborts as a parent failure before any child is attempted (previously children were created unlinked with the `parent` field omitted while the report printed `Created parent ?`).
- Removed the dead `project_key` field from the task-template schema and docs (EN+RU) — it was documented as "default project key; may be overridden at call time" but never read by the handler; the target project is always provided at call time. Legacy template files containing `project_key` keep loading (pydantic ignores the unknown field).
- `JTM_TEMPLATES_DIR` now expands a leading `~` (matches the documented example) — previously a tilde path was taken literally and the override directory was silently missing in `.env` / systemd / docker contexts.
- Renamed the built-in task template `standup-preparation` → `stand-preparation` — the old name was a translation error (the owner's «стенд» / test environment was rendered as "standup", the scrum meeting). Parent description rewritten to «Подготовка нового стенда.»; the 15 child tasks were already environment-provisioning wording and stay unchanged. No migration needed: user override files re-key on `name: stand-preparation`.

## [0.4.3] — 2026-08-08

### Fixed

- `jira-tempo-mcp install` now shows clear guidance when invoked outside a git clone (wheel/Docker). Previously failed with terse "install.py not found". install.py is a dev-setup script requiring the repo tree (`.env.example`, `copilot-integration/`, `pyproject.toml`); it is intentionally NOT shipped in the wheel.
- Added tests covering the install-guidance message for non-clone installs.

### Docs

- `installation.md` / `installation.ru.md`: clarified that `jira-tempo-mcp install` requires git clone (editable install); Docker runs without install.

## [0.4.2] — 2026-08-08

### Documentation

- **`api.md`/`api.ru.md` — all 15 MCP tools documented** — the reference previously documented only 9 tools; the missing 6 (`preview_report_template`, `list_report_templates`, `get_tempo_worklogs`, `get_jira_issue`, `list_workspace_files`, `convert_report_template`) are now covered with full request/response contracts updated to v0.4.x.
- **`reports.md` — filename format ISO `YYYY-MM-DD`** — the weekly-report filename format was previously documented as `DDMMYY`; it is now documented as ISO `YYYY-MM-DD` (the actual implementation format). No `DDMMYY` references remain.
- **`mcp-integration.md` — phantom tool names fixed** — the MCP integration guide previously referenced tool names that do not exist in the server (phantom names); all references now resolve to real tool names.
- **`deployment.md` — GitHub Actions disabled status clarified** — the deployment guide previously implied CI workflows were active; it now documents explicitly that GitHub Actions are intentionally disabled and that `make ci` is the canonical local verification path.
- **`architecture.md` — tool count 9 → 15, CI reference updated** — the architecture overview previously stated "9 tools"; corrected to 15, with the CI reference updated to the current `make ci` flow.
- **`cli.md` — version 0.4.1, installer flags documented** — the CLI reference previously referenced version `0.1.0` and omitted installer flags; version corrected and installer flags documented.
- **`troubleshooting.md` — `pydantic` → `ConfigError`** — the troubleshooting guide previously attributed config-validation errors to `pydantic`; corrected to `ConfigError` (the actual exception class used by the server).
- **RU terminology unified** (`кастомные` → `пользовательские`) — the Russian documentation previously mixed `кастомные` (anglicism) and `пользовательские`; unified to `пользовательские` across all Russian docs.
- **Emoji-heading anchors fixed across all docs** — Markdown anchors generated from emoji-prefixed headings were broken (GitHub anchor algorithm strips emoji but leaves stray punctuation); all emoji-prefixed headings and their cross-references corrected across 14 files.

## [0.4.1] — 2026-08-08

### Fixed

- **`tasks_report` concurrency bounded** (`tasks_report.py`) — previously called `asyncio.gather` over all users without a `Semaphore`, risking Tempo API rate-limit storms (HTTP 429) and silent empty results on large teams. Now mirrors `team_report.py`: bounded concurrency (`TEMPO_MAX_CONCURRENT_REQUESTS`), inter-batch delay, and retry-on-429 via the shared `_fetch_with_retry` helper. Also caps `max_results` to prevent unbounded pagination.
- **Client retry on transient failures** (`client.py`) — `_request` now optionally retries idempotent GET requests on HTTP 5xx and `httpx.RequestError` with exponential backoff, controlled by `JIRA_HTTP_MAX_RETRIES` (default `0` = current behaviour, backwards-compatible). POST/PUT/DELETE are never retried (avoids duplicate worklogs).
- **Server distinguishes unexpected errors** (`server.py`) — the catch-all `except Exception` in `_call_tool` previously labelled every failure identically. Unexpected errors (not `JiraTempoError`/`ValueError`/`KeyError`) are now prefixed `[unexpected]` with a hint to enable DEBUG, so users can tell a validation error from a latent bug.
- **Tolerant `date_started` parsing in `create_worklog`** (`server.py`) — `datetime.fromisoformat` in Python 3.11 rejected `+0300` (no colon) and microsecond variants. A new `_parse_iso_datetime` helper normalizes these shapes before parsing.
- **Filename hash `md5` → `sha256`** (`team_report.py`) — the per-users filename hash now uses SHA-256 (6-char digest) instead of MD5, satisfying `ruff/B` and removing the only crypto-broken primitive from the codebase.
- **Jinja2 dependency contradiction resolved** (`templates/loader.py`) — the optional-import fallback (classes set to `None` on `ImportError`) was unreachable because `jinja2` is a declared `[project.dependencies]` entry. Jinja2 is now imported unconditionally; dead fallback branches removed.
- **`.py` template code-execution warning strengthened** (`templates/loader.py`) — `REPORT_TEMPLATE_PATH` pointing at a `.py` file previously loaded without warning (unlike `discover_custom_templates`, which warned). Now both paths log prominently; the threat model is also documented in `docs/templates.*`.
- **Secrets redacted from error response bodies** (`client.py`) — API error bodies logged at `ERROR` level (first 200 chars) are now passed through a `_redact_body` filter masking common token patterns (`ghp_`, `hvs.`, `Bearer …`, `sk-`, `xox[bpoa]-`).
- **22 additional low-severity quality fixes** across `client.py`, `config.py`, `report.py`, `_shared.py`, `server.py`, `utils.py`, and the builtin templates — dead-code removal (`format_date_short`, `_resolve_issue_titles` sync version), deterministic `group_worklogs_by_comment_raw` selection (longest raw wins), Unix-newline enforcement in report file writes, cached `extract_seconds` in sort keys, paginated `find_worker_key`, explicit `JiraTempoError.__init__`, `timezone` field validation at config load, duplicate-key fix in the `default` template's remaining-section header, and more.

### Security

- **Security test suite added** (`tests/test_security.py`, 8 tests) — path-traversal rejection in `_validate_output_dir`, Jinja2 sandbox dunder-escape (`{{ config.__class__… }}` blocked), 5xx retry/no-retry semantics, network-error propagation, and `.py`-template warning verification. Previously, security coverage was zero.
- **`Config.__repr__` secret masking now tested** (`tests/test_config.py`) — removed `# pragma: no cover`; asserts `jira_pat` value never appears in `repr(config)`.

### Changed

- **`report_common.py` shared module** (`src/jira_tempo_mcp/report_common.py`) — extracts `resolve_output_dir`, `sort_worklogs_by_issue`, and `write_report_file` helpers previously duplicated across `report.py`, `tasks_report.py`, and `team_report.py` (~40 lines deduplicated). Enforces deterministic Unix newlines in written report files.

### Docs

- **15 MCP tools documented** (`docs/api.md` + `docs/api.ru.md`) — was 9; added `search_users`, `list_user_tasks`, `list_issues_by_jql`, `get_current_user`, `generate_tasks_report`, `preview_report_template`. Contracts for `generate_weekly_report`, `generate_team_report`, `get_issue`, `create_worklog`, `list_report_templates` updated to match `server.py` (`format`, `username`, user-hash, 8 metadata fields, provenance, ISO filenames).
- **Legacy docs modernised** — `reports.md`/`.ru.md` filename format `DDMMYY` → ISO `YYYY-MM-DD`; `mcp-integration.md`/`.ru.md` phantom tool names (`get_tempo_worklogs`/`get_jira_issue`) replaced with real names (`list_worklogs`/`get_issue`); `deployment.md`/`.ru.md` clarifies GitHub Actions are disabled and `make ci` is the canonical gate; `architecture.md`/`.ru.md` tool count 9 → 15; `cli.md`/`.ru.md` version example and installer flags updated; `troubleshooting.md`/`.ru.md` pydantic → `ConfigError`.
- **Quick start Docker tag** (`README.md` + `README.ru.md`) — `:0.3.2` → `:0.4.0`; Features table lists all 15 tools.
- **Broken emoji-heading anchors fixed** across `api.md`, `configuration.md`/`.ru.md`, `reports.md`, `troubleshooting.md` — GitHub strips leading emojis from anchors, leaving a leading dash (`#-custom-templates`, not `#custom-templates`).
- **RU terminology unified** — "пользовательские" vs "кастомные" custom templates consolidated to a single term per doc.

## [0.4.0] — 2026-08-08

### Added

- **`preview_report_template` MCP tool** (`server.py`, `templates/`) — a read-only tool that renders any report template (builtin or custom) against deterministic mock Tempo worklogs without calling Jira/Tempo or writing a file. Three preset `sample_data` profiles (`default` realistic 7-worklog week, `minimal` single worklog, `empty` no worklogs) exercise full and empty-state rendering. The preview uses a fixed week (2026-06-15..19) for deterministic cross-run output, letting users explore templates before running a real report.
- **Template kind/engine provenance in `list_report_templates`** (`server.py`, `templates/loader.py`) — every builtin template (default, weekly_summary, team_report) and loader adapter (JinjaTemplate, PythonTemplate) now declares a `kind` (builtin/custom) and `engine` (Jinja2/Python) attribute. The listing surfaces them, e.g. `- default (builtin, Python): ...`, so users distinguish builtin from custom and Jinja2 from Python at a glance. A `getattr` fallback guards user-supplied `TEMPLATE` objects that may not set these.
- **Custom templates reference** (`docs/templates.md` + `docs/templates.ru.md`) — the author reference for custom report templates: full Jinja2 context table, worklog fields, the Python `ReportTemplate` protocol, the security model (SandboxedEnvironment), and the author workflow. Cross-linked from `docs/reports.md`/`.ru.md` and indexed in the READMEs + `docs/README`.
- **Ready-to-copy template examples** (`examples/templates/standup.j2` + `examples/templates/detailed.j2`) — a compact stand-up summary (total hours, top-3 by time) and a per-issue breakdown with comments and tracked time. Both render against the real sandboxed context.
- **"Custom templates" README section** (`README.md` + `README.ru.md`) — quickstart in 3 steps, the `preview_report_template` workflow, per-OS template directories, the two engines (Jinja2 recommended/sandboxed, Python opt-in), and cross-references to the full reference. EN and RU mirror content; identifiers stay in backticks.
- **"Template tools" section in MCP-integration docs** (`docs/mcp-integration.md` + `docs/mcp-integration.ru.md`) — documents the three template-related MCP tools (`list_report_templates`, `preview_report_template`, `generate_weekly_report` `template` parameter), the `preview_report_template` contract, and a recommended list → preview → generate workflow.

### Fixed

- **App version in MCP `serverInfo`** (`server.py`) — `Server()` was constructed with only a name, so MCP clients saw the SDK version (`SERVER_VERSION`) instead of the app version. The MCP SDK `Server` constructor accepts a `version` keyword, so `__version__` is now passed explicitly, letting clients (and operators) detect which jira-tempo-mcp release is running.

## [0.3.5] — 2026-08-08

### Fixed

- **`report_output_dir` field description corrected** (`config.py`) — the Field description claimed an empty value falls back to `./reports`, but `load_config()` actually substitutes `_DEFAULT_REPORT_DIR` (`~/.mcp/jira-tempo-mcp/reports/`) and never passes an empty string. Updated the description to match the real fallback path. No behavior change — the default value and resolution logic are untouched.
- **Four config tests isolated from the host `.env.local`** (`tests/test_config.py`) — the affected tests read the real `_env_local_candidates`, so a machine with a custom `.env.local` could leak its paths into test outcomes. Each test now patches `_env_local_candidates` to temp dotenv files, making the suite deterministic regardless of the host configuration.
- **RU configuration heading grammar fixed** (`docs/configuration.ru.md`) — corrected a singular/plural mismatch in a section heading.

## [0.3.4] — 2026-08-07

### Added

- **Tests for the dotenv priority chain + silent mkdir** (`tests/test_config.py`, 8 cases) — `TestResilientConfigLoading` (6 cases) covers the full priority chain: process env > `.env.local` > repo `.env` > defaults, idempotent re-application, and `MCP_ENV_FILE` override; `TestGenerateWeeklyReportSilentMkdir` (2 cases) covers silent nested `year/month/weekly` dir creation. Tests use temp dotenv files + `_env_local_candidates` patching so the real machine's `.env.local` never leaks into outcomes. Suite: 286 → 294, no regressions.
- **Agent ↔ MCP contract section** in RU and EN MCP-integration docs — MCP tools are the only sanctioned channel; direct Python/CLI calls from an agent chat are an anti-pattern; on MCP unavailability the agent retries with backoff and escalates a diagnosis, never delegating command execution to the user. RU/EN mirrors stay in sync.

### Changed

- **Config source priority chain documented** in RU and EN configuration docs — `process env > MCP-host .env.local > repo .env`, plus the `MCP_ENV_FILE` override and the default `REPORT_OUTPUT_DIR` (`~/.mcp/jira-tempo-mcp/reports`) with silent year/month/weekly subdirectory creation.

### Fixed

- **Resilient dotenv priority chain** (`config.py`) — direct terminal invocations of the Python module did not read the MCP-host `.env.local` (`~/.config/Code/User/.env.local`), so `REPORT_OUTPUT_DIR` set there was ignored and weekly reports fell back to the default path, forcing manual copies (problem 1, mnemos `735034da`). Added `_apply_dotenv_files()` which loads, with `override=False` (process env always wins), the MCP-host `.env.local` first then the repo `.env`, giving the documented chain: process env → `.env.local` → repo `.env` → defaults. The `.env.local` path is resolved via `MCP_ENV_FILE` override or the standard VS Code user-level locations (Linux/macOS/Windows).

## [0.3.3] — 2026-08-03

### Added

- **`docker-compose.yml`** — single-service compose for running the MCP server in a container, image pinned to the release tag (e.g. `:0.3.3`), secrets via `.env` file (gitignored). Use `docker compose up -d` to run as a managed service or `docker compose run --rm -T jira-tempo-mcp` to drive the server via stdio.
- **README Quick start Docker block expanded** — two options: `docker run --env-file .env ghcr.io/korrnals/jira-tempo-mcp:<version>` (one-liner) and `docker compose up -d` (managed). Image is published to ghcr for every release with version-pinned + `:latest` tags.
- **Tests for installer agent code paths** (`tests/test_install_agent.py`, 6 cases) — cover `install_copilot_agent` / `uninstall_copilot_agent`, `--no-agent` / `--skip-vscode` skip logic, file copy to correct install destinations, missing-source non-blocking skip, uninstall removes only JTM files (foreign agents/skills untouched), idempotent uninstall. Total suite: 280 → 286.

### Changed

- **`JTM_AGENT.md` fallback scenario** — added mention of read-only tools (`get_worklog`, `list_favorite_issues`, `list_user_tasks`, `search_users`) available in manual composition fallback. Write operations (`create_worklog`, `delete_worklog`) explicitly out of scope (agent is read-only on Jira).

### Fixed

- **README Quick start Docker block** previously used `:latest` tag — now pins to the versioned release tag for reproducibility, with `:latest` documented as the tracking option.

## [0.3.2] — 2026-08-03

### Added

- **Standalone JTM Copilot Chat agent** — a ready-to-use AI agent (`JTM: Jira Tempo Reports`) that produces Jira/Tempo worklog reports predictably via the `jira-tempo` MCP generators. Installs by default with `python install.py` into `~/.copilot/agents/` (agent) and `~/.copilot/skills/jira-tempo-reports/` (skill + universal knowledge doc). Escape hatches: `--no-agent` (skip agent on install), `--uninstall-agent` (remove only the agent, keep the MCP server). See README §"JTM Agent" for the full integration matrix.
- **Universal knowledge doc `JTM_AGENT.md`** — IDE-agnostic 7-type report matrix, MCP-tool mapping, work scenarios, and fallback rules. Works with any MCP-capable agent (Cursor, Claude Code, Continue, Aider) that reads it as context. The VS Code wrapper (`copilot-integration/jtm-jira-tempo-reports.agent.md` + `copilot-integration/jira-tempo-reports.skill.md`) adds the interactive `vscode_askQuestions` picker and VS Code-specific behavior on top of this universal layer.
- **Installer agent integration** — `install.py` extended with `install_copilot_agent()` / `uninstall_copilot_agent()`, `--no-agent` and `--uninstall-agent` flags, and a loud announcement block at the end of install confirming the agent location and one-click usage. Full uninstall (`python install.py uninstall`) now also removes the agent + skill + knowledge doc.
- **README §"JTM Agent"** — new section documenting the agent install locations, VS Code one-click usage, and a harness integration table (VS Code, Cursor, Claude Code, Continue, Aider) with the MCP server JSON entry for non-VS Code harnesses.
- **README Quick start uninstall one-liners** — two copy-pasteable one-liners: full uninstall (`python install.py uninstall` / `curl ... | bash -- --uninstall`) and agent-only uninstall (`python install.py --uninstall-agent`).

### Fixed

- **`JTM_AGENT.md` install location** — the universal knowledge doc was initially copied into `~/.copilot/agents/`, which VS Code Copilot Chat scans for agents — it appeared as a second fake agent in the picker. Fixed: `JTM_AGENT.md` now installs into `~/.copilot/skills/jira-tempo-reports/` (next to `SKILL.md`), which VS Code does not scan for agents.

## [0.3.1] — 2026-08-03

### Added

- **Non-interactive installer mode** (`install.py --non-interactive`).
  Enables setup from CI, scripts, and agents without a TTY. CLI flags
  (`--jira-base-url`, `--jira-user`, `--jira-pat`, `--jira-timezone`,
  `--log-level`) and env-var fallbacks replace interactive prompts.
  `--register-only` skips venv/pip and only writes `~/.config/Code/User/.env.local`
  + registers the MCP server in VS Code `mcp.json`. `--skip-vscode` skips
  VS Code registration. Missing required values exit 1 with a clear stderr
  message instead of raising `KeyError`.
- **`ConfigError` diagnostics for missing required env vars** (`config.py`).
  When `JIRA_BASE_URL`, `JIRA_USER`, or `JIRA_PAT` is empty after
  `load_dotenv()`, `load_config()` raises `ConfigError(ValueError)` with
  backend-specific remediation instructions (VS Code `envFile`, CLI `.env`,
  Docker `--env-file`). The message never contains the secret value —
  only the variable name. Replaces pydantic's generic "field required".
- **26 new tests** (19 for `install.py` non-interactive mode, 7 for
  `ConfigError` diagnostics). 245 → 271 total.

### Fixed

- **Broken bullet rendering in worklog reports (all types, all formats).**
  Multi-line worklog comments were collapsed into a single line and templates
  prepended their own marker, producing duplicated markers (`+ + …`) and merged
  actions. Fixed across TXT, Markdown, and JSON for weekly, team, weekly-summary
  and tasks reports:
  - New pure helpers in `templates/_shared.py`: `strip_bullet_marker`,
    `split_comment_lines`, `render_comment_lines` (TXT), `render_comment_cell`
    (MD `<br>`-joined cells), and `group_worklogs_by_comment_raw` (separates the
    normalized grouping key from the raw render payload so newlines survive).
  - Each action now renders as its own bullet with a single unified marker; the
    human-readable time suffix is attached to the last sub-item only.
  - Markdown cells stay table-safe (escaped pipes, `<br>` line breaks); JSON now
    round-trips the raw multi-line comment faithfully.
  - Grouping and time summation are unchanged.
  - 26 new regression tests (219 → 245).

- **Pagination in `client.py`** for `search_worklogs` / `list_user_tasks` / `search_issues` / `list_users` via a new `_paginated_get` helper. Jira REST responses with >100 items were silently truncated (single-page `maxResults`); now pages through `startAt` / `total`. Covered by new `tests/test_client_pagination.py`.
- **`JiraTempoError` attributes** `status_code` / `response_body` declared on the class — removed 3 unjustified `# type: ignore[attr-defined]`; mypy tracks them natively.
- **Bare `except` narrowed to `except ValueError`** in `_request` JSON-parse fallback (catches `json.JSONDecodeError`; no longer swallows `KeyboardInterrupt` / `SystemExit`).
- **Stale tool descriptions corrected** — `generate_weekly_report` / `generate_team_report` referenced a `<DDMMYY>` filename format, but the actual output uses ISO `<YYYY-MM-DD>`.
- **Version sync** — `__init__.py` `__version__` was `0.3.0` while pyproject was `0.3.1`; `cli --version` printed the wrong number.
- **`test_all_tools.py` internal refs removed** (internal hostname, real username) — parameterized, safe for public visibility.
- **LICENSE file added (MIT)** + MIT classifier in pyproject.
- **Local CI scaffold** — `Makefile` + `scripts/local-ci.sh` provide `make ci` / `test` / `lint` / `typecheck` / `build` (GitHub Actions intentionally disabled; local CI is the canonical gate).
- **README badges + Development section** — removed GitHub Actions status badges (Actions disabled); added a Development section documenting `make` targets.

## [0.3.0] — 2026-06-23


### Added

- **New MCP tools:**
  - `list_issues_by_jql` — arbitrary JQL search (read-only, max 100 results).
  - `get_current_user` — authenticated user info (username, displayName, email, key, active).
- **`REPORT_TEAM_USERS` env var** — default list of Jira usernames for team/tasks reports. When set, `generate_team_report` and `generate_tasks_report` can be called without the `users` parameter.
- **`username` parameter on `generate_weekly_report`** — generate weekly reports for any user, not just the configured `JIRA_USER`. Affects filename prefix, report header, and worker key resolution.
- **Dynamic Tempo work attributes** — `create_worklog` proactively queries Tempo for required work attributes on validation failure and returns an actionable hint with attribute names and types.
- **`get_work_attributes()` client method** — queries Tempo `/work-attributes` endpoint (graceful degradation on 404).
- **Report directory structure** — reports organized into subdirectories: `weekly/`, `team/`, `tasks/`, `tasks-team/` under the month directory.
- **`Reports directory:` line** in all report tool results — shows the output directory path.
- **Default report directory** — changed from `Path.cwd()/"reports"` to `~/.mcp/jira-tempo-mcp/reports` (stable across CWD changes).
- 34 new tests (185 → 219): bug/UX coverage, username override, REPORT_TEAM_USERS.

### Changed

- **Markdown report redesign** — all 3 MD report types (weekly, team, tasks) now use professional table-based layout: summary table at top, top-5 issues, per-user tables with total rows. Task summaries truncated to 50 chars, comments to 80 chars with `…`.
- **`get_issue` expanded** — now returns 8 fields (was 3): added priority, assignee, duedate, issuetype, components.
- **`get_worklog` formatted output** — structured key/value display instead of raw Python dict repr. Nested attributes expanded.
- **`list_user_tasks` shows comments** — last 2 comments displayed inline with 💬 marker (was only comment count).
- **`create_worklog` returns full details** — after successful creation, returns complete worklog info (no need for separate `get_worklog` call).
- **ISO dates in filenames** — all report filenames use `2026-06-15_2026-06-19` format (was `150626-190626`).
- **`.env.example` rewrite** — clean sections (Required / Optional / Report config / Advanced), all env vars documented.
- **`search_users` description** — updated to mention email fragment search.

### Fixed

- **`list_user_tasks` status_filter with Russian statuses** (BUG-1) — JQL now uses `statusCategory` mapping instead of localized `status` names. Russian status names ("В работе", "Ожидание", etc.) mapped to category keys.
- **`create_worklog` without required attributes** (BUG-2) — returns actionable error message listing required Tempo work attributes instead of raw API error.
- **`list_worklogs` invalid date** (BUG-3) — local date validation via `_validate_date` before API call (was 500 from server with Java stack trace).
- **`list_worklogs` reversed date range** (BUG-4) — validation error when `date_from > date_to` (was silent 0 results).
- **`generate_team_report` file overwrite** (BUG-5) — filename includes hash of sorted usernames, so different user sets produce different files.
- **`list_favorite_issues` 404 handling** (BUG-6) — distinguishes "endpoint unavailable" from "empty favorites list" with appropriate messages.
- **`parse_tempo_date` critical fix** (BUG-7) — Tempo API returns dates with space separator (`"2026-06-15 00:00:00.000"`) instead of ISO `T`. Now normalized before parsing. This was causing all weekly reports to show 0h.
- **404 noise from `/workers` endpoint** (UX-1) — class-level cache suppresses repeated 404 logs after first failure.

## [0.2.0] — 2026-06-20

### Added

- **Team reports** — new `generate_team_report` MCP tool aggregates worklogs
  for multiple Jira users into a single `.txt` report with per-user sections
  and an aggregate summary (per-user totals, grand total, top 5 issues).
- **Rate-limiting for team reports** — concurrent Tempo requests are bounded
  by `asyncio.Semaphore` (`TEMPO_MAX_CONCURRENT_REQUESTS`, default 3), with a
  configurable delay between batches (`TEMPO_REQUEST_DELAY_MS`, default 100 ms)
  and exponential backoff on HTTP 429 (`TEMPO_MAX_RETRIES`, default 3).
- **Custom report templates** — new template system with a `ReportTemplate`
  protocol and a `TemplateRegistry`. Builtin templates: `default`,
  `weekly_summary`, `team_report`.
- **Jinja2 templates** — `.j2` files discovered from `REPORT_TEMPLATE_DIR`
  are loaded into a `SandboxedEnvironment` (safe by default).
- **Python templates (opt-in)** — `.py` templates loaded only when
  `REPORT_TEMPLATE_ALLOW_PY=1` (code execution risk, explicit opt-in).
- **`list_report_templates` MCP tool** — lists builtin + custom templates.
- **`template` parameter** on `generate_weekly_report` and
  `generate_team_report` to select a template by name.
- New env vars: `TEMPO_MAX_CONCURRENT_REQUESTS`, `TEMPO_REQUEST_DELAY_MS`,
  `TEMPO_MAX_RETRIES`, `REPORT_TEAM_OUTPUT_DIR`, `REPORT_TEMPLATE`,
  `REPORT_TEMPLATE_PATH`, `REPORT_TEMPLATE_DIR`, `REPORT_TEMPLATE_ALLOW_PY`.
- `jinja2>=3.1` added to dependencies.

### Changed

- `generate_weekly_report` now resolves templates through the registry;
  without a `template` argument it falls back to the `default` builtin,
  preserving the exact previous output (backward compatible).
- Report rendering logic extracted into `src/jira_tempo_mcp/templates/`
  package; `report.py` delegates to the selected template.
- Architecture diagram updated to include the templates and team_report
  modules.

### Fixed

- Worklogs returned by Tempo with dates slightly outside the target week
  are now filtered out before rendering (defensive date-range check).

### Security

- Jinja2 templates run in `SandboxedEnvironment` — unsafe constructs
  (e.g. `{{ config.__class__ }}`) are blocked.
- Python templates require explicit opt-in via `REPORT_TEMPLATE_ALLOW_PY=1`
  and log a warning on load.
- `output_dir` for team reports is validated against path traversal, same
  as the weekly report.

### Documentation

- Bilingual docs (EN/RU) updated: `api.md`, `reports.md`,
  `configuration.md`, `architecture.md`, `README.md`.
- New sections: "Team reports", "Custom templates".
- New env vars documented in `configuration.md`.

## [0.1.0] — 2026-06-19

### Added

- Initial release — MCP server for self-hosted Jira (Server / Data Center)
  + Tempo Timesheets 4.
- MCP tools: `list_worklogs`, `get_worklog`, `create_worklog`,
  `delete_worklog`, `get_issue`, `list_favorite_issues`,
  `generate_weekly_report`.
- Async `httpx` client with PAT auth, TLS verification, no redirects.
- Pydantic-validated `Config` with secrets masked in `__repr__`.
- Interactive installer (`jira-tempo-mcp install`) for venv, `.env`, and
  VS Code MCP registration.
- Docker image (multi-stage, non-root, `.dockerignore` for secrets).
- CI/CD pipeline (ruff + mypy + pytest) and release workflow (PyPI + GHCR).
- Bilingual documentation (EN/RU).

### Security

- Tokens never logged; URLs redacted; API error bodies truncated to 200
  chars.
- `output_dir` validated against path traversal.
- `.env` gitignored and created with `0600` permissions.
