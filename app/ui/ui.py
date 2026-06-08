import streamlit as st
import requests
import time
import os

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")

CATEGORY_LABELS = {
    "educational": "📚 Образование",
    "entertainment": "🎭 Развлечение",
    "news": "📰 Новости",
    "music": "🎵 Музыка",
    "gaming": "🎮 Игры",
    "random": "🎲 Разное",
    "unknown": "❓ Неизвестно",
}

st.set_page_config(
    page_title="VideoFlow | AI Podcast Creator",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .stButton>button {
        border-radius: 8px;
        transition: all 0.3s ease-in-out;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .category-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        margin-right: 8px;
        margin-bottom: 16px;
    }
    .reject-card {
        padding: 24px;
        border-radius: 12px;
        background-color: rgba(220, 38, 38, 0.1);
        border: 1px solid #dc2626;
        color: var(--text-color);
    }
    .rec-card {
        padding: 14px 18px;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(99,102,241,0.12), rgba(139,92,246,0.08));
        border: 1px solid rgba(99,102,241,0.25);
        margin-bottom: 10px;
        transition: all 0.3s ease;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
    }
    .rec-card:hover {
        transform: translateY(-3px);
        border-color: #8b5cf6;
        box-shadow: 0 6px 20px rgba(99,102,241,0.25);
        background: linear-gradient(135deg, rgba(99,102,241,0.18), rgba(139,92,246,0.14));
    }
    .rec-card a {
        color: var(--text-color) !important;
        text-decoration: none;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 0.95rem;
    }
    .rec-card a:hover {
        color: #a78bfa !important;
    }
    </style>
""", unsafe_allow_html=True)

if 'page' not in st.session_state:
    st.session_state.page = "Generate"
if 'last_result' not in st.session_state:
    st.session_state.last_result = None
if 'selected_library_video' not in st.session_state:
    st.session_state.selected_library_video = None


# ─── API helpers ─────────────────────────────────────────────────────────────

def get_all_videos():
    try:
        r = requests.get(f"{API_URL}/videos", timeout=10)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []

def get_video_details(video_id):
    try:
        r = requests.get(f"{API_URL}/videos/{video_id}", timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def delete_video(video_id):
    try:
        r = requests.delete(f"{API_URL}/videos/{video_id}", timeout=10)
        return r.status_code == 200
    except Exception:
        return False

def get_recommendations(video_id):
    try:
        r = requests.post(f"{API_URL}/videos/{video_id}/recommend", timeout=120)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"Recommendations error: {e}")
        return None

def ask_question(video_id, question):
    try:
        r = requests.post(f"{API_URL}/videos/{video_id}/qa", json={"question": question}, timeout=120)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        print(f"QA error: {e}")
        return None

def check_audio_exists(video_id):
    try:
        with requests.get(f"{API_URL}/videos/{video_id}/audio", stream=True, timeout=5) as r:
            return r.status_code == 200
    except Exception:
        return False


# ─── Reusable UI components ──────────────────────────────────────────────────

def render_recommendations(rec_data):
    """Render courses and books from a recommendation dict."""
    courses = rec_data.get("courses", [])
    books = rec_data.get("books", [])

    if rec_data.get("from_cache"):
        st.caption("💾 Загружено из кэша")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 🎓 Онлайн-курсы")
        if courses:
            for c in courses:
                title = c.get("title", c.get("url", "Ссылка"))
                url = c.get("url", "#")
                st.markdown(
                    f'<div class="rec-card"><a href="{url}" target="_blank">📌 {title}</a></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Курсы не найдены")

    with col2:
        st.markdown("#### 📚 Книги")
        if books:
            for b in books:
                title = b.get("title", b.get("url", "Ссылка"))
                url = b.get("url", "#")
                st.markdown(
                    f'<div class="rec-card"><a href="{url}" target="_blank">📖 {title}</a></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Книги не найдены")

def render_video_details(video_id, data, context="gen"):
    """Render the standard tabbed interface for a video's details."""
    cat = data.get("video_category") or data.get("category", "unknown")
    cat_label = CATEGORY_LABELS.get(cat, cat)
    
    st.markdown(
        f'<span class="category-badge">{cat_label}</span>',
        unsafe_allow_html=True,
    )
    
    t1, t2, t3, t4, t5 = st.tabs(
        ["📝 Конспект", "🎬 Скрипт", "🎙️ Аудио", "🎯 Рекомендации", "💬 Спросить"]
    )

    with t1:
        st.markdown(data.get("summary", "Конспект отсутствует."))
        kw = data.get("keywords", [])
        if kw:
            st.write("---")
            st.write("**Ключевые слова:**")
            st.write(", ".join(kw))

    with t2:
        st.text_area(
            "Сценарий диалога",
            data.get("podcast_script", ""),
            height=400,
            key=f"{context}_script_{video_id}",
        )
        if "cache_hit" in data:
            st.caption(f"Кэш: {'Использован' if data.get('cache_hit') else 'Создан заново'}")

    with t3:
        @st.fragment
        def audio_fragment():
            st.subheader("🎙️ Аудио подкаст")
            audio_status_key = f"{context}_audio_ready_{video_id}"
            audio_generating_key = f"{context}_audio_gen_{video_id}"

            # Cache audio existence in session state to avoid repeated network calls
            if audio_status_key not in st.session_state:
                st.session_state[audio_status_key] = check_audio_exists(video_id)

            box = st.container(height=300, border=True)
            with box:
                if st.session_state[audio_status_key]:
                    st.audio(f"{API_URL}/videos/{video_id}/audio")
                    st.success("✅ Аудио готово к прослушиванию.")
                elif st.session_state.get(audio_generating_key):
                    # Generating — show ONLY spinner (no button)
                    with st.spinner("🎙️ Генерирую аудио... Это может занять пару минут."):
                        try:
                            r = requests.post(f"{API_URL}/videos/{video_id}/audio", timeout=300)
                            if r.status_code == 200:
                                st.session_state[audio_status_key] = True
                                st.session_state.pop(audio_generating_key, None)
                                st.rerun()  # reruns only this fragment
                            else:
                                st.session_state.pop(audio_generating_key, None)
                                st.error(r.text)
                        except Exception as e:
                            st.session_state.pop(audio_generating_key, None)
                            st.error(f"Ошибка при генерации аудио: {e}")
                else:
                    # Idle — show ONLY button (no spinner)
                    st.info("🎙️ Аудио ещё не сгенерировано.")
                    if st.button("Создать аудио", key=f"{context}_gen_audio_{video_id}"):
                        st.session_state[audio_generating_key] = True
                        st.rerun()  # reruns only this fragment

        audio_fragment()

    with t4:
        @st.fragment
        def recommendations_fragment():
            st.subheader("🎯 Рекомендации по теме")
            rec_cache_key = f"{context}_rec_{video_id}"
            rec_loading_key = f"{context}_rec_loading_{video_id}"

            if context == "gen" and data.get("recommendation"):
                if rec_cache_key not in st.session_state:
                    st.session_state[rec_cache_key] = data["recommendation"]

            if rec_cache_key not in st.session_state:
                st.session_state[rec_cache_key] = None

            cached_rec = st.session_state[rec_cache_key]

            box = st.container(height=400, border=True)
            with box:
                if cached_rec and (cached_rec.get("courses") or cached_rec.get("books")):
                    render_recommendations(cached_rec)
                elif st.session_state.get(rec_loading_key):
                    # Loading — show ONLY spinner (no button)
                    with st.spinner("🔍 Ищем релевантные курсы и книги..."):
                        rec_result = get_recommendations(video_id)
                    st.session_state.pop(rec_loading_key, None)
                    if rec_result and (rec_result.get("courses") or rec_result.get("books")):
                        st.session_state[rec_cache_key] = rec_result
                        st.rerun()  # reruns only this fragment
                    else:
                        st.session_state[rec_cache_key] = None
                        st.error("Не удалось получить рекомендации. Попробуйте позже.")
                else:
                    # Idle — show ONLY button (no spinner)
                    if context == "gen" and not data.get("recommendation"):
                        st.info("Рекомендации ещё не сгенерированы для этого видео.")
                    if st.button("🔍 Загрузить рекомендации", key=f"btn_rec_{context}_{video_id}", use_container_width=True):
                        st.session_state[rec_loading_key] = True
                        st.rerun()  # reruns only this fragment

        recommendations_fragment()

    with t5:
        st.subheader("💬 Задать вопрос по видео")

        chat_history_key = f"{context}_chat_{video_id}"
        processing_key = f"{context}_chat_processing_{video_id}"
        if chat_history_key not in st.session_state:
            st.session_state[chat_history_key] = []

        # --- Handle pending question (process BEFORE rendering) ---
        if st.session_state.get(processing_key):
            question = st.session_state.pop(processing_key)
            st.session_state[chat_history_key].append({"role": "user", "content": question})
            with st.spinner("🔍 Ищу ответ..."):
                ans = ask_question(video_id, question)
            if ans:
                st.session_state[chat_history_key].append({
                    "role": "assistant",
                    "content": ans["answer"],
                    "sources": ans.get("sources", []),
                })
            else:
                st.session_state[chat_history_key].append({
                    "role": "assistant",
                    "content": "❌ Не удалось получить ответ. Попробуйте ещё раз.",
                })

        # --- Render chat history ---
        chat_container = st.container(height=400, border=True)
        if st.session_state[chat_history_key]:
            for msg in st.session_state[chat_history_key]:
                with chat_container.chat_message(msg["role"]):
                    st.write(msg["content"])
                    if msg.get("sources"):
                        with st.expander("Источники"):
                            for s in msg["sources"]:
                                st.write(f"- [{s['timestamp']}]({s['url']})")
        else:
            with chat_container:
                st.info("Задайте вопрос, и ИИ ответит на основе транскрипта видео.")

        # --- Input form (no st.chat_input — it resets tabs on rerun) ---
        with st.form(key=f"{context}_chat_form_{video_id}", clear_on_submit=True):
            cols = st.columns([5, 1])
            with cols[0]:
                user_input = st.text_input(
                    "Вопрос", placeholder="Спросите что-нибудь по видео...",
                    label_visibility="collapsed",
                )
            with cols[1]:
                submitted = st.form_submit_button("📤", use_container_width=True)
            if submitted and user_input.strip():
                st.session_state[processing_key] = user_input.strip()
                st.rerun()


# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3064/3064197.png", width=80)
    st.title("VideoFlow")
    st.caption("AI-Powered Podcast Factory")
    st.divider()

    pages = ["Generate", "Library", "Settings"]
    page_labels = ["✨ Генерировать", "📚 Библиотека", "⚙️ Настройки"]
    
    for page, label in zip(pages, page_labels):
        is_active = st.session_state.page == page
        if st.button(label, use_container_width=True, type="primary" if is_active else "secondary", key=f"nav_{page}"):
            st.session_state.page = page
            st.rerun()

    st.divider()
    try:
        requests.get(f"{API_URL}/health", timeout=2)
        st.success("🟢 API: Online")
    except Exception:
        st.error("🔴 API: Offline")


# ═══════════════════════════════════════════════════════════════════
#  PAGE: Generate
# ═══════════════════════════════════════════════════════════════════
if st.session_state.page == "Generate":
    st.title("✨ Создать новый подкаст")
    st.write("Вставьте ссылку на YouTube видео, и наш ИИ превратит его в увлекательный подкаст.")

    col1, col2 = st.columns([3, 1])
    with col1:
        url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...", label_visibility="collapsed")
    with col2:
        start_btn = st.button("🚀 Начать магию", disabled=not url, use_container_width=True, type="primary", key="start_magic_btn")

    if start_btn:
        st.session_state.last_result = None

        with st.status("🔮 Работаем над вашим видео...", expanded=True) as status:
            st.write("🔍 Извлекаем транскрипт и классифицируем видео...")

            try:
                response = requests.post(
                    f"{API_URL}/generate",
                    json={"video_url": url, "skip_audio": True},
                    timeout=300,
                )

                if response.status_code == 200:
                    data = response.json()
                    st.session_state.last_result = data
                    status.update(
                        label="✅ Готово!",
                        state="complete",
                        expanded=False,
                    )
                else:
                    status.update(label="❌ Ошибка API", state="error", expanded=False)
                    st.error(f"Ошибка API: {response.status_code} — {response.text}")
            except Exception as e:
                status.update(label="❌ Ошибка", state="error", expanded=False)
                st.error(f"Произошла ошибка: {str(e)}")

    data = st.session_state.last_result
    if data:
        if data.get("rejected"):
            cat = data.get("video_category", "unknown")
            cat_label = CATEGORY_LABELS.get(cat, cat)
            st.markdown(
                f'<div class="reject-card">'
                f"<h3>🚫 Видео не подходит для обработки</h3>"
                f"<p><b>Категория:</b> {cat_label}</p>"
                f"<p><b>Причина:</b> {data.get('classification_reason', '—')}</p>"
                f"<p>Пожалуйста, выберите образовательное видео "
                f"(лекция, туториал, курс).</p>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            render_video_details(data.get("video_id"), data, context="gen")


# ═══════════════════════════════════════════════════════════════════
#  PAGE: Library
# ═══════════════════════════════════════════════════════════════════
elif st.session_state.page == "Library":

    sel_id = st.session_state.selected_library_video

    # ── Detail view (replaces the list entirely) ──
    if sel_id:
        if st.button("← Назад к библиотеке", type="secondary", key=f"back_btn_{sel_id}"):
            st.session_state.selected_library_video = None
            st.rerun()

        details = get_video_details(sel_id)
        if details:
            st.image(
                f"https://img.youtube.com/vi/{sel_id}/hqdefault.jpg",
                width=480,
            )
            render_video_details(sel_id, details, context="lib")
        else:
            st.warning("Видео не найдено в кэше.")
            st.session_state.selected_library_video = None

    # ── List view ──
    else:
        st.title("📚 Ваша Библиотека")
        videos = get_all_videos()

        if not videos:
            st.info("В библиотеке пока пусто. Сгенерируйте свой первый подкаст!")
        else:
            for v in videos:
                video_id = v["video_id"]

                with st.container(border=True):
                    cols = st.columns([1, 4, 1])

                    cols[0].image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg", use_container_width=True)

                    with cols[1]:
                        cat = v.get("category", "unknown")
                        cat_label = CATEGORY_LABELS.get(cat, cat)
                        st.markdown(f"#### [YouTube Video]({v['url']})")
                        st.caption(
                            f"**{cat_label}** • Язык: {v.get('language', 'неизвестен').upper()} • "
                            f"Длительность: {v.get('duration_sec', 0)/60:.1f} мин"
                        )

                    with cols[2]:
                        st.write("")
                        if st.button("👁️ Открыть", key=f"view_{video_id}", use_container_width=True):
                            st.session_state.selected_library_video = video_id
                            st.rerun()
                        if st.button("🗑️ Удалить", key=f"del_{video_id}", use_container_width=True, type="secondary"):
                            if delete_video(video_id):
                                st.toast(f"Видео {video_id} удалено")
                                st.rerun()


# ═══════════════════════════════════════════════════════════════════
#  PAGE: Settings
# ═══════════════════════════════════════════════════════════════════
elif st.session_state.page == "Settings":
    st.title("⚙️ Настройки")

    st.header("Управление данными")
    st.write("Очистка кэша поможет освободить место в базе данных.")

    if st.button("🧹 Удалить устаревшие видео (7+ дней)", type="primary", key="delete_expired_btn"):
        with st.spinner("Удаление..."):
            try:
                r = requests.delete(f"{API_URL}/videos/expired", timeout=10)
                if r.status_code == 200:
                    st.success(r.json().get("message", "Успешно удалено"))
                else:
                    st.error(f"Ошибка: {r.text}")
            except Exception as e:
                st.error(f"Не удалось связаться с API: {e}")

    st.divider()
    st.header("О сервисе")
    st.info("VideoFlow v1.0.0 — Инструмент для автоматизации контента. Превращайте образовательные видео в подкасты с помощью ИИ.")
