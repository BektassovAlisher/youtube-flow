import streamlit as st
import requests
import time

API_URL = "http://127.0.0.1:8000"

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
    </style>
""", unsafe_allow_html=True)

if 'page' not in st.session_state:
    st.session_state.page = "Generate"

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

def ask_question(video_id, question):
    try:
        r = requests.post(f"{API_URL}/videos/{video_id}/qa", json={"question": question})
        return r.json() if r.status_code == 200 else None
    except:
        return None

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

if st.session_state.page == "Generate":
    st.title("✨ Создать новый подкаст")
    st.write("Вставьте ссылку на YouTube видео, и наш ИИ превратит его в увлекательный подкаст.")

    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")

    if st.button("🚀 Начать магию", disabled=not url):
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

                    # ── Classification badge ──
                    cat = data.get("video_category", "unknown")
                    cat_label = CATEGORY_LABELS.get(cat, cat)

                    # ── Rejected? ──
                    if data.get("rejected"):
                        status.update(
                            label="🚫 Видео отклонено классификатором",
                            state="error",
                            expanded=False,
                        )
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
                        status.update(
                            label="✅ Готово! Текст сохранён в кэш.",
                            state="complete",
                            expanded=False,
                        )

                        # Classification info
                        st.markdown(
                            f'<span class="category-badge">{cat_label}</span>',
                            unsafe_allow_html=True,
                        )

                        t1, t2, t3, t4 = st.tabs(
                            ["📝 Конспект", "🎬 Скрипт", "🎙️ Аудио", "💬 Чат с видео"]
                        )

                        with t1:
                            st.markdown(data["summary"])
                            st.write("---")
                            st.write("**Ключевые слова:**")
                            st.write(", ".join(data["keywords"]))

                        with t2:
                            st.text_area(
                                "Сценарий диалога",
                                data["podcast_script"],
                                height=400,
                            )

                            st.caption(f"Кэш: {'Использован' if data['cache_hit'] else 'Создан заново'}")

                        with t4:
                            st.subheader("💬 Спроси что-нибудь у этого видео")
                            if "chat_history" not in st.session_state:
                                st.session_state.chat_history = {}
                            
                            v_id = data['video_id']
                            if v_id not in st.session_state.chat_history:
                                st.session_state.chat_history[v_id] = []
                            
                            # Показываем историю
                            for chat in st.session_state.chat_history[v_id]:
                                with st.chat_message("user"):
                                    st.write(chat["question"])
                                with st.chat_message("assistant"):
                                    st.write(chat["answer"])
                                    if chat.get("sources"):
                                        with st.expander("Источники"):
                                            for s in chat["sources"]:
                                                st.markdown(f"- [{s['timestamp']}]({s['url']})")

                            # Поле ввода
                            if q := st.chat_input("Напр.: О чем говорилось на 15-й минуте?"):
                                st.session_state.chat_history[v_id].append({"question": q, "answer": "..."})
                                with st.spinner("Думаю..."):
                                    ans = ask_question(v_id, q)
                                    if ans:
                                        st.session_state.chat_history[v_id][-1]["answer"] = ans["answer"]
                                        st.session_state.chat_history[v_id][-1]["sources"] = ans["sources"]
                                        st.rerun()

                else:
                    st.error(f"Ошибка сервера: {response.text}")
            except Exception as e:
                st.error(f"Произошла ошибка: {str(e)}")

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
                    details = get_video_details(video_id)
                    if details:
                        with st.expander("Детали видео", expanded=True):
                            audio_resp = requests.get(f"{API_URL}/videos/{video_id}/audio")
                            if audio_resp.status_code == 200:
                                st.audio(f"{API_URL}/videos/{video_id}/audio")
                            else:
                                st.info("🎙️ Аудио ещё не сгенерировано.")
                                if st.button("Создать аудио", key=f"gen_{video_id}"):
                                    with st.spinner("Генерирую..."):
                                        r = requests.post(f"{API_URL}/videos/{video_id}/audio", timeout=300)
                                        if r.status_code == 200:
                                            st.success("✅ Аудио готово!")
                                            st.rerun()
                                        else:
                                            st.error(r.text)
                            st.markdown(details["summary"])
                            
                            st.divider()
                            st.subheader("💬 Чат с видео")
                            v_id = video_id
                            if "chat_history" not in st.session_state:
                                st.session_state.chat_history = {}
                            if v_id not in st.session_state.chat_history:
                                st.session_state.chat_history[v_id] = []
                            
                            for chat in st.session_state.chat_history[v_id]:
                                st.markdown(f"**Вы:** {chat['question']}")
                                st.markdown(f"**Ассистент:** {chat['answer']}")
                            
                            q_lib = st.text_input("Задать вопрос", key=f"q_{v_id}")
                            if st.button("Спросить", key=f"btn_q_{v_id}"):
                                with st.spinner("Поиск ответа..."):
                                    ans = ask_question(v_id, q_lib)
                                    if ans:
                                        st.session_state.chat_history[v_id].append({
                                            "question": q_lib, 
                                            "answer": ans["answer"]
                                        })
                                        st.rerun()

                if cols[3].button("🗑️", key=f"del_{video_id}"):
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

    if st.button("🧹 Удалить устаревшие (7+ дней)"):
        try:
            r = requests.delete(f"{API_URL}/videos/expired")
            st.success(r.json().get("message"))
        except:
            st.error("Не удалось связаться с API")

    st.divider()
    st.header("О сервисе")
    st.info("VideoFlow v1.0.0 — Инструмент для автоматизации контента.")
