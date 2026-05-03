# CLAUDE.md — Руководство по разработке Бауманка.Квиз

## Стек технологий

- **Backend**: Python 3.12 + Flask
- **БД**: PostgreSQL (через psycopg2 + SQLAlchemy ORM)
- **Real-time**: flask-socketio (WebSockets, eventlet)
- **Frontend**: Jinja2 templates + Tailwind CSS + DaisyUI + vanilla JS
- **Сборка CSS**: Tailwind CLI (через npm/npx, не PostCSS плагин)
- **Контейнеризация**: Docker + docker-compose
- **Файлы**: локально в Docker volume (`/app/uploads`)
- **Excel-экспорт**: openpyxl
- **ZIP-экспорт/импорт**: stdlib `zipfile` + `tempfile` + `shutil`
- **Markdown-рендеринг (фронт)**: marked.js (CDN, подключается только в нужных шаблонах)

## Структура проекта

```
bmstu_quiz/
├── app/
│   ├── __init__.py          # create_app(), socketio инициализация
│   ├── models.py            # SQLAlchemy модели
│   ├── auth.py              # авторизация (login/logout/decorators)
│   ├── admin/               # Blueprint: конструктор, управление квизом
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── templates/admin/
│   ├── judge/               # Blueprint: проверка ответов
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── templates/judge/
│   ├── participant/         # Blueprint: экран участника
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── templates/participant/
│   ├── presentation/        # Blueprint: экран презентации
│   │   ├── __init__.py
│   │   ├── routes.py
│   │   └── templates/presentation/
│   ├── sockets/             # SocketIO event handlers
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── judge.py
│   │   ├── participant.py
│   │   └── presentation.py
│   ├── static/
│   │   ├── css/             # собранный tailwind output.css
│   │   ├── js/              # общий JS, socket-client.js
│   │   └── uploads/         # медиафайлы (volume mount)
│   └── templates/
│       ├── base.html
│       └── auth/
├── migrations/              # SQL-миграции (plain .sql файлы)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── tailwind.config.js
├── package.json             # только для tailwind cli
└── .env.example
```

## Соглашения по коду

### Python / Flask
- Application Factory pattern: `create_app()` в `app/__init__.py`
- Blueprints для каждой роли: `admin`, `judge`, `participant`, `presentation`
- SocketIO namespace для каждой роли: `/admin`, `/judge`, `/participant`, `/presentation`
- Простые функции вместо классов там, где классы не нужны
- Не добавлять docstrings и type annotations к коду, который не трогаем
- Конфиг через переменные окружения (`.env` + `python-dotenv`)
- Нет автотестов — не создавать тестовые файлы

### БД
- SQLAlchemy ORM для всех запросов
- Миграции — plain SQL файлы в `migrations/`, применяются вручную или при старте контейнера
- Именование таблиц: snake_case множественное число (`quiz_questions`, `team_answers`)
- UUID как primary key везде (uuid4)

### Frontend
- Jinja2 шаблоны, base.html с блоками `head`, `content`, `scripts`
- Tailwind + DaisyUI — использовать готовые компоненты DaisyUI максимально
- Vanilla JS, никаких фреймворков (React, Vue — не использовать)
- Socket.IO client подключается глобально через `base.html`, конкретные handlers в page-specific `<script>` блоках
- Alpine.js допустим для реактивности небольших компонентов (dropdown, модалки)
- Drag & drop: нативный HTML5 DnD API. В конструкторе квиза — перетаскивание туров и вопросов (event delegation через `initDnD()` на `#tours-list`); для сопоставления — отдельная логика

### Именование
- Роуты: kebab-case (`/admin/quiz-builder`, `/participant/answer`)
- Python функции/переменные: snake_case
- JS переменные/функции: camelCase
- CSS классы: только Tailwind утилиты + DaisyUI классы, никаких кастомных CSS классов без крайней нужды

## Ключевые архитектурные решения

### WebSockets
- Каждый клиент при подключении присоединяется к room по `quiz_id`
- Дополнительно: участник — в room `team_{team_id}`, судья — в room `judges`
- Все state-изменения (смена экрана, запуск таймера, окончание времени) — только через SocketIO events, не через polling
- Таймер считается на **сервере**, клиенты получают `timer_tick` каждую секунду

### Сессии участников
- Участник идентифицируется по `session['team_id']` (Flask session, cookie)
- При повторном заходе по QR — сессия восстанавливается, участник видит текущее состояние игры
- После завершения регистрации (`registration_closed`) участник не может менять имя команды

### Один активный квиз
- В БД есть поле `is_active` у квиза, только один может быть активным
- Все SocketIO rooms привязаны к активному квизу

### Типы вопросов (`question_type`)
- `text` — только текст
- `formatted_text` — форматированный markdown-текст с поддержкой колонок; хранится в поле `text`; рендерится через marked.js (CDN) на презентации и у участников; разделитель колонок: `---col---`; иконка `format_color_text`
- `text_image` — текст + картинка; на презентации картинка растянута на всю ширину (до 55vh)
- `image_only` — только картинка, полноэкранный режим с чёрным фоном, текст и варианты скрыты
- `audio` — текст + большая иконка ноты на презентации; новый флоу: сначала играет аудиотрек (через кнопку «Воспроизвести → Таймер» в панели управления), затем стартует отсчёт; при показе ответа трек автоматически воспроизводится на презентации и у участников

На экране ответа (`question_answer`): для `image_only` и `text_image` показывается миниатюра картинки над правильным ответом. Текст вопроса скрывается если пустой (`:empty { display: none }`).

### Аудио-вопросы: дополнительные поля
- `audio_original_name` — оригинальное имя файла при загрузке (показывается в редакторе вместо UUID)
- `audio_trim_start` — начало воспроизведения (секунды, float, default 0)
- `audio_trim_end` — конец воспроизведения (секунды, float, null = до конца)
- Обрезка настраивается ползунками в редакторе конструктора; учитывается во всех местах воспроизведения (панель управления, презентация, участник)

### Реупорядочивание в конструкторе
- API уже есть: `POST /admin/tours/<id>/reorder` и `POST /admin/questions/<id>/reorder`
- Оба принимают массив `[{id, order}, ...]` и обновляют `order` у каждого элемента
- Фронтенд: единый `initDnD()` с event delegation, различает тур- и вопрос-дроп по `closest('.question-item')` / `closest('.tour-card')`
- Перетаскивание вопросов только внутри одного тура (кросс-тур не поддерживается)
- Туры можно сворачивать/разворачивать кнопкой `expand_less`/`expand_more`; состояние сохраняется в `localStorage` по ключу `tourCollapsed`

### Файлы
- Загрузка через `werkzeug.utils.secure_filename`
- Хранение: `/app/static/uploads/{quiz_id}/{type}/{filename}`
- Типы: `images`, `audio`
- Максимальный размер: настраивается через `MAX_CONTENT_LENGTH`

### Проверка ответов
- Авто-проверка: только для типа "выбор одного варианта" и "выбор нескольких вариантов"
- Ручная проверка: текстовые поля и сопоставление — всегда ручная
- Судьи видят ВСЕ ответы (включая авто-проверенные) — могут переопределить
- Режим Tinder: каждому судье выдаётся следующий непроверенный ответ из очереди (pessimistic locking через `checking_by` поле)
- Режим таблицы: все ответы на вопрос в сетке

### Баллы
- По умолчанию 1 балл за верный ответ, 0 за неверный
- Судья может выставить любой целый балл вручную
- Кол-во баллов за вопрос настраивается в конструкторе

### Экспорт / импорт квиза
- **JSON** (`GET /admin/quizzes/<id>/export-json`, `POST /admin/quizzes/import-json`) — только структура без медиафайлов
- **ZIP** (`GET /admin/quizzes/<id>/export-zip`, `POST /admin/quizzes/import-zip`) — полный архив: `quiz.json` + `media/images/` + `media/audio/`; внешние URL-картинки в ZIP не включаются
- Интерфейс: страница квизов, кнопка «Импорт» (модал с табами ZIP / JSON), кнопка «ZIP» на карточке каждого квиза

## Docker окружение

```yaml
services:
  web:    # Flask + gunicorn + eventlet
  db:     # PostgreSQL 15
  nginx:  # reverse proxy (опционально для продакшена)
```

- Volumes: `postgres_data`, `uploads_data`
- `.env` файл для секретов: `SECRET_KEY`, `DATABASE_URL`, `ADMIN_PASSWORD`
- `docker-compose up --build` — единственная команда для запуска

## Что не делаем

- Никаких микросервисов — монолит
- Никаких REST API (кроме минимального для AJAX там, где нужно)
- Никаких автотестов
- Никаких фреймворков на фронтенде кроме Alpine.js при необходимости
- Никаких внешних хранилищ
- Никакой горизонтальной масштабируемости
