# 🌐 API — MCP-инструменты

Сервер открывает 15 инструментов через Model Context Protocol. Каждый
инструмент определён в `src/jira_tempo_mcp/server.py` и диспетчеризуется
через таблицу (`_TOOL_HANDLERS`).

---

## 🌐 Индекс инструментов

| Инструмент | Группа | Назначение |
| --- | --- | --- |
| [`list_worklogs`](#-list_worklogs) | Worklog'и | Список worklog'ов за период или один день |
| [`get_worklog`](#-get_worklog) | Worklog'и | Получить один worklog по Tempo ID |
| [`create_worklog`](#-create_worklog) | Worklog'и | Учесть время на задаче Jira |
| [`delete_worklog`](#-delete_worklog) | Worklog'и | Удалить worklog по ID |
| [`get_issue`](#-get_issue) | Задачи | Получить метаданные задачи Jira (9 полей, включая описание) |
| [`list_favorite_issues`](#-list_favorite_issues) | Задачи | Список избранных задач текущего пользователя |
| [`list_issues_by_jql`](#-list_issues_by_jql) | Задачи | Поиск задач через JQL-запрос |
| [`get_current_user`](#-get_current_user) | Пользователи | Данные аутентифицированного пользователя |
| [`search_users`](#-search_users) | Пользователи | Поиск пользователей Jira по имени или email |
| [`list_user_tasks`](#-list_user_tasks) | Пользователи | Задачи, назначенные пользователю |
| [`generate_weekly_report`](#-generate_weekly_report) | Отчёты | Сгенерировать еженедельный отчёт (`txt`/`md`/`json`) |
| [`generate_team_report`](#-generate_team_report) | Отчёты | Сгенерировать командный отчёт для нескольких пользователей |
| [`generate_tasks_report`](#-generate_tasks_report) | Отчёты | Сгенерировать отчёт по задачам, сгруппированный по статусу |
| [`list_report_templates`](#-list_report_templates) | Отчёты | Показать доступные шаблоны отчётов |
| [`preview_report_template`](#-preview_report_template) | Отчёты | Предпросмотр шаблона с тестовыми данными |

---

## 📝 `list_worklogs`

Список worklog'ов Tempo за период (или один день). Возвращается только
фактически учтённое время — плановое исключается.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `date_from` | string | нет | Начальная дата (ISO `YYYY-MM-DD`). По умолч. сегодня. |
| `date_to` | string | нет | Конечная дата (ISO `YYYY-MM-DD`). По умолч. `date_from`. |

**Пример вызова:**

```json
{
  "name": "list_worklogs",
  "arguments": {
    "date_from": "2026-06-16",
    "date_to": "2026-06-20"
  }
}
```

**Возвращает:** по одной строке на worklog:

```text
Worklogs 2026-06-16 .. 2026-06-20 (5 entries):
- 2026-06-16 | PROJECT-100 | 1h 30m | id=12345 | Implemented login flow
- 2026-06-17 | PROJECT-101 | 2h | id=12346 | Code review
```

---

## 🔍 `get_worklog`

Получить один worklog Tempo по его внутреннему ID.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `worklog_id` | string | да | ID worklog'а Tempo |

**Пример вызова:**

```json
{
  "name": "get_worklog",
  "arguments": { "worklog_id": "12345" }
}
```

**Возвращает:** строки ключ/значение со всеми полями worklog'а:

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

Учесть время на задаче Jira через Tempo. Worklog приписывается владельцу
токена, если не задан `author_account_id`.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `issue_key` | string | да | Ключ задачи Jira (напр. `PROJECT-100`) |
| `time_spent` | string | да | Длительность: `1h 30m`, `2h`, `45m`, `1d 2h` |
| `comment` | string | нет | Опциональный комментарий к worklog'у |
| `date_started` | string | нет | Дата в формате `YYYY-MM-DD` (напр. `2026-06-19`). Полные ISO datetime также принимаются и нормализуются до даты. По умолч. сегодня. |
| `author_account_id` | string | нет | Опциональный Tempo worker key. По умолч. владелец токена. |
| `attributes` | object | нет | Опциональные рабочие атрибуты Tempo (напр. `{"_Специализация_": "Devops", "_Форматработы_": "Удаленно"}`). **Обязательны на некоторых инсталляциях** — при ошибке `VALIDATION_FAILED` укажите их. |

> 💡 **Совет:** Единицы длительности: `w` (неделя = 5d), `d` (день = 8h), `h` (час), `m` (минута).

**Пример вызова:**

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

**Возвращает:** строку подтверждения плюс полные детали worklog'а:

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

Удалить worklog Tempo по его ID. Используется для отмены/исправления
неправильно учтённого времени.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `worklog_id` | string | да | ID worklog'а Tempo для удаления |

**Пример вызова:**

```json
{
  "name": "delete_worklog",
  "arguments": { "worklog_id": "12345" }
}
```

**Возвращает:**

```text
Deleted worklog 12345.
```

---

## 📋 `get_issue`

Получить метаданные задачи Jira: summary, описание, статус, проект,
приоритет, исполнителя, срок, тип задачи и компоненты (9 полей).

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `issue_key` | string | да | Ключ задачи Jira (напр. `PROJECT-100`) |

**Пример вызова:**

```json
{
  "name": "get_issue",
  "arguments": { "issue_key": "PROJECT-100" }
}
```

**Возвращает:**

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

## ⭐ `list_favorite_issues`

Список избранных задач текущего пользователя Jira. Возвращает ключи и summary.

**Параметры:** нет.

**Пример вызова:**

```json
{
  "name": "list_favorite_issues",
  "arguments": {}
}
```

**Возвращает:**

```text
Favorite issues (3):
- PROJECT-100: Implement login flow
- PROJECT-101: Code review process
- PROJECT-102: Fix CI pipeline
```

---

## 📝 `generate_weekly_report`

Сгенерировать еженедельный отчёт из worklog'ов Tempo и сохранить его как
файл. Группирует worklog'и по задачам, отображает известные задачи в
стабильные секции и записывает `<prefix>_<YYYY-MM-DD>_<YYYY-MM-DD>.<fmt>` в
настроенную директорию. С версии v0.3.0 параметр `format` выбирает формат:
`txt` (по умолч.), `md` (Markdown) или `json`.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `target_date` | string | нет | Любая дата целевой недели (ISO `YYYY-MM-DD`). По умолч. сегодня. |
| `output_dir` | string | нет | Директория вывода. По умолч. `REPORT_OUTPUT_DIR` или `~/.mcp/jira-tempo-mcp/reports/`. Должна быть внутри разрешённого корня. |
| `template` | string | нет | Имя шаблона (напр. `default`, `weekly_summary`). По умолч. `REPORT_TEMPLATE` или `default`. Используется только при `format='txt'`. |
| `format` | string | нет | Формат вывода: `txt` (текст, по умолч.), `md` (Markdown), `json` (структурированный JSON). Расширение файла соответствует формату. |
| `username` | string | нет | Опциональное имя пользователя Jira для отчёта (вместо настроенного `JIRA_USER`). Если указано, worklog'и фильтруются по этому пользователю. |

**Пример вызова:**

```json
{
  "name": "generate_weekly_report",
  "arguments": { "target_date": "2026-06-19", "format": "md" }
}
```

**Возвращает:**

```text
Weekly report generated: /home/user/.mcp/jira-tempo-mcp/reports/golikhin_2026-06-15_2026-06-19.md
Reports directory: /home/user/.mcp/jira-tempo-mcp/reports
```

> 💡 **Совет:** Настройка отчёта (маппинг секций, стабильный порядок, не-задачные
> секции) — в [reports.ru.md](reports.ru.md).

---

## 👥 `generate_team_report`

Сгенерировать командный отчёт из worklog'ов Tempo для нескольких
пользователей Jira. Для каждого пользователя загружаются worklog'ы с
ограничением параллельности (защита от rate-limit), рендерятся секции по
пользователям и агрегированная сводка, файл
`team_<YYYY-MM-DD>_<YYYY-MM-DD>_<users_hash>.<fmt>` записывается в
настроенную директорию. С версии v0.3.0 параметр `format` выбирает формат:
`txt` (по умолч.), `md` или `json`.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `users` | array<string> | нет | Имена пользователей Jira. Если не указаны, используется `REPORT_TEAM_USERS` или текущий пользователь. |
| `date_from` | string | нет | Начальная дата (ISO `YYYY-MM-DD`). По умолч. понедельник текущей недели. |
| `date_to` | string | нет | Конечная дата (ISO `YYYY-MM-DD`). По умолч. пятница текущей недели. |
| `section_map` | object | нет | Опциональная замена для `REPORT_SECTION_MAP` (ключ задачи → заголовок секции) |
| `template` | string | нет | Имя шаблона. По умолч. `team_report`. Используется только при `format='txt'`. |
| `output_dir` | string | нет | Директория вывода. По умолч. `REPORT_TEAM_OUTPUT_DIR` или `REPORT_OUTPUT_DIR`. Должна быть внутри разрешённого корня. |
| `format` | string | нет | Формат вывода: `txt` (текст, по умолч.), `md` (Markdown), `json` (структурированный JSON). Расширение файла соответствует формату. |

> 🛡️ **Ограничение скорости (rate-limiting):** параллельные запросы к Tempo
> ограничены `TEMPO_MAX_CONCURRENT_REQUESTS` (по умолч. 3). Между пакетами
> запросов вставляется задержка `TEMPO_REQUEST_DELAY_MS` (по умолч. 100 мс).
> При HTTP 429 клиент повторяет запрос с экспоненциальной задержкой до
> `TEMPO_MAX_RETRIES` (по умолч. 3) раз.

**Пример вызова:**

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

**Возвращает:**

```text
Team report: 3 users, 24h total. Written to /home/user/.mcp/jira-tempo-mcp/reports/team_2026-06-15_2026-06-19_a1b2c3.md
Reports directory: /home/user/.mcp/jira-tempo-mcp/reports
```

---

## 🎨 `list_report_templates`

Показать доступные шаблоны отчётов (встроенные + пользовательские). Возвращает имя
каждого шаблона, происхождение (`builtin` или `custom`), движок (`Jinja2`
или `Python`) и описание. Кастомные шаблоны обнаруживаются в
`REPORT_TEMPLATE_DIR`.

**Параметры:** нет.

**Пример вызова:**

```json
{
  "name": "list_report_templates",
  "arguments": {}
}
```

**Возвращает:**

```text
Report templates (4):
- default (builtin, Jinja2): Weekly report grouped by issue with stable sections
- team_report (builtin, Jinja2): Team report: per-user sections with issue breakdown
- weekly_summary (builtin, Jinja2): Compact weekly summary: total hours, top 5 issues
- my_custom (custom, Jinja2): My custom Jinja2 template
```

> 💡 **Совет:** См. [reports.md#custom-templates](reports.md#-custom-templates) —
> как добавлять пользовательские шаблоны.

---

## 📊 `generate_tasks_report`

Сгенерировать отчёт по задачам пользователя, сгруппированный по статусу, и
сохранить его как файл. Для одного пользователя: все задачи с полными
деталями (summary, срок, приоритет, комментарии). Для нескольких
пользователей: только активные задачи (категория статуса «In Progress»),
сгруппированные сначала по пользователю, затем по статусу. С версии v0.3.0
параметр `format` выбирает формат: `md` (Markdown, по умолч.), `txt` или
`json`.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `users` | array<string> | нет | Имена пользователей Jira. Если не указаны, используется `REPORT_TEAM_USERS` или текущий пользователь. |
| `active_only` | boolean | нет | Только активные задачи. Принудительно `true` для нескольких пользователей. По умолч. `false`. |
| `output_dir` | string | нет | Директория вывода. По умолч. `REPORT_OUTPUT_DIR` или `~/.mcp/jira-tempo-mcp/reports/`. Должна быть внутри разрешённого корня. |
| `format` | string | нет | Формат вывода: `md` (Markdown, по умолч.), `txt` (текст), `json` (структурированный JSON). Расширение файла соответствует формату. |

**Пример вызова:**

```json
{
  "name": "generate_tasks_report",
  "arguments": { "users": ["golikhin"], "format": "md" }
}
```

**Возвращает:**

```text
Tasks report for 1 user(s) written to /home/user/.mcp/jira-tempo-mcp/reports/tasks_golikhin_2026-06-19.md
Reports directory: /home/user/.mcp/jira-tempo-mcp/reports
```

---

## 👁️ `preview_report_template`

Предпросмотр шаблона отчёта, отрендеренного на **тестовых данных** — запросы
к Jira/Tempo не выполняются. Полезно для изучения шаблонов перед
генерацией реального отчёта. Возвращает отрендеренный текст без записи файла.

> 🆕 **Новое в v0.4.0.** Этот инструмент не вызывает Jira или Tempo — он
> использует встроенные тестовые worklog'и, поэтому шаблон можно
> посмотреть офлайн.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `template_name` | string | да | Имя шаблона (используйте `list_report_templates` для просмотра доступных) |
| `sample_data` | string | нет | Профиль тестовых данных: `default` (реалистичная неделя, несколько задач), `minimal` (один worklog), `empty` (без worklog'ов — проверяет рендер пустого состояния). По умолч. `default`. |

**Пример вызова:**

```json
{
  "name": "preview_report_template",
  "arguments": { "template_name": "default", "sample_data": "minimal" }
}
```

**Возвращает:** отрендеренный текст шаблона:

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

Получить информацию об аутентифицированном пользователе (владельце PAT).
Возвращает имя пользователя, отображаемое имя, email, ключ и статус
активности. Полезно для проверки, под какой учётной записью работает сервер.

**Параметры:** нет.

**Пример вызова:**

```json
{
  "name": "get_current_user",
  "arguments": {}
}
```

**Возвращает:**

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

Поиск пользователей Jira по имени, фамилии, имени пользователя или фрагменту
email. Возвращает список найденных пользователей с именем, ключом,
отображаемым именем, email и статусом активности.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `query` | string | да | Поисковый запрос — имя, фамилия или фрагмент имени пользователя |
| `max_results` | integer | нет | Максимальное количество пользователей. По умолч. `10`. |

**Пример вызова:**

```json
{
  "name": "search_users",
  "arguments": { "query": "golikhin", "max_results": 5 }
}
```

**Возвращает:**

```text
Users matching 'golikhin' (1):
- golikhin (golikhin): Ivan Golikhin <i.golikhin@example.com> [active]
```

---

## 📋 `list_user_tasks`

Получить задачи, назначенные пользователю Jira. Возвращает до 100 задач,
отсортированных по последнему обновлению, — каждая со статусом, сроком,
summary, приоритетом, типом задачи, проектом и последними 2 комментариями.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `username` | string | да | Имя пользователя Jira (напр. `golikhin`) |
| `status_filter` | array<string> | нет | Опциональный список статусов для фильтрации |
| `max_results` | integer | нет | Максимальное количество задач. По умолч. `100`. |

**Пример вызова:**

```json
{
  "name": "list_user_tasks",
  "arguments": { "username": "golikhin", "status_filter": ["In Progress", "Open"] }
}
```

**Возвращает:**

```text
Tasks for golikhin (2):
- [DEVOPS-101] Refactor Helm release workflow | In Progress | priority=High | due=2026-06-20 | comments=2
    💬 tech-lead: Looks good, please add tests.
- [DEVOPS-102] Migrate Valkey chart | Open | priority=Medium | due=— | comments=0
```

---

## 🔍 `list_issues_by_jql`

Поиск задач Jira через JQL-запрос (только чтение). Возвращает
отформатированный список задач с ключом, summary, статусом, приоритетом,
сроком и исполнителем. Максимум 100 результатов.

**Параметры:**

| Имя | Тип | Обяз. | Описание |
| --- | --- | --- | --- |
| `jql` | string | да | Строка JQL-запроса (напр. `project = DEVOPS AND assignee = golikhin ORDER BY updated DESC`) |
| `fields` | string | нет | Поля через запятую. По умолч. `summary,status,priority,duedate,assignee,issuetype,project,created,updated`. |
| `max_results` | integer | нет | Максимальное количество результатов. По умолч. `50`. Ограничено `100`. |
| `include_description` | boolean | нет | Дополнительно вернуть описание каждой задачи. По умолч. `false` — чтобы списки оставались компактными. |

**Пример вызова:**

```json
{
  "name": "list_issues_by_jql",
  "arguments": {
    "jql": "project = DEVOPS AND assignee = golikhin ORDER BY updated DESC",
    "max_results": 5
  }
}
```

**Возвращает:**

```text
Issues matching JQL (2):
- [DEVOPS-101] Refactor Helm release workflow | In Progress | priority=High | due=2026-06-20 | assignee=golikhin
- [DEVOPS-102] Migrate Valkey chart | Open | priority=Medium | due=— | assignee=golikhin
```

С `include_description: true` после каждой строки идёт отступ с описанием:

```text
Issues matching JQL (1):
- [DEVOPS-101] Refactor Helm release workflow | In Progress | priority=High | due=2026-06-20 | assignee=golikhin
    Description: Split the release workflow into reusable jobs.
```

---

## ❌ Обработка ошибок

Все инструменты при сбое возвращают пользовательскую строку ошибки (не
сырой trace исключения). Частые шаблоны ошибок:

| Ошибка | Причина |
| --- | --- |
| `Invalid issue key '...'` | ключ не соответствует `^[A-Z][A-Z0-9]+-\d+$` |
| `Invalid date for ...` | дата не в ISO `YYYY-MM-DD` |
| `Could not parse duration: '...'` | в `time_spent` нет валидных токенов `w/d/h/m` |
| `Jira/Tempo API error: 401 ...` | невалидный или истёкший PAT |
| `output_dir '...' resolves outside the allowed root` | попытка path traversal |
| `Could not identify your Tempo worker key` | несоответствие `JIRA_USER` или связь с Tempo |

---

## ➡️ Дальнейшие шаги

- 📝 [reports.ru.md](reports.ru.md) — настройка еженедельного отчёта
- ⚙️ [configuration.ru.md](configuration.ru.md) — переменные окружения, влияющие на инструменты
- 🏗️ [architecture.ru.md](architecture.ru.md) — как диспетчеризуются инструменты
