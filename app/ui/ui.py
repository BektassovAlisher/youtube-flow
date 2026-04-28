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
    .main { background-color: #0e1117; }
    .stApp { color: #fafafa; }
    .stButton>button {
        border-radius: 8px;
        transition: all 0.3s;
        border: 1px solid #6366f1;
        background-color: transparent;
    }
    .stButton>button:hover {
        background-color: #6366f1;
        color: white;
        transform: translateY(-2px);
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
    }
    .reject-card {
        padding: 24px;
        border-radius: 12px;
        background: linear-gradient(135deg, #7f1d1d, #991b1b);
        border: 1px solid #dc2626;
        color: #fca5a5;
    }
    .rec-card {
        padding: 12px 16px;
        border-radius: 10px;
        background: linear-gradient(135deg, #1e1b4b, #312e81);
        border: 1px solid #4338ca;
        margin-bottom: 8px;
    }
    .rec-card a {
        color: #a5b4fc !important;
        text-decoration: none;
        font-weight: 500;
    }
    .rec-card a:hover {
        color: #c7d2fe !important;
        text-decoration: underline;
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
        r = requests.get(f"{API_URL}/videos")
        return r.json() if r.status_code == 200 else []
    except:
        return []

def get_video_details(video_id):
    try:
        r = requests.get(f"{API_URL}/videos/{video_id}")
        return r.json() if r.status_code == 200 else None
    except:
        return None

def delete_video(video_id):
    try:
        r = requests.delete(f"{API_URL}/videos/{video_id}")
        return r.status_code == 200
    except:
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



# ─── Reusable UI components ──────────────────────────────────────────────────

def render_recommendations(rec_data):
    """Render courses and books from a recommendation dict."""
    courses = rec_data.get("courses", [])
    books = rec_data.get("books", [])

    if rec_data.get("from_cache"):
        st.caption("💾 Загружено из кэша")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🎓 Онлайн-курсы")
        if courses:
            for c in courses:
                title = c.get("title", c.get("url", "Ссылка"))
                url = c.get("url", "#")
                st.markdown(
                    f'<div class="rec-card">📌 <a href="{url}" target="_blank">{title}</a></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Курсы не найдены")

    with col2:
        st.markdown("### 📚 Книги")
        if books:
            for b in books:
                title = b.get("title", b.get("url", "Ссылка"))
                url = b.get("url", "#")
                st.markdown(
                    f'<div class="rec-card">📖 <a href="{url}" target="_blank">{title}</a></div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("Книги не найдены")


# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3064/3064197.png", width=80)
    st.title("VideoFlow")
    st.caption("AI-Powered Podcast Factory")
    st.divider()

    if st.button("✨ Генерировать", use_container_width=True):
        st.session_state.page = "Generate"
    if st.button("📚 Библиотека", use_container_width=True):
        st.session_state.page = "Library"
    if st.button("⚙️ Настройки", use_container_width=True):
        st.session_state.page = "Settings"

    st.divider()
    try:
        requests.get(f"{API_URL}/health", timeout=1)
        st.success("API: Online")
    except:
        st.error("API: Offline")


# ═══════════════════════════════════════════════════════════════════
#  PAGE: Generate
# ═══════════════════════════════════════════════════════════════════
if st.session_state.page == "Generate":
    st.title("✨ Создать новый подкаст")
    st.write("Вставьте ссылку на YouTube видео, и наш ИИ превратит его в увлекательный подкаст.")

    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")

    if st.button("🚀 Начать магию", disabled=not url):
        # Clear previous result
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
        cat = data.get("video_category", "unknown")
        cat_label = CATEGORY_LABELS.get(cat, cat)

        if data.get("rejected"):
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
            st.markdown(
                f'<span class="category-badge">{cat_label}</span>',
                unsafe_allow_html=True,
            )

            t1, t2, t3, t4, t5 = st.tabs(
                ["📝 Конспект", "🎬 Скрипт", "🎙️ Аудио", "🎯 Рекомендации", "💬 Спросить"]
            )

            with t1:
                st.markdown(data.get("summary", ""))
                st.write("---")
                st.write("**Ключевые слова:**")
                st.write(", ".join(data.get("keywords", [])))

            with t2:
                st.text_area(
                    "Сценарий диалога",
                    data.get("podcast_script", ""),
                    height=400,
                )
                st.caption(f"Кэш: {'Использован' if data.get('cache_hit') else 'Создан заново'}")

            with t3:
                st.subheader("🎙️ Аудио подкаст")
                video_id = data.get("video_id", "")
                audio_resp = requests.get(f"{API_URL}/videos/{video_id}/audio")
                if audio_resp.status_code == 200:
                    st.audio(f"{API_URL}/videos/{video_id}/audio")
                else:
                    st.info("🎙️ Аудио ещё не сгенерировано.")
                    if st.button("Создать аудио", key=f"gen_audio_{video_id}"):
                        with st.spinner("Генерирую..."):
                            r = requests.post(f"{API_URL}/videos/{video_id}/audio", timeout=300)
                            if r.status_code == 200:
                                st.success("✅ Аудио готово!")
                                st.rerun()
                            else:
                                st.error(r.text)

            with t4:
                st.subheader("🎯 Рекомендации по теме")
                video_id = data.get("video_id", "")

                # Check recommendations from session state (updated after generation or fetch)
                rec = (st.session_state.last_result or {}).get("recommendation")
                has_recs = rec and (rec.get("courses") or rec.get("books"))

                if not has_recs:
                    st.info("Рекомендации ещё не сгенерированы для этого видео.")
                    if st.button("🔍 Сгенерировать рекомендации", key=f"btn_rec_gen_{video_id}", use_container_width=True):
                        with st.status("🔍 Генерация рекомендаций...", expanded=True) as rec_status:
                            st.write("🕵️ Анализируем контекст видео...")
                            time.sleep(0.5)
                            st.write("🌐 Ищем релевантные курсы и книги...")

                            rec_result = get_recommendations(video_id)

                            if rec_result and (rec_result.get("courses") or rec_result.get("books")):
                                st.write("✨ Готово!")
                                rec_status.update(label="✅ Рекомендации найдены!", state="complete", expanded=False)
                                # Save to session state
                                st.session_state.last_result["recommendation"] = {
                                    "courses": rec_result.get("courses", []),
                                    "books": rec_result.get("books", []),
                                }
                                # Render inline immediately
                                render_recommendations(rec_result)
                            else:
                                rec_status.update(label="❌ Ошибка", state="error", expanded=False)
                                st.error("Не удалось получить рекомендации. Попробуйте позже.")
                else:
                    render_recommendations(rec)
                    
            with t5:
                st.subheader("💬 Задать вопрос по видео")
                video_id = data.get("video_id", "")
                
                chat_history_key = f"chat_{video_id}"
                if chat_history_key not in st.session_state:
                    st.session_state[chat_history_key] = []
                    
                chat_container = st.container(height=400, border=False)
                for msg in st.session_state[chat_history_key]:
                    with chat_container.chat_message(msg["role"]):
                        st.write(msg["content"])
                        if "sources" in msg and msg["sources"]:
                            with st.expander("Источники"):
                                for s in msg["sources"]:
                                    st.write(f"- [{s['timestamp']}]({s['url']})")

                prompt = st.chat_input("Спросите что-нибудь по видео...", key=f"chat_input_{video_id}")
                if prompt:
                    st.session_state[chat_history_key].append({"role": "user", "content": prompt})
                    with chat_container.chat_message("user"):
                        st.write(prompt)
                    
                    with chat_container.chat_message("assistant"):
                        with st.spinner("Ищу ответ..."):
                            ans = ask_question(video_id, prompt)
                            if ans:
                                st.write(ans["answer"])
                                if ans.get("sources"):
                                    with st.expander("Источники"):
                                        for s in ans["sources"]:
                                            st.write(f"- [{s['timestamp']}]({s['url']})")
                                st.session_state[chat_history_key].append({
                                    "role": "assistant", 
                                    "content": ans["answer"],
                                    "sources": ans.get("sources", [])
                                })
                            else:
                                st.error("Не удалось получить ответ.")

            st.divider()


# ═══════════════════════════════════════════════════════════════════
#  PAGE: Library
# ═══════════════════════════════════════════════════════════════════
elif st.session_state.page == "Library":
    st.title("📚 Ваша Библиотека")
    videos = get_all_videos()

    if not videos:
        st.info("В библиотеке пока пусто. Сгенерируйте свой первый подкаст!")
    else:
        for v in videos:
            with st.container():
                cols = st.columns([1, 4, 1, 1])

                video_id = v["video_id"]
                cols[0].image(
                    f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
                )

                with cols[1]:
                    cat = v.get("category", "unknown")
                    cat_label = CATEGORY_LABELS.get(cat, cat)
                    st.markdown(f"### [Видео {video_id}]({v['url']})")
                    st.caption(
                        f"{cat_label} · Язык: {v.get('language', '?')} · "
                        f"{v.get('duration_sec', 0):.0f} сек"
                    )

                if cols[2].button("👁️", key=f"view_{video_id}"):
                    st.session_state.selected_library_video = video_id

                if cols[3].button("🗑️", key=f"del_{video_id}"):
                    if delete_video(video_id):
                        st.toast(f"Видео {video_id} удалено")
                        if st.session_state.selected_library_video == video_id:
                            st.session_state.selected_library_video = None
                        st.rerun()

        # ── Detail panel for selected video ──
        sel_id = st.session_state.selected_library_video
        if sel_id:
            st.divider()
            details = get_video_details(sel_id)
            if details:
                st.subheader(f"📋 Детали: {sel_id}")

                lib_t1, lib_t2, lib_t3, lib_t4, lib_t5 = st.tabs(
                    ["📝 Конспект", "🎬 Скрипт", "🎙️ Аудио", "🎯 Рекомендации", "💬 Спросить"]
                )

                with lib_t1:
                    st.markdown(details.get("summary", ""))
                    kw = details.get("keywords", [])
                    if kw:
                        st.write("---")
                        st.write("**Ключевые слова:**")
                        st.write(", ".join(kw))

                with lib_t2:
                    st.text_area(
                        "Сценарий диалога",
                        details.get("podcast_script", ""),
                        height=400,
                        key=f"lib_script_{sel_id}",
                    )

                with lib_t3:
                    audio_resp = requests.get(f"{API_URL}/videos/{sel_id}/audio")
                    if audio_resp.status_code == 200:
                        st.audio(f"{API_URL}/videos/{sel_id}/audio")
                    else:
                        st.info("🎙️ Аудио ещё не сгенерировано.")
                        if st.button("Создать аудио", key=f"lib_gen_audio_{sel_id}"):
                            with st.spinner("Генерирую..."):
                                r = requests.post(f"{API_URL}/videos/{sel_id}/audio", timeout=300)
                                if r.status_code == 200:
                                    st.success("✅ Аудио готово!")
                                    st.rerun()
                                else:
                                    st.error(r.text)

                with lib_t4:
                    st.subheader("🎯 Рекомендации")

                    # Check cache key for this video's recommendations
                    rec_cache_key = f"lib_rec_{sel_id}"
                    if rec_cache_key not in st.session_state:
                        st.session_state[rec_cache_key] = None

                    cached_rec = st.session_state[rec_cache_key]

                    if cached_rec and (cached_rec.get("courses") or cached_rec.get("books")):
                        render_recommendations(cached_rec)
                    else:
                        if st.button("🔍 Загрузить рекомендации", key=f"btn_rec_lib_{sel_id}", use_container_width=True):
                            with st.status("🔍 Генерация рекомендаций...", expanded=True) as lib_rec_status:
                                st.write("🕵️ Анализируем контекст видео...")
                                time.sleep(0.5)
                                st.write("🌐 Ищем релевантные курсы и книги...")

                                rec_result = get_recommendations(sel_id)

                                if rec_result and (rec_result.get("courses") or rec_result.get("books")):
                                    st.write("✨ Готово!")
                                    lib_rec_status.update(label="✅ Рекомендации найдены!", state="complete", expanded=False)
                                    st.session_state[rec_cache_key] = rec_result
                                    # Render inline immediately
                                    render_recommendations(rec_result)
                                else:
                                    lib_rec_status.update(label="❌ Ошибка", state="error", expanded=False)
                                    st.error("Не удалось получить рекомендации.")
                                    
                with lib_t5:
                    st.subheader("💬 Задать вопрос по видео")
                    
                    chat_history_key = f"lib_chat_{sel_id}"
                    if chat_history_key not in st.session_state:
                        st.session_state[chat_history_key] = []
                        
                    chat_container = st.container(height=400, border=False)
                    for msg in st.session_state[chat_history_key]:
                        with chat_container.chat_message(msg["role"]):
                            st.write(msg["content"])
                            if "sources" in msg and msg["sources"]:
                                with st.expander("Источники"):
                                    for s in msg["sources"]:
                                        st.write(f"- [{s['timestamp']}]({s['url']})")

                    prompt = st.chat_input("Спросите что-нибудь по видео...", key=f"lib_chat_input_{sel_id}")
                    if prompt:
                        st.session_state[chat_history_key].append({"role": "user", "content": prompt})
                        with chat_container.chat_message("user"):
                            st.write(prompt)
                        
                        with chat_container.chat_message("assistant"):
                            with st.spinner("Ищу ответ..."):
                                ans = ask_question(sel_id, prompt)
                                if ans:
                                    st.write(ans["answer"])
                                    if ans.get("sources"):
                                        with st.expander("Источники"):
                                            for s in ans["sources"]:
                                                st.write(f"- [{s['timestamp']}]({s['url']})")
                                    st.session_state[chat_history_key].append({
                                        "role": "assistant", 
                                        "content": ans["answer"],
                                        "sources": ans.get("sources", [])
                                    })
                                else:
                                    st.error("Не удалось получить ответ.")
            else:
                st.warning(f"Видео {sel_id} не найдено в кэше.")
                st.session_state.selected_library_video = None

elif st.session_state.page == "Settings":
    st.title("⚙️ Настройки")

    st.header("Управление данными")
    st.write("Очистка кэша поможет освободить место в базе данных.")

    if st.button("🧹 Удалить устаревшие (7+ дней)"):
        try:
            r = requests.delete(f"{API_URL}/videos/expired")
            st.success(r.json().get("message"))
        except:
            st.error("Не удалось связаться с API")

    st.divider()
    st.header("О сервисе")
    st.info("VideoFlow v1.0.0 — Инструмент для автоматизации контента.")
