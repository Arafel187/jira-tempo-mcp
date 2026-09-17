# jira-tempo-mcp

![banner](docs/assets/banner.svg)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](#лицензия)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-blue.svg)](https://github.com/Korrnals/jira-tempo-mcp/pkgs/container/jira-tempo-mcp)

MCP-сервер для **самохостинг-инстанса Jira (Server / Data Center) + Tempo Timesheets 4**.
Учитывайте время, просматривайте worklog'и и создавайте еженедельные отчёты —
всё из вашего AI-агента (Copilot, Claude и др.) через Model Context Protocol.

> 📖 **English version:** [README.md](README.md)

## 📚 Документация

| Документ | Описание |
|----------|---------|
| [API-справочник](docs/api.ru.md) | Полное описание MCP-инструментов с параметрами и примерами |
| [Установка](docs/installation.ru.md) | Установка и настройка |
| [Конфигурация](docs/configuration.ru.md) | Переменные окружения |
| [Отчёты](docs/reports.ru.md) | Форматы отчётов (txt, md, json) и шаблоны |
| [Шаблоны](docs/templates.ru.md) | Справочник по своим шаблонам отчётов (Jinja2 + Python) |
| [Шаблоны задач](docs/task-templates.ru.md) | Справочник по шаблонам задач (родительская задача + дочерние из YAML) |
| [Архитектура](docs/architecture.ru.md) | Архитектура проекта и проектные решения |
| [CLI](docs/cli.ru.md) | Командная строка |
| [Решение проблем](docs/troubleshooting.ru.md) | Частые проблемы и решения |
| [MCP-интеграция](docs/mcp-integration.ru.md) | Интеграция с MCP-клиентами (VS Code и др.) |
| [Развёртывание](docs/deployment.ru.md) | Docker и варианты развёртывания |

---

## 📋 Возможности

| Инструмент | Что делает |
| --- | --- |
| `list_worklogs` | Список worklog'ов Tempo за период или один день |
| `get_worklog` | Получить один worklog по Tempo ID |
| `create_worklog` | Учесть время на задаче Jira с комментарием |
| `delete_worklog` | Удалить worklog (отмена неправильно учтённого времени) |
| `get_issue` | Получить метаданные задачи Jira (summary, статус, проект) |
| `create_issue` | Создать новую задачу Jira (в том числе подзадачу через ключ родителя) |
| `add_issue_comment` | Добавить комментарий к существующей задаче Jira |
| `list_issue_templates` | Показать доступные шаблоны задач (встроенные + пользовательские) |
| `create_issue_from_template` | Создать родительскую задачу и упорядоченные дочерние подзадачи из шаблона задач |
| `list_favorite_issues` | Список избранных задач текущего пользователя |
| `search_users` | Поиск пользователей Jira по имени, фамилии или username |
| `list_user_tasks` | Задачи пользователя со статусом, приоритетом, комментариями |
| `generate_weekly_report` | Сгенерировать еженедельный отчёт (txt/md/json) из worklog'ов Tempo |
| `generate_team_report` | Сгенерировать командный отчёт (txt/md/json) для нескольких пользователей |
| `generate_tasks_report` | Сгенерировать отчёт по задачам (md/txt/json) с группировкой по статусам |
| `list_issues_by_jql` | Поиск задач Jira по JQL-запросу (только чтение, до 100) |
| `get_current_user` | Информация об аутентифицированном пользователе (владельце PAT) |
| `preview_report_template` | Предпросмотр шаблона отчёта на образцовых данных |
| `list_report_templates` | Показать доступные шаблоны отчётов (встроенные + пользовательские) |

Начиная с v0.2.0 сервер поддерживает **командные отчёты** (агрегация по
пользователям с rate-limiting) и **пользовательские шаблоны отчётов** (Jinja2-песочница
+ opt-in Python). Начиная с v0.3.0 все генераторы отчётов поддерживают **три
формата вывода**: `txt` (plain text), `md` (Markdown с таблицами и эмодзи) и
`json` (структурированный JSON). Подробнее — в [docs/reports.ru.md](docs/reports.ru.md).

Полный справочник инструментов с параметрами и примерами — в [docs/api.ru.md](docs/api.ru.md).

---

## 🚀 Быстрый старт

Запуск меньше чем за минуту:

**Установка одной командой:**

```bash
curl -fsSL https://raw.githubusercontent.com/Korrnals/jira-tempo-mcp/main/scripts/install.sh | bash
```

Скрипт скачивает и запускает интерактивный установщик, который:

- ✅ Проверяет Python 3.11+ и pip
- ✅ Клонирует репозиторий и создаёт venv
- ✅ Устанавливает пакет
- ✅ Проводит через настройку учётных данных Jira
- ✅ Регистрирует MCP-сервер в VS Code (user + workspace)
- ✅ По умолчанию устанавливает standalone-агент **JTM: Jira Tempo Reports** для Copilot Chat (пропустить через `--no-agent`) — см. [§Агент JTM](#-агент-jtm-standalone-агент-для-copilot-chat)

> 💡 **Совет:** Установщик не требует `sudo` — всё ставится в user space.
> Скрипт идемпотентен: повторный запуск обновляет без затирания существующего конфига.

**Удаление:**

```bash
# Полное удаление (MCP-сервер + агент Copilot Chat + skill):
curl -fsSL https://raw.githubusercontent.com/Korrnals/jira-tempo-mcp/main/scripts/install.sh | bash -- --uninstall
# …или из локального клона:
python install.py uninstall

# Удалить ТОЛЬКО агент Copilot Chat (MCP-сервер остаётся):
python install.py --uninstall-agent
```

Полное удаление убирает запись в VS Code `mcp.json`, агента + skill + knowledge-документ Copilot Chat, а также (по запросу) учётные данные Jira из `.env.local` и pip-пакет. Удаление только агента оставляет MCP-сервер полностью рабочим — используйте его, если установили агента, но решили, что он не нужен.

**Docker:**

```bash
# Опция A — docker run с .env-файлом (chmod 600, добавлен в .gitignore):
cp .env.example .env  # впишите JIRA_BASE_URL, JIRA_USER, JIRA_PAT
docker run -i --rm --env-file .env ghcr.io/korrnals/jira-tempo-mcp:0.4.0

# Опция B — docker compose (использует docker-compose.yml в корне репо):
docker compose up -d
docker compose logs -f jira-tempo-mcp
# управлять сервером через stdio:
docker compose run --rm -T jira-tempo-mcp
```

Образ публикуется в ghcr для каждого релиза: `ghcr.io/korrnals/jira-tempo-mcp:<version>` и `:latest`. Пиньте к тегу версии (например `:0.4.0`) для воспроизводимости; `:latest` отслеживает новейший релиз.

> ⚠️ **Внимание:** URL установочного скрипта заработает, когда репозиторий
> станет публичным. До этого — клонируйте вручную и запустите `python install.py`.

---

<details>
<summary><b>🔧 Из исходников (разработка)</b></summary>

Интерактивный установщик создаёт venv, записывает `.env`, регистрирует
MCP-сервер в VS Code и опционально проверяет связь с Jira:

```bash
cd jira-tempo-mcp
python install.py
```

Или установка из исходников:

```bash
git clone https://github.com/Korrnals/jira-tempo-mcp.git
cd jira-tempo-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
jira-tempo-mcp serve
```

Или запуск через Docker:

```bash
docker run -i --rm \
  --env-file .env \
  ghcr.io/korrnals/jira-tempo-mcp:latest
```

Все способы установки: [docs/installation.ru.md](docs/installation.ru.md).

</details>

---

## ⚙️ Настройка

Вся конфигурация — через переменные окружения. Обязательные:

| Переменная | Описание |
| --- | --- |
| `JIRA_BASE_URL` | Базовый URL Jira без слэша на конце |
| `JIRA_USER` | Имя пользователя Jira (логин) |
| `JIRA_PAT` | Personal Access Token — **никогда не коммитьте** |

Опциональные: `JIRA_TIMEZONE`, `TEMPO_API_TOKEN`, `LOG_LEVEL`,
`JIRA_HTTP_TIMEOUT` и переменные отчёта (`REPORT_*`).

Полный справочник: [docs/configuration.ru.md](docs/configuration.ru.md).

---

## 🔌 MCP-интеграция

Сервер работает через **stdio** и регистрируется в VS Code `mcp.json`:

```json
{
  "servers": {
    "jira-tempo": {
      "command": "${workspaceFolder}/.venv/bin/python",
      "args": ["-m", "jira_tempo_mcp.server"],
      "envFile": "/home/your-username/.config/Code/User/.env.local",
      "env": {
        "JIRA_BASE_URL": "https://jira.example.com",
        "JIRA_USER": "your-username",
        "PYTHONPATH": "${workspaceFolder}/src"
      }
    }
  }
}
```

> 💡 **Совет:** Всегда используйте **абсолютные пути** для `envFile` — `~` не
> работает в sandbox-окружениях (distrobox, snap, контейнеры).

Полное руководство: [docs/mcp-integration.ru.md](docs/mcp-integration.ru.md).

---

<details>
<summary><b>🖥️ CLI</b></summary>

```text
jira-tempo-mcp                  # запустить MCP-сервер (по умолчанию)
jira-tempo-mcp serve            # запустить MCP-сервер
jira-tempo-mcp install          # интерактивный установщик
jira-tempo-mcp uninstall        # откатить установку
jira-tempo-mcp --version        # показать версию
```

Полный справочник: [docs/cli.ru.md](docs/cli.ru.md).

</details>

---

<details>
<summary><b>🔒 Безопасность</b></summary>

- **🔑 Токены не покидают локальный процесс** — `JIRA_PAT` отправляется только
  на инстанс Jira через HTTPS.
- **🛡️ TLS-верификация всегда включена**, **HTTP-редиректы отключены**
  (`follow_redirects=False`) — предотвращает утечку PAT через редирект.
- **👁️ Токены замаскированы в логах** — `Config.__repr__` заменяет `JIRA_PAT` на `***`.
- **✅ Валидация ввода** — ключи задач, даты и `output_dir` (защита от path
  traversal) проверяются перед любым вызовом API.
- **🐳 Docker** — многостадийная сборка, non-root пользователь, секреты никогда
  не вшиваются в образ.

Полная модель: [docs/architecture.ru.md#безопасность](docs/architecture.ru.md#-безопасность).

</details>

---

<details>
<summary><b>🛠️ Разработка</b></summary>

Канонический quality gate для этого репозитория — локальный набор `make`.
GitHub Actions в этом репозитории намеренно отключены, поэтому `make ci` —
это то, что каждое изменение должно пройти перед мержем: линтер, тайпчекер,
тесты и сборку одной командой.

```sh
make ci         # полный quality gate — lint + typecheck + test + build
make lint       # ruff
make typecheck  # mypy
make test       # pytest
make build      # python -m build (sdist + wheel)
```

</details>

---

## 🤖 Агент JTM (standalone-агент для Copilot Chat)

В этом репозитории поставляется standalone AI-агент, который предсказуемо строит отчёты по журналу работ Jira/Tempo, вызывая генераторы MCP-сервера `jira-tempo`. Знания агента IDE-agnostic, а поверх них — тонкая обёртка для VS Code Copilot Chat для генерации отчётов в один клик.

### Что куда устанавливается

`python install.py` по умолчанию устанавливает агента:
- `~/.copilot/agents/jtm-jira-tempo-reports.agent.md` — агент для VS Code Copilot Chat.
- `~/.copilot/agents/JTM_AGENT.md` — универсальный документ знаний (матрица из 7 типов отчётов, сценарии, правила), копируется рядом с агентом.
- `~/.copilot/skills/jira-tempo-reports/SKILL.md` — VS Code-специфичный skill (интерактивный picker-флоу).

В конце `install.py` выводится громкий блок-анонс, подтверждающий установку. Пропустить агента: `python install.py --no-agent`. Удалить только агента: `python install.py --uninstall-agent`.

### VS Code Copilot Chat (в один клик)

После установки откройте Copilot Chat, выберите агента **JTM: Jira Tempo Reports** и нажмите **📊 Недельный отчёт (по умолчанию)** для отчёта за неделю в один клик (basic + txt + текущая неделя + текущий пользователь). Для разрешения неоднозначностей агент использует графический пикер (`vscode_askQuestions`).

<details>
<summary><b>Другие harness-ы (Cursor, Claude Code, Continue, Aider) — нажмите для раскрытия</b></summary>

Универсальный документ знаний `JTM_AGENT.md` (в `copilot-integration/`) — IDE-agnostic. Любой агент с поддержкой MCP читает его как контекст. Типовая настройка:

| Harness | MCP-инструменты | Документ знаний | Picker UI |
|---|---|---|---|
| VS Code Copilot Chat | авто-регистрация через `install.py` | авто-установка в `~/.copilot/agents/` | `vscode_askQuestions` (графический) |
| Cursor | добавить `jira-tempo` в `.cursor/mcp.json` (та же запись сервера, что и в mcp.json для VS Code) | указать в Cursor rules на `JTM_AGENT.md` | текстовые вопросы (без GUI-пикера) |
| Claude Code | добавить `jira-tempo` в `~/.claude/mcp.json` | ссылка на `JTM_AGENT.md` в `CLAUDE.md` | текстовые вопросы |
| Continue | добавить `jira-tempo` в секцию MCP `~/.continue/config.json` | ссылка на `JTM_AGENT.md` в конфиге | текстовые вопросы |
| Aider / прочие MCP-клиенты | конфиг MCP для конкретного клиента | передать `JTM_AGENT.md` как файл контекста (`--read JTM_AGENT.md` для Aider) | текстовые вопросы |

Запись MCP-сервера для не-VS Code harness-ов (скопируйте из mcp.json для VS Code, который пишет установщик):
```json
{
  "jira-tempo": {
    "command": "/path/to/your/venv/bin/python",
    "args": ["-m", "jira_tempo_mcp.server"],
    "env": { "PYTHONPATH": "/path/to/this/repo/src" }
  }
}
```
Укажите `PYTHONPATH` на `src/` этого репозитория, чтобы пакет был импортируем. Передавайте `JIRA_BASE_URL`, `JIRA_USER`, `JIRA_PAT` через переменные окружения или env-файл согласно вашему harness-у.

</details>

### Что агент НЕ делает

- Операции записи в Jira (создание/обновление задач или журнала работ) — только чтение.
- Аналитика за пределами агрегации сырого журнала работ (тренды, прогнозирование) — вне области действия.
- Авторинг пользовательских шаблонов (написание файлов шаблонов `.py`/`.j2`) — вне области действия.

Полная матрица из 7 типов отчётов, семантика параметров и рабочие сценарии — в `JTM_AGENT.md`.

---

## 🎨 Пользовательские шаблоны

Начиная с v0.2.0 `jira-tempo-mcp` поддерживает **пользовательские шаблоны
отчётов**. Положите файл `.j2` в директорию — и он становится доступным по
имени: без изменения кода, без перезапуска (достаточно перезагрузить
конфигурацию MCP-сервера).

### Быстрый старт (3 шага)

1. **Создайте директорию шаблонов:**

   ```bash
   mkdir -p ~/.config/jira-tempo-mcp/templates/
   ```

2. **Добавьте шаблон `.j2`.** Скопируйте готовый пример из этого репозитория
   как отправную точку:

   ```bash
   cp examples/templates/standup.j2 ~/.config/jira-tempo-mcp/templates/
   ```

3. **Сгенерируйте отчёт с ним** через MCP-инструменты:

   - `list_report_templates` — показать доступные шаблоны (встроенные +
     пользовательские, с типом `Jinja2`/`Python`).
   - `generate_weekly_report(template="standup")` — сгенерировать выбранным
     шаблоном.

### Предпросмотр перед генерацией

Инструмент `preview_report_template` рендерит шаблон на встроенных
**тестовых worklog'ах** — без вызова Jira/Tempo, без создания файла. Доступны
три профиля демонстрационных данных:

| `sample_data` | Что показывает |
| --- | --- |
| `default` | Несколько реалистичных worklog'ов с разным временем (по умолчанию) |
| `minimal` | Один worklog |
| `empty` | Нет worklog'ов — проверка отрисовки пустого состояния |

```
preview_report_template(template_name="standup", sample_data="default")
```

<details>
<summary><b>Где хранятся шаблоны и детали движков</b></summary>

Директории шаблонов по ОС:

| ОС | Путь по умолчанию |
| --- | --- |
| Linux | `~/.config/jira-tempo-mcp/templates/` |
| macOS | `~/Library/Application Support/jira-tempo-mcp/templates/` |
| Windows | `%APPDATA%\jira-tempo-mcp\templates\` |

Поддерживаются два движка:

- **Jinja2** (`.j2`) — рекомендуется. Запускается в `SandboxedEnvironment`
  (безопасно: опасные конструкции вроде `{{ config.__class__ }}` блокируются).
- **Python** (`.py`) — **только по явному включению** через
  `REPORT_TEMPLATE_ALLOW_PY=1`. Выполняет произвольный код — загружайте только
  доверенные файлы.

</details>

📖 **Полный справочник для авторов** (переменные контекста, поля worklog,
фильтры Jinja2, протокол Python, модель безопасности):
[docs/templates.ru.md](docs/templates.ru.md). Примеры встроенных шаблонов и
галерея вывода — в [docs/reports.ru.md](docs/reports.ru.md#-пользовательские-шаблоны).

---

##  Лицензия

MIT
