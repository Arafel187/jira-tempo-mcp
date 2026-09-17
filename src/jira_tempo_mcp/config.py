"""Configuration loader — reads environment variables, never logs secrets.

Uses pydantic for validation. Secrets are masked in repr so accidental
print(config) does not leak credentials.

Diagnostics: if a required variable (JIRA_BASE_URL, JIRA_USER, JIRA_PAT) is
missing after all sources are loaded, ``load_config`` raises
:class:`ConfigError` with backend-specific remediation instructions. The
exception message never contains the secret value itself — only the variable
name.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytz
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Repo-local .env (one level up from src/). Lowest-priority dotenv source.
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


# MCP-host `.env.local` candidate paths, checked in order. The first existing
# file is loaded. ``MCP_ENV_FILE`` (explicit absolute path) wins; otherwise the
# standard VS Code user-level locations are searched so that direct terminal
# invocations of the Python module read the same secrets the MCP host injects.
# NOTE: distrobox expands ``Path.home()`` to the user's real $HOME
# (/var/home/<user>/.distrobox/<box>/home/...), matching where VS Code writes
# the file — verified 2026-08-07.
def _env_local_candidates() -> list[Path]:
    """Return candidate ``.env.local`` paths in priority order.

    Order: explicit ``MCP_ENV_FILE`` override first, then standard VS Code
    user-level locations (Linux, macOS, Windows). Only paths that exist are
    useful at call time, but the full ordered list is returned so callers can
    log/report which locations were searched.
    """
    home = Path.home()
    explicit = os.getenv("MCP_ENV_FILE", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    # Standard VS Code user-level .env.local locations.
    candidates.extend(
        [
            home / ".config" / "Code" / "User" / ".env.local",  # Linux
            home / "Library" / "Application Support" / "Code" / "User" / ".env.local",  # macOS
            home / "AppData" / "Roaming" / "Code" / "User" / ".env.local",  # Windows
        ]
    )
    return candidates


def _apply_dotenv_files() -> None:
    """Apply dotenv sources with a documented priority chain.

    Priority (highest first, because ``load_dotenv(override=False)`` never
    overwrites a value already in ``os.environ``):

    1. **Process environment** — always wins.
    2. **MCP-host ``.env.local``** — the first existing candidate from
       :func:`_env_local_candidates` (or ``MCP_ENV_FILE`` override).
    3. **Repo-local ``.env``** — ``.env`` at the repository root.

    Within dotenv files, the FIRST file to define a key wins (because
    ``override=False`` keeps the value already set). We load ``.env.local``
    before the repo ``.env`` so the MCP-host file takes priority over the
    repo file for keys absent from the process environment.

    This is idempotent: calling it again only fills keys still missing from
    ``os.environ``, so re-invocation during tests or hot-reload is safe.
    """
    # 1. MCP-host .env.local (explicit override or standard VS Code location).
    for candidate in _env_local_candidates():
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            break
    # 2. Repo-local .env — never overrides .env.local or process env.
    if _ENV_PATH.is_file():
        load_dotenv(_ENV_PATH, override=False)


# Apply dotenv sources at import time so module-level os.getenv calls in
# load_config() see the merged environment. Idempotent and safe to re-run.
_apply_dotenv_files()


class ConfigError(ValueError):
    """Raised when a required configuration value is missing.

    Inherits from ``ValueError`` so existing ``except ValueError`` handlers
    and pydantic-aware test suites (``pytest.raises((RuntimeError, ValueError))``)
    keep working. The message lists backend-specific remediation steps and
    never includes secret values.
    """


# Required env vars validated explicitly before pydantic — gives the user a
# backend-specific remediation message instead of pydantic's generic
# "field required".
_REQUIRED_ENV_VARS: tuple[tuple[str, str], ...] = (
    ("JIRA_BASE_URL", "Base URL of your Jira instance"),
    ("JIRA_USER", "Jira username (login)"),
    ("JIRA_PAT", "Jira Personal Access Token (PAT)"),
)


def _missing_var_message(var_name: str, description: str) -> str:
    """Build a backend-specific remediation message for a missing env var.

    The message intentionally never echoes the secret value (which is empty
    anyway at this point) — only the variable name and description.
    """
    return (
        f"{var_name} ({description}) не найден в окружении. "
        "Проверьте источник (в порядке приоритета):\n"
        "  • VS Code MCP: укажите envFile в mcp.json → "
        "~/.config/Code/User/.env.local (см. docs/mcp-integration.ru.md)\n"
        "  • CLI: создайте .env в корне репо (cp .env.example .env)\n"
        "  • Docker: передайте --env-file при запуске\n"
        "Запустите `python install.py --non-interactive --register-only` "
        "для автоматической настройки."
    )


# --- Default section mapping for weekly reports ---
# Maps issue keys to report section titles. Can be overridden via
# REPORT_SECTION_MAP env var (JSON dict) or a JSON file at REPORT_SECTION_MAP_FILE.
# Default section mapping for weekly reports.
# Empty by default — users provide their own via REPORT_SECTION_MAP env var
# or REPORT_SECTION_MAP_FILE. See README for format.
DEFAULT_SECTION_MAP: dict[str, str] = {}

# Stable sections that always appear (in this order) if they have worklogs.
# Empty by default — users provide their own via REPORT_STABLE_ORDER env var.
DEFAULT_STABLE_ORDER: list[str] = []

# Non-issue sections (no issue key in the report line).
# Empty by default — users provide their own via REPORT_NON_ISSUE_SECTIONS env var.
DEFAULT_NON_ISSUE_SECTIONS: list[str] = []

# Default directory for custom report templates (expanded at load time).
_DEFAULT_TEMPLATE_DIR = str(Path.home() / ".config" / "jira-tempo-mcp" / "templates")

# Default directory for task-template overrides (expanded at load time).
# Task templates (parent issue + child subtasks from YAML) are built into the
# package; this directory holds user overrides/additions discovered on top.
# Empty by default — when unset, only built-in templates are available.
_DEFAULT_TASK_TEMPLATE_DIR = ""

# Default base directory for report output when REPORT_OUTPUT_DIR env is not set.
# Uses ~/.mcp/jira-tempo-mcp/reports so reports land in a stable, predictable
# location regardless of the MCP server process CWD.
_DEFAULT_REPORT_DIR = str(Path.home() / ".mcp" / "jira-tempo-mcp" / "reports")


class Config(BaseModel):
    """Runtime configuration loaded from environment.

    Secrets are held in this model and never logged. The __repr__ masks
    token fields so accidental print(config) does not leak credentials.
    """

    model_config = ConfigDict(frozen=True)

    jira_base_url: str = Field(min_length=1)
    jira_user: str = Field(min_length=1)
    jira_pat: str = Field(min_length=1)
    timezone: str = "Europe/Moscow"
    tempo_api_token: str | None = None  # falls back to jira_pat if empty
    log_level: str = "INFO"

    # Report configuration (M3, M4 — externalized from report.py).
    report_output_dir: str = Field(
        default="",
        description="Base directory for weekly reports. Empty = falls back to `~/.mcp/jira-tempo-mcp/reports/` via `load_config()`.",
    )
    author_display_name: str = Field(
        default="",
        description="Display name in report header. Empty = use jira_user.",
    )
    report_filename_prefix: str = Field(
        default="",
        description="Prefix for weekly report filenames. Empty = use jira_user.",
    )
    section_map: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_SECTION_MAP),
        description="Maps issue keys to report section titles.",
    )
    stable_order: list[str] = Field(
        default_factory=lambda: list(DEFAULT_STABLE_ORDER),
        description="Issue keys that always appear in this order if they have worklogs.",
    )
    non_issue_sections: list[str] = Field(
        default_factory=lambda: list(DEFAULT_NON_ISSUE_SECTIONS),
        description="Sections without issue keys (planerki, Jira work).",
    )

    # HTTP timeout (m5 — configurable).
    http_timeout: float = Field(default=30.0, gt=0)

    # HTTP retries for transient server/network errors (v0.4.1 — finding #11).
    # Applied at the low-level _request() layer to idempotent GET requests only.
    # Default 0 preserves the original fail-fast behaviour (backwards compatible).
    http_max_retries: int = Field(
        default=0,
        ge=0,
        description="Max retry attempts for idempotent GET on HTTP 5xx / network errors (exponential backoff). 0 = fail fast (backwards compatible).",
    )

    # --- Team report rate-limiting (v0.2.0) ---
    tempo_max_concurrent_requests: int = Field(
        default=3,
        ge=1,
        description="Semaphore limit for concurrent Tempo requests in team reports.",
    )
    tempo_request_delay_ms: int = Field(
        default=100,
        ge=0,
        description="Delay (ms) between request batches in team reports.",
    )
    tempo_max_retries: int = Field(
        default=3,
        ge=0,
        description="Max retry attempts for HTTP 429 responses.",
    )
    report_team_output_dir: str = Field(
        default="",
        description="Output dir for team reports. Empty = use report_output_dir.",
    )

    report_team_users: list[str] = Field(
        default_factory=list,
        description="Default list of Jira usernames for team/tasks reports.",
    )

    # --- Custom report templates (v0.2.0) ---
    report_template: str = Field(
        default="default",
        description="Name of the template used by generate_weekly_report.",
    )
    report_template_path: str = Field(
        default="",
        description="Explicit path to a template file (overrides report_template).",
    )
    report_template_dir: str = Field(
        default="",
        description="Directory scanned for custom templates (.py / .j2).",
    )
    report_template_allow_py: bool = Field(
        default=False,
        description="Opt-in flag to load .py templates (code execution risk).",
    )

    # --- Task templates (parent issue + child subtasks from YAML) ---
    task_template_dir: str = Field(
        default="",
        description="Directory scanned for task-template overrides (*.yaml). "
        "User files with the same template name override built-ins. "
        "Empty = built-in templates only.",
    )

    def __repr__(self) -> str:
        """Masked repr — secrets (jira_pat, tempo_api_token) never appear.

        Covered by tests/test_config.py::TestConfigValidation::test_repr_* to
        guard against regressions that would leak a secret via repr/logging.
        """
        return (
            f"Config(jira_base_url={self.jira_base_url!r}, "
            f"jira_user={self.jira_user!r}, "
            f"jira_pat=***, timezone={self.timezone!r}, "
            f"tempo_api_token={'***' if self.tempo_api_token else 'None'}, "
            f"log_level={self.log_level!r})"
        )

    @property
    def tempo_token(self) -> str:
        """Tempo auth token — uses TEMPO_API_TOKEN if set, else JIRA_PAT."""
        return self.tempo_api_token or self.jira_pat

    @property
    def tempo_api_base(self) -> str:
        return f"{self.jira_base_url.rstrip('/')}/rest/tempo-timesheets/4"

    @property
    def jira_api_base(self) -> str:
        return f"{self.jira_base_url.rstrip('/')}/rest/api/2"

    @property
    def report_author_header(self) -> str:
        """Author name for report header — uses author_display_name or jira_user."""
        return self.author_display_name or self.jira_user

    @property
    def report_filename_header(self) -> str:
        """Filename prefix for weekly reports — uses report_filename_prefix or jira_user."""
        return self.report_filename_prefix or self.jira_user

    @property
    def team_output_dir(self) -> str:
        """Output dir for team reports — falls back to report_output_dir."""
        return self.report_team_output_dir or self.report_output_dir

    @property
    def team_users_resolved(self) -> list[str]:
        """Default users for team/tasks reports.

        Returns ``report_team_users`` when non-empty, else falls back to
        ``[jira_user]`` so a team report with no users and no env still works
        for the current user.

        .. note::

            An **unset or empty** ``report_team_users`` always resolves to
            ``[jira_user]`` — it never returns an empty list. To generate a
            report for zero users, filter downstream (pass an explicit empty
            ``users=`` argument through to the report generator) rather than
            relying on this property to surface an empty set.
        """
        return list(self.report_team_users) if self.report_team_users else [self.jira_user]

    @property
    def template_dir_resolved(self) -> str:
        """Resolved custom template directory (default: ~/.config/jira-tempo-mcp/templates)."""
        return self.report_template_dir or _DEFAULT_TEMPLATE_DIR

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.strip().upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return upper

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        """Validate ``timezone`` via pytz at config load time (not runtime).

        Without this an invalid zone (e.g. ``Europe/Moskow`` typo) would crash
        the first time ``datetime.now(pytz.timezone(tz))`` runs, far from the
        configuration source. Validating at load yields a clear, actionable
        error at startup instead.
        """
        try:
            pytz.timezone(v)
        except pytz.UnknownTimeZoneError as exc:
            raise ValueError(
                f"Unknown timezone {v!r}. Use an IANA/pytz zone name like "
                "'Europe/Moscow', 'UTC', or 'America/New_York'. "
                "List: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
            ) from exc
        return v


def _load_section_map() -> dict[str, str]:
    """Load section map from env var (JSON) or file, falling back to default."""
    raw = os.getenv("REPORT_SECTION_MAP", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, TypeError):
            pass

    file_path = os.getenv("REPORT_SECTION_MAP_FILE", "").strip()
    if file_path:
        try:
            p = Path(file_path)
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
        except (json.JSONDecodeError, TypeError, OSError):
            pass

    return dict(DEFAULT_SECTION_MAP)


def _load_json_list(env_var: str) -> list[str]:
    """Load a JSON list of strings from an env var.

    Returns an empty list if the var is unset, empty, or holds invalid JSON.
    Non-string items are coerced to str.
    """
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(item) for item in data]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _load_int(env_var: str, default: int) -> int:
    """Load an integer env var with a fallback."""
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _load_bool(env_var: str, default: bool) -> bool:
    """Load a boolean env var (1/0, true/false, yes/no)."""
    raw = os.getenv(env_var, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def load_config() -> Config:
    """Load configuration from environment. Raises if required vars are missing.

    Raises :class:`ConfigError` (subclass of :class:`ValueError`) with a
    backend-specific remediation message if any required env var
    (JIRA_BASE_URL, JIRA_USER, JIRA_PAT) is missing or empty after
    ``load_dotenv`` has run. The message never contains secret values.
    """
    base_url = os.getenv("JIRA_BASE_URL", "").strip()
    user = os.getenv("JIRA_USER", "").strip()
    pat = os.getenv("JIRA_PAT", "").strip()

    # Explicit diagnostics BEFORE pydantic — gives the user a precise,
    # backend-specific remediation message instead of pydantic's generic
    # "field required". Iterate in declared order so the first missing
    # required var is reported (pydantic would also report the first one).
    for var_name, description in _REQUIRED_ENV_VARS:
        value = os.getenv(var_name, "").strip()
        if not value:
            raise ConfigError(_missing_var_message(var_name, description))

    tz = os.getenv("JIRA_TIMEZONE", "Europe/Moscow").strip()
    tempo_token = os.getenv("TEMPO_API_TOKEN", "").strip() or None
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    report_output_dir = os.getenv("REPORT_OUTPUT_DIR", "").strip() or _DEFAULT_REPORT_DIR
    author_display_name = os.getenv("REPORT_AUTHOR_NAME", "").strip()
    report_filename_prefix = os.getenv("REPORT_FILENAME_PREFIX", "").strip()
    stable_order = _load_json_list("REPORT_STABLE_ORDER")
    non_issue_sections = _load_json_list("REPORT_NON_ISSUE_SECTIONS")
    http_timeout_str = os.getenv("JIRA_HTTP_TIMEOUT", "30.0").strip()
    # v0.4.1 — low-level HTTP retries for idempotent GET on 5xx / network errors.
    http_max_retries = _load_int("JIRA_HTTP_MAX_RETRIES", 0)

    # v0.2.0 — team report rate-limiting + templates.
    tempo_max_concurrent = _load_int("TEMPO_MAX_CONCURRENT_REQUESTS", 3)
    tempo_request_delay_ms = _load_int("TEMPO_REQUEST_DELAY_MS", 100)
    tempo_max_retries = _load_int("TEMPO_MAX_RETRIES", 3)
    report_team_output_dir = os.getenv("REPORT_TEAM_OUTPUT_DIR", "").strip()
    report_team_users = _load_json_list("REPORT_TEAM_USERS")
    report_template = os.getenv("REPORT_TEMPLATE", "default").strip() or "default"
    report_template_path = os.getenv("REPORT_TEMPLATE_PATH", "").strip()
    report_template_dir = os.getenv("REPORT_TEMPLATE_DIR", "").strip()
    report_template_allow_py = _load_bool("REPORT_TEMPLATE_ALLOW_PY", False)

    # Task templates (parent issue + child subtasks from YAML).
    task_template_dir = os.getenv("JTM_TEMPLATES_DIR", "").strip()

    try:
        http_timeout = float(http_timeout_str)
    except ValueError:
        http_timeout = 30.0

    # pydantic will validate non-empty constraints.
    return Config(
        jira_base_url=base_url,
        jira_user=user,
        jira_pat=pat,
        timezone=tz,
        tempo_api_token=tempo_token,
        log_level=log_level,
        report_output_dir=report_output_dir,
        author_display_name=author_display_name,
        report_filename_prefix=report_filename_prefix,
        section_map=_load_section_map(),
        stable_order=stable_order,
        non_issue_sections=non_issue_sections,
        http_timeout=http_timeout,
        http_max_retries=http_max_retries,
        tempo_max_concurrent_requests=tempo_max_concurrent,
        tempo_request_delay_ms=tempo_request_delay_ms,
        tempo_max_retries=tempo_max_retries,
        report_team_output_dir=report_team_output_dir,
        report_team_users=report_team_users,
        report_template=report_template,
        report_template_path=report_template_path,
        report_template_dir=report_template_dir,
        report_template_allow_py=report_template_allow_py,
        task_template_dir=task_template_dir,
    )
