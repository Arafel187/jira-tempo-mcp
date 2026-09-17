# 🏗️ Архитектура

Слоистая архитектура: каждый модуль несёт одну ответственность, зависимости
направлены в одну сторону.

---

## 🏗️ Слои

```mermaid
flowchart TD
    S[server.py<br/>MCP-сервер + 17 инструментов + валидация] --> C[client.py<br/>HTTP-клиент Jira + Tempo]
    S --> R[report.py<br/>Генератор еженедельного отчёта]
    S --> U[utils.py<br/>Разбор длительности, форматирование, tz]
    S --> CFG[config.py<br/>Загрузка env, модель Config, секреты замаскированы]
    C --> CFG
    R --> C
    R --> CFG
    R --> U
```

| Слой | Файл | Ответственность |
| --- | --- | --- |
| MCP-сервер | `server.py` | JSON-RPC через stdio, определения инструментов, таблица диспетчеризации, валидация ввода, пользовательские ошибки |
| HTTP-клиент | `client.py` | Jira REST API + Tempo Timesheets 4 API, авторизация PAT, TLS, без редиректов, редукция ошибок |
| Генератор отчётов | `report.py` | Еженедельный отчёт: выборка worklog'ов, делегирование рендеринга системе шаблонов, запись `.txt` |
| Командный отчёт | `team_report.py` | Командный отчёт: агрегация worklog'ов по пользователям с семафором и повтором 429 |
| Шаблоны | `templates/` | Протокол `ReportTemplate`, `TemplateRegistry`, встроенные шаблоны, Jinja2-песочница + opt-in Python-загрузчик |
| Конфиг | `config.py` | Загрузка env через pydantic, модель `Config`, секреты замаскированы в `__repr__` |
| Утилиты | `utils.py` | Чистые помощники: разбор длительности, секунды→человек, `iso_now` с учётом часового пояса |
| CLI | `cli.py` | Диспетчер консольной точки входа (`serve` / `install` / `uninstall` / `--version`) |
| Установщик | `install.py` | Интерактивная настройка: venv, `.env`, регистрация в VS Code `mcp.json`, проверка связи |

---

## 🔄 Поток данных

```mermaid
sequenceDiagram
    participant A as AI-агент (Copilot)
    participant S as server.py
    participant C as client.py
    participant J as Jira/Tempo API
    A->>S: JSON-RPC вызов инструмента (stdin)
    S->>S: валидация ввода (ключ задачи, дата, длительность)
    S->>C: асинхронный вызов (JiraTempoClient)
    C->>J: HTTPS GET/POST + Bearer PAT
    J-->>C: JSON-ответ
    C-->>S: разобранный dict / возбуждает JiraTempoError
    S-->>A: результат TextContent (stdout)
```

1. AI-агент отправляет JSON-RPC вызов инструмента через stdin.
2. `server.py` валидирует ввод (регекс ключа задачи, ISO-дата, токены длительности).
3. Обработчик вызывает `JiraTempoClient` (асинхронный `httpx`).
4. Клиент отправляет HTTPS-запрос с заголовком Bearer PAT.
5. При успехе разобранный JSON возвращается в обработчик.
6. При ошибке возбуждается `JiraTempoError` с редуцированным сообщением.
7. Обработчик форматирует результат в строку и возвращает `TextContent`.

---

## ⚙️ Диспетчеризация инструментов

Инструменты регистрируются в списке `TOOLS` и диспетчеризуются через таблицу:

```python
_TOOL_HANDLERS: dict[str, Any] = {
    "list_worklogs": _handle_list_worklogs,
    "get_worklog": _handle_get_worklog,
    "create_worklog": _handle_create_worklog,
    "delete_worklog": _handle_delete_worklog,
    "get_issue": _handle_get_issue,
    "list_favorite_issues": _handle_list_favorites,
    "generate_weekly_report": _handle_generate_report,
    "generate_team_report": _handle_generate_team_report,
    "list_report_templates": _handle_list_templates,
    "preview_report_template": _handle_preview_template,
    "search_users": _handle_search_users,
    "list_user_tasks": _handle_list_user_tasks,
    "list_issues_by_jql": _handle_list_issues_by_jql,
    "get_current_user": _handle_get_current_user,
    "generate_tasks_report": _handle_generate_tasks_report,
}
```

Каждый обработчик — `async`-функция, принимающая `(arguments, config, client)`
и возвращающая строку. Ошибки перехватываются в `_call_tool` и
преобразуются в пользовательские сообщения через `_user_friendly_error`.

---

## 🔒 Безопасность

### 🔑 Обработка токенов

- **Токены не покидают локальный процесс.** `JIRA_PAT` читается из окружения
  и отправляется только на инстанс Jira через HTTPS.
- **`.env` в `.gitignore`** и создаётся с правами `0600` на POSIX.
- **Токены замаскированы в логах** — `Config.__repr__` заменяет `JIRA_PAT`
  на `***`.
- **Сообщения об ошибках редуцируются** — `_redact()` очищает URL от
  учётных данных перед логированием. Тела ошибок API обрезаются до 200 символов.
- AI-агент получает только **результат** вызовов API, никогда сам токен.

### 🛡️ Усиление транспорта

- **TLS-верификация всегда включена** (`httpx.AsyncClient(verify=True)`).
- **HTTP-редиректы отключены** (`follow_redirects=False`) — предотвращает
  утечку PAT через редирект на подконтрольный злоумышленнику хост.
- **Настраиваемый HTTP-таймаут** (`JIRA_HTTP_TIMEOUT`, по умолч. 30 с).

### ✅ Валидация ввода

- **Ключи задач Jira** проверяются по `^[A-Z][A-Z0-9]+-\d+$`.
- **Даты** проверяются как ISO `YYYY-MM-DD`.
- **`output_dir` отчёта** проверяется на path traversal — разрешённый путь
  должен быть внутри разрешённого корня (`REPORT_OUTPUT_DIR` или `./reports`).

### 🐳 Безопасность сборки Docker

- `.dockerignore` исключает `.env`, `.env.*.local`, `.history/`, `.venv/`,
  `__pycache__/`, `.git/`, `tests/`.
- Многостадийная сборка — runtime-образ содержит только установленный wheel.
- Запуск от non-root пользователя `appuser` (UID 1001) без shell.
- Секреты никогда не вшиваются в образ — передаются при запуске через
  `--env-file` или Kubernetes Secret.

> 💡 **Совет:** Подробнее о Docker — в [deployment.ru.md](deployment.ru.md).

---

## 🧪 Тестирование

Тесты лежат в `tests/` (15 файлов) и запускаются под `pytest` с
`asyncio_mode = "auto"`:

| Файл | Покрывает |
| --- | --- |
| `test_config.py` | валидация `Config`, загрузка env, маскировка секретов |
| `test_config_diagnostics.py` | сообщения `ConfigError`, backend-специфичные рекомендации |
| `test_utils.py` | разбор длительности, форматирование, помощники часового пояса |
| `test_report.py` | логика генерации отчёта (unit) |
| `test_report_integration.py` | end-to-end отчёт с замоканным клиентом |
| `test_team_report.py` | агрегация командного отчёта, конкурентность, повтор 429 |
| `test_tasks_report.py` | генерация отчёта по задачам |
| `test_templates.py` | реестр шаблонов, встроенные шаблоны |
| `test_templates_dx.py` | помощники developer experience (DX) для шаблонов |
| `test_client_pagination.py` | пагинация клиента, обработка курсора |
| `test_security.py` | маскировка секретов, редукция, защита от path traversal |
| `test_bugs_and_ux.py` | регрессионные баги и edge-cases UX |
| `test_install.py` | поток установщика (интерактивный) |
| `test_install_noninteractive.py` | путь `--non-interactive` установщика |
| `test_install_agent.py` | установка/удаление агента Copilot Chat |

Канонический CI-порог — `make ci`: прогоняет `ruff check` + `ruff format
--check` + `mypy src/` + `pytest tests/ -v` на Python 3.12, повторяя то, что
запускал бы GitHub Actions `ci.yml`. **GitHub Actions отключены в этом
окружении** (billing заблокирован), поэтому зелёный `make ci` — сигнал для
merge/релиза. См. [deployment.ru.md](deployment.ru.md#-cicd).

---

## ➡️ Дальнейшие шаги

- 🌐 [api.ru.md](api.ru.md) — 15 MCP-инструментов
- 🐳 [deployment.ru.md](deployment.ru.md) — Docker, CI/CD, релизы
- ⚙️ [configuration.ru.md](configuration.ru.md) — переменные окружения и обработка секретов
