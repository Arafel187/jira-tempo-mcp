# 🧩 Шаблоны задач — родительская задача + дочерние подзадачи из YAML

Шаблон задачи описывает повторяемую работу, которая разворачивается в одну
родительскую задачу Jira и упорядоченный список дочерних подзадач. Два
MCP-инструмента работают с ним: [`list_issue_templates`](api.ru.md#-list_issue_templates)
показывает доступные шаблоны, [`create_issue_from_template`](api.ru.md#-create_issue_from_template)
создаёт дерево задач по одному из них.

Встроенные шаблоны поставляются вместе с пакетом (сейчас `standup-preparation`,
15 дочерних задач); пользовательские шаблоны расширяют или заменяют их.

---

## 📄 Формат файла шаблона

Шаблоны — YAML-файлы. Ниже показаны все поддерживаемые поля:

```yaml
name: standup-preparation        # слаг, уникальный в реестре: ^[a-z0-9][a-z0-9_-]*$
title: "{{ summary }}"           # summary родителя, рендерится через jinja2
description: >-                  # описание родителя, рендерится через jinja2;
  Подготовка стенда к стендапу.{%- if user_description %} Контекст:  # пустое -> дублирует отрендеренный title
  {{ user_description }}.{% endif %}
project_key: null                # ключ проекта по умолчанию; переопределяется при вызове
parent_issuetype: Task           # тип родительской задачи (по умолчанию Task)
child_issuetype: Sub-task        # тип дочерних задач (по умолчанию Sub-task)
tasks:                           # упорядоченные дочерние задачи (минимум одна)
  - tag: "[terraform]"           # необязательный префикс перед summary
    summary: "Подготовить IaC-манифесты для нового стенда"  # рендерится через jinja2
    description: "Создать и проверить Terraform-манифесты для ландшафта «{{ summary }}»."
  - summary: "Прогнать smoke-тесты на стенде"  # без description -> дублирует summary
```

**Правила валидации** (pydantic, проверяются при загрузке):

| Поле | Правило |
| --- | --- |
| `name` | Обязательно, соответствует `^[a-z0-9][a-z0-9_-]*$`; уникален в реестре |
| `title` | Обязательно, непустое |
| `tasks` | Обязательно, минимум одна дочерняя задача; у каждой непустой `summary` |
| `tag` | Необязательно, одна строка (без переносов) |
| `project_key` | Необязательно; если задан — заглавные буквы и цифры (ключ проекта Jira) |
| `parent_issuetype` / `child_issuetype` | Необязательно; по умолчанию `Task` / `Sub-task` |

---

## 🧩 Контекст рендеринга Jinja2

Описания и заголовки рендерятся через песочницу Jinja2 (та же защита, что у
шаблонов отчётов — обращение к dunder/глобалам заблокировано). Доступные
переменные:

| Переменная | Тип | Значение |
| --- | --- | --- |
| `summary` | string | Описание задачи от вызывающего (аргумент `summary`) |
| `user_description` | string | Необязательный дополнительный контекст (аргумент `description`); пустая строка, если не задан |
| `project_key` | string | Ключ целевого проекта |
| `today` | string | Дата создания, ISO `YYYY-MM-DD` |

Запасные варианты: дочерняя задача без `description` дублирует свой
отрендеренный summary; родитель без `description` дублирует отрендеренный
title.

Ошибки рендеринга (неопределённая переменная с неизвестным фильтром, попытка
выхода из песочницы) вызывают `TemplateRenderError` с именем шаблона и
полем, на котором произошёл сбой.

---

## 📁 Пользовательские переопределения — `JTM_TEMPLATES_DIR`

Задайте переменную окружения `JTM_TEMPLATES_DIR` — каталог, сканируемый
на `*.yaml`-шаблоны задач:

- Пользовательский файл, чей `name` совпадает с именем встроенного шаблона,
  **заменяет** встроенный.
- Остальные пользовательские файлы добавляются в реестр.
- Файлы, начинающиеся с `_`, и не-`.yaml` файлы игнорируются.
- Сломанный пользовательский файл пропускается с предупреждением в лог —
  он никогда не кладёт сервер.

```bash
# Заменить встроенный standup-preparation более лёгкой версией
JTM_TEMPLATES_DIR=~/.mcp/jira-tempo-mcp/task-templates
```

Без переменной (или с пустым/несуществующим каталогом) сервер отдаёт только
встроенные шаблоны.

---

## ✏️ Пример

1. Создайте `~/.mcp/jira-tempo-mcp/task-templates/deploy-checklist.yaml`:

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

2. Укажите серверу каталог и вызовите:

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

3. Результат: родительская `Task DEVOPS-200` («Deploy release 1.4 to
staging», отрендеренное описание) плюс три последовательные `Sub-task`
дочерние задачи, связанные с ней, в порядке из шаблона.

---

## 🔗 Связанное

- [Справочник API — `create_issue_from_template`](api.ru.md#-create_issue_from_template)
- [Справочник API — `list_issue_templates`](api.ru.md#-list_issue_templates)
- [Пользовательские шаблоны отчётов](templates.ru.md) (отдельная система для отчётов)