# 🎙️ VideoFlow — AI Podcast Creator

**VideoFlow** — мультиагентная система на базе LangGraph, которая превращает образовательные YouTube-видео в структурированные подкасты. Система автоматически извлекает транскрипт, классифицирует контент, генерирует конспект, сценарий диалога, аудио-подкаст, а также позволяет задавать вопросы по содержанию видео через RAG (Retrieval-Augmented Generation).

---

## 📋 Оглавление

- [Возможности](#-возможности)
- [Архитектура](#-архитектура)
- [Технологический стек](#-технологический-стек)
- [Структура проекта](#-структура-проекта)
- [Установка и запуск](#-установка-и-запуск)
  - [Локальный запуск](#локальный-запуск)
  - [Docker](#docker)
- [Переменные окружения](#-переменные-окружения)
- [API документация](#-api-документация)
- [Мультиагентный пайплайн](#-мультиагентный-пайплайн)
- [RAG система](#-rag-система-вопрос-ответ)
- [Интерфейс (UI)](#-интерфейс)

---

## ✨ Возможности

| Функция | Описание |
|---|---|
| 🎬 **Извлечение транскрипта** | Автоматическое получение субтитров YouTube-видео (RU/EN/KK) |
| 🔍 **Классификация контента** | ИИ определяет тип видео и фильтрует неподходящий контент |
| 📝 **Генерация конспекта** | Подробный структурированный конспект с таймстампами |
| 🔑 **Извлечение ключевых слов** | 10–15 основных терминов, отсортированных по важности |
| 🎙️ **Сценарий подкаста** | Диалог двух ведущих (Алекс и Марина) с проверкой критиком |
| 🔊 **Аудио генерация** | Озвучка подкаста через ElevenLabs (мультиголосовая) |
| 💬 **RAG QA** | Вопрос-ответ по видео с гибридным поиском (ChromaDB + BM25) |
| 🎯 **Рекомендации** | Поиск релевантных курсов и книг через Tavily Search |
| 💾 **Кэширование** | Все результаты сохраняются в PostgreSQL для повторного использования |

---

## 🏗️ Архитектура

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Streamlit UI  │────▶│   FastAPI (API)  │────▶│   LangGraph     │
│   (порт 8501)   │◀────│   (порт 8000)    │◀────│   (Агенты)      │
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                 │                       │
                    ┌────────────┼────────────┐          │
                    │            │            │          │
               ┌────▼───┐  ┌────▼───┐  ┌─────▼────┐ ┌──▼──────────┐
               │PostgreSQL│  │ChromaDB│  │ElevenLabs│ │ LLM (Gemini,│
               │ (Кэш)   │  │(Вектор)│  │ (Аудио)  │ │ Groq, Llama)│
               └─────────┘  └────────┘  └──────────┘ └─────────────┘
```

### Граф агентов (LangGraph)

```
START
  │
  ├──▶ extract_transcript ──┬──▶ classify ──┬──▶ cache_node ──┬──▶ start_pipeline ──┬──▶ summarize ──▶ merge
  │                         │               │                │                     │
  │                         │               │                │                     └──▶ keywords ──▶ recommend ──▶ merge
  │                         │               │                │
  │                         │               ▼                ├──▶ audio ──▶ END (если cache_hit + !skip_audio)
  │                         │             reject ──▶ END     │
  │                         │                                └──▶ END (если cache_hit + skip_audio)
  │                         │
  │                         └──▶ rag_index ──▶ END
  │
  merge ──▶ script ──▶ critic ──┬──▶ save_to_db ──┬──▶ audio ──▶ END
                                │                 │
                                └──▶ script       └──▶ END (skip_audio)
                                (повтор, макс. 2)
```

---

## 🛠️ Технологический стек

| Компонент | Технология |
|---|---|
| **Оркестрация агентов** | LangGraph (StateGraph) |
| **LLM** | Google Gemini 3.1 Flash Lite, Groq (Llama 3.3 70B) |
| **Векторная БД** | ChromaDB + HuggingFace Embeddings (`paraphrase-multilingual-MiniLM-L12-v2`) |
| **Гибридный поиск** | ChromaDB (семантический) + BM25 (лексический) + Reciprocal Rank Fusion |
| **Генерация аудио** | ElevenLabs API (`eleven_multilingual_v2`) |
| **Веб-поиск** | Tavily Search API |
| **База данных** | PostgreSQL (SQLAlchemy ORM) |
| **API** | FastAPI |
| **Интерфейс** | Streamlit |
| **Контейнеризация** | Docker + Docker Compose |

---

## 📁 Структура проекта

```
video-flow/
├── app/
│   ├── agent/
│   │   ├── agent.py              # Все ноды агентов (extract, classify, summarize, script, critic, audio, recommend и т.д.)
│   │   ├── agent_node.py         # Граф LangGraph — связи между нодами
│   │   ├── agent_state.py        # GraphState (TypedDict) + инициализация LLM
│   │   └── chat_agent/
│   │       └── rag.py            # RAG модуль: индексация, гибридный поиск, QA цепочка
│   ├── api/
│   │   └── api.py                # FastAPI — REST endpoints
│   ├── db/
│   │   ├── database.py           # SQLAlchemy модели (Video, Summary, Keyword, PodcastScript, PodcastAudio, Recommendation)
│   │   └── cache.py              # Функции кэширования (чтение/запись/удаление)
│   ├── tools/
│   │   ├── youtube_scraper.py    # Извлечение транскрипта с YouTube
│   │   ├── chunking_transcript.py # Разбивка транскрипта на чанки с таймстампами
│   │   └── audio_generator.py    # Генерация мультиголосового аудио через ElevenLabs
│   └── ui/
│       └── ui.py                 # Streamlit интерфейс
├── vector_storage/               # Хранилище ChromaDB (персистентное)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env                          # Переменные окружения (API ключи)
└── README.md
```

---

## 🚀 Установка и запуск

### Предварительные требования

- Python 3.11+
- PostgreSQL 15+
- ffmpeg (для обработки аудио)

### Локальный запуск

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/your-username/video-flow.git
cd video-flow
```

2. **Создайте виртуальное окружение:**
```bash
python -m venv venv
source venv/bin/activate  # macOS/Linux
```

3. **Установите зависимости:**
```bash
pip install -r requirements.txt
```

4. **Настройте переменные окружения:**
```bash
cp .env.example .env
# Заполните .env вашими API ключами (см. раздел ниже)
```

5. **Создайте базу данных PostgreSQL:**
```bash
createdb lecture_agent
```

6. **Запустите API сервер:**
```bash
cd app
uvicorn api.api:app --host 0.0.0.0 --port 8000 --reload
```

7. **Запустите UI (в отдельном терминале):**
```bash
streamlit run app/ui/ui.py
```

8. **Откройте в браузере:** [http://localhost:8501](http://localhost:8501)

### Docker

```bash
# Запуск всех сервисов (PostgreSQL + API + UI)
docker-compose up --build

# Остановка
docker-compose down

# Остановка с удалением данных
docker-compose down -v
```

После запуска:
- **UI:** [http://localhost:8501](http://localhost:8501)
- **API:** [http://localhost:8000](http://localhost:8000)
- **API Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 🔐 Переменные окружения

Создайте файл `.env` в корне проекта:

| Переменная | Описание | Обязательно |
|---|---|---|
| `DATABASE_URL` | URL подключения к PostgreSQL | ✅ |
| `GOOGLE_API_KEY` | API ключ Google Gemini | ✅ |
| `GROQ_API_KEY` | API ключ Groq (для Llama/Qwen) | ✅ |
| `ELEVENLABS_API_KEY` | API ключ ElevenLabs (для аудио) | ✅ |
| `TAVILY_API_KEY` | API ключ Tavily (для рекомендаций) | ✅ |
| `DB_PASSWORD` | Пароль PostgreSQL (для Docker) | 🐳 |

```env
DATABASE_URL="postgresql://postgres:your_password@localhost:5432/lecture_agent"
GOOGLE_API_KEY="your_google_api_key"
GROQ_API_KEY="your_groq_api_key"
ELEVENLABS_API_KEY="your_elevenlabs_api_key"
TAVILY_API_KEY="your_tavily_api_key"
DB_PASSWORD="your_password"
```

---

## 📡 API документация

### Основные эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/generate` | Генерация подкаста из YouTube URL |
| `GET` | `/videos` | Список всех обработанных видео |
| `GET` | `/videos/{video_id}` | Детали конкретного видео |
| `DELETE` | `/videos/{video_id}` | Удаление видео из кэша |
| `DELETE` | `/videos/expired` | Удаление видео старше 7 дней |
| `POST` | `/videos/{video_id}/qa` | Задать вопрос по видео (RAG) |
| `POST` | `/videos/{video_id}/recommend` | Получить рекомендации |
| `POST` | `/videos/{video_id}/audio` | Сгенерировать аудио |
| `GET` | `/videos/{video_id}/audio` | Скачать аудио файл |
| `GET` | `/health` | Проверка статуса API |

### Примеры запросов

**Генерация подкаста:**
```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"video_url": "https://www.youtube.com/watch?v=VIDEO_ID", "skip_audio": true}'
```

**Вопрос по видео (RAG):**
```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/qa \
  -H "Content-Type: application/json" \
  -d '{"question": "О чём это видео?"}'
```

**Получение рекомендаций:**
```bash
curl -X POST http://localhost:8000/videos/VIDEO_ID/recommend
```

---

## 🤖 Мультиагентный пайплайн

Пайплайн построен на **LangGraph StateGraph** и состоит из следующих агентов:

### 1. 🎬 Extract Transcript
Извлекает транскрипт с YouTube через `youtube-transcript-api`. Поддерживает языки: русский, английский, казахский. Параллельно парсит название видео.

### 2. 🔍 Classify
Классифицирует видео по категориям: `educational`, `entertainment`, `news`, `music`, `gaming`, `random`. Пропускает только образовательный контент (confidence ≥ 0.6).

### 3. 💾 Cache Node
Проверяет, есть ли видео в кэше PostgreSQL. Если да — возвращает результаты без повторной обработки.

### 4. 📝 Summarize
Генерирует подробный конспект с разбивкой по разделам, таймстампами, глоссарием и вопросами для самопроверки.

### 5. 🔑 Keywords
Извлекает 10–15 ключевых терминов из транскрипта.

### 6. 🎙️ Script
Создаёт сценарий диалога двух ведущих (Алекс — новичок, Марина — эксперт).

### 7. ✅ Critic
Проверяет сценарий на формат и использование ключевых слов. Может отклонить и отправить на переработку (максимум 2 попытки).

### 8. 🔊 Audio
Генерирует мультиголосовой аудио-подкаст через ElevenLabs API.

### 9. 🎯 Recommend
Ищет релевантные онлайн-курсы и книги через Tavily Search API.

### 10. 🧠 RAG Index
Параллельно индексирует транскрипт в ChromaDB для будущих вопросов.

---

## 💬 RAG система (Вопрос-Ответ)

Система использует **гибридный поиск** для точных ответов:

1. **Семантический поиск** — ChromaDB с эмбеддингами `paraphrase-multilingual-MiniLM-L12-v2`
2. **Лексический поиск** — BM25 Retriever для точного совпадения ключевых слов
3. **Reciprocal Rank Fusion** — объединение результатов обоих поисков

Каждый ответ сопровождается таймстампами и ссылками на конкретные моменты видео.

---

## 🖥️ Интерфейс

Интерфейс построен на **Streamlit** и включает три страницы:

### ✨ Генерация
- Ввод YouTube URL
- Прогресс-бар обработки
- Табы: Конспект → Скрипт → Аудио → Рекомендации → Чат

### 📚 Библиотека
- Список всех обработанных видео с превью
- При выборе видео — полноэкранный просмотр деталей с кнопкой «Назад»
- Удаление видео из кэша

### ⚙️ Настройки
- Очистка устаревших видео (7+ дней)
- Информация о сервисе

---

## 📄 Лицензия

Этот проект создан в образовательных целях.

---

## 👤 Автор
- Alisher Manetti

