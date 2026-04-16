import streamlit as st
import requests
import json
import time
from datetime import datetime

API_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="VideoFlow | AI Podcast Creator",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .main {
        background-color: #0e1117;
    }
    .stApp {
        color: #fafafa;
    }
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
    .card {
        padding: 20px;
        border-radius: 12px;
        background-color: #1e293b;
        border: 1px solid #334155;
        margin-bottom: 20px;
    }
    .status-badge {
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        background-color: #064e3b;
        color: #10b981;
    }
    </style>
""", unsafe_allow_html=True)

if 'page' not in st.session_state:
    st.session_state.page = "Generate"

def get_all_videos():
    try:
        r = requests.get(f"{API_URL}/videos")
        return r.json() if r.status_code == 200 else []
    except: return []

def get_video_details(video_id):
    try:
        r = requests.get(f"{API_URL}/videos/{video_id}")
        return r.json() if r.status_code == 200 else None
    except: return None

def delete_video(video_id):
    try:
        r = requests.delete(f"{API_URL}/videos/{video_id}")
        return r.status_code == 200
    except: return False

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
            st.write("🔍 Извлекаем транскрипт...")
            start_time = time.time()
            
            try:
                response = requests.post(f"{API_URL}/generate", json={"video_url": url}, timeout=300)
                
                if response.status_code == 200:
                    data = response.json()
                    status.update(label="✅ Готово! Подкаст создан.", state="complete", expanded=False)
                    
                    st.balloons()
                    
                    t1, t2, t3 = st.tabs(["🎙️ Аудио", "📝 Конспект", "🎬 Скрипт"])
                    
                    with t1:
                        st.subheader("Слушать подкаст")
                        audio_url = f"{API_URL}/videos/{data['video_id']}/audio"
                        st.audio(audio_url)
                        st.info(f"Кэш: {'Использован' if data['cache_hit'] else 'Создан заново'}")
                    
                    with t2:
                        st.markdown(data['summary'])
                        st.write("---")
                        st.write("**Ключевые слова:**")
                        st.write(", ".join(data['keywords']))
                    
                    with t3:
                        st.text_area("Сценарий диалога", data['podcast_script'], height=400)
                else:
                    st.error(f"Ошибка сервера: {response.text}")
            except Exception as e:
                st.error(f"Произошла ошибка: {str(e)}")

elif st.session_state.page == "Library":
    st.title("📚 Ваша Библиотека")
    videos = get_all_videos()
    
    if not videos:
        st.info("В библиотеке пока пусто. Сгенерируйте свой первый подкаст!")
    else:
        for v in videos:
            with st.container():
                cols = st.columns([1, 4, 1, 1])
                
                video_id = v['video_id']
                cols[0].image(f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg")
                
                with cols[1]:
                    st.markdown(f"### [Видео {video_id}]({v['url']})")
                    st.caption(f"Язык: {v.get('language', 'Unknown')} | Длительность: {v.get('duration_sec', 0)} сек")
                
                if cols[2].button("👁️ Просмотр", key=f"view_{video_id}"):
                    details = get_video_details(video_id)
                    if details:
                        with st.expander("Детали видео", expanded=True):
                            st.audio(f"{API_URL}/videos/{video_id}/audio")
                            st.markdown(details['summary'])
                
                if cols[3].button("🗑️ Удалить", key=f"del_{video_id}"):
                    if delete_video(video_id):
                        st.toast(f"Видео {video_id} удалено")
                        st.rerun()

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
