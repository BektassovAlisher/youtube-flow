from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from typing import List, Dict, Any
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
from langchain_ollama import ChatOllama
from agent.agent_state import llm2

CHROMA = "vector_storage/chroma_db"

base_embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

def get_vector_store(video_id: str) -> Chroma:
    return Chroma(
        persist_directory=CHROMA,
        embedding_function=base_embeddings,
        collection_name=video_id
    )

def index_video(video_id: str, documents: List[Document]):
    print(f"📄 RAG: Индексирую {len(documents)} фрагментов для видео {video_id}...")
    vector_store = Chroma(
        persist_directory=CHROMA,
        embedding_function=base_embeddings,
        collection_name=video_id
    )
   
    ids = [f"{video_id}_{i}" for i in range(len(documents))]
    
    vector_store.add_documents(documents=documents, ids=ids)
    print(f"✅ RAG: Индексация {video_id} завершена.")

def delete_video_index(video_id: str):
    try:
        vector_store = get_vector_store(video_id)
        vector_store.delete_collection()
        print(f"🗑️ RAG: Индекс для {video_id} удалён.")
    except Exception as e:
        print(f"⚠️ RAG: Ошибка при удалении индекса {video_id}: {e}")


def get_bm25_retriever(video_id: str, k: int = 3):
    vector_store = get_vector_store(video_id)
    all_data = vector_store.get()
    
    if not all_data or not all_data.get("documents"):
        return None

    docs = []
    for i in range(len(all_data["documents"])):
        docs.append(Document(
            page_content=all_data["documents"][i],
            metadata=all_data["metadatas"][i] if all_data["metadatas"] else {}
        ))
    
    bm25_retriever = BM25Retriever.from_documents(docs)
    bm25_retriever.k = k
    return bm25_retriever

def reciprocal_rank_fusion(docs_lists: List[List[Document]], k=3, c=60) -> List[Document]:
    doc_scores = {}
    for docs in docs_lists:
        for rank, doc in enumerate(docs):
            content = doc.page_content 
            score = 1 / (rank + c)
            if content in doc_scores:
                doc_scores[content]['score'] += score
            else:
                doc_scores[content] = {'doc': doc, 'score': score}
    
    sorted_docs = sorted(doc_scores.values(), key=lambda x: x['score'], reverse=True)
    return [item['doc'] for item in sorted_docs[:k]]

def ensemble_retrieve(video_id: str, query: str, k: int = 3) -> List[Document]:
    vector_store = get_vector_store(video_id)
    vector_retriever = vector_store.as_retriever(search_kwargs={"k": k})
    
    bm25_retriever = get_bm25_retriever(video_id, k)
    
    vector_docs = vector_retriever.invoke(query)
    
    if bm25_retriever:
        bm25_docs = bm25_retriever.invoke(query)
        return reciprocal_rank_fusion([bm25_docs, vector_docs], k=k)
    
    return vector_docs

prompt = ChatPromptTemplate.from_template("""Ты — эксперт-аналитик по контенту видео. Твоя задача: ответить на вопрос, опираясь на предоставленный контекст.

---КОНТЕКСТ---
{context}
---КОНЕЦ---

### ИНСТРУКЦИИ ПО ТИПАМ ВОПРОСОВ:

1. **Обзор (О чем видео):** Дай структуру и главную тему. Выдели 3-5 ключевых идей с таймстампами [MM:SS]. Укажи целевую аудиторию и пользу.
2. **Сравнение (A vs B):** Разбери плюсы/минусы каждого варианта. Сделай итоговый выбор "что и когда лучше" на основе мнений автора [MM:SS].
3. **Рекомендация (Что выбрать):** Дай конкретный совет без лишней неопределенности. Ссылайся на позицию автора с таймстампом [MM:SS].
4. **Объяснение (Что такое / Как работает):** Объясни концепцию простыми словами + аналогия. Укажи таймстамп объяснения [MM:SS].
5. **Инструкция (Как сделать):** Пошаговый алгоритм на основе видео. Упомяни ошибки, о которых предупреждает автор [MM:SS].
6. **Дискуссия (Мнение):** Сформулируй позицию, взвесив аргументы "за" и "против". Сопоставь свое мнение с мнением автора [MM:SS].

### ПРАВИЛА ОФОРМЛЕНИЯ:
- Хронология: Ссылайся на фрагменты видео строго в порядке их появления (от начала к концу). Не допускай прыжков во времени (например, [15:20], а затем [02:10]).
- Если темы нет в видео: Скажи об этом прямо, затем ответь на базе своих знаний.
- Стиль: Живой, экспертный, дружелюбный (не Wikipedia).
- Детали: Минимум 3-5 абзацев. Английские термины оставляй на английском.
- Обязательно: Каждое утверждение подтверждай таймстампом в формате [MM:SS].


Вопрос: {question}
""")

def format_docs(docs: List[Document]) -> str:
    result = []
    for doc in docs:
        timestamp = doc.metadata.get("timestamp", "")
        url = doc.metadata.get("youtube_url", "")
        result.append(f"[{timestamp}] ({url})\n{doc.page_content}")
    return "\n\n".join(result)

def ask(video_id: str, question: str) -> dict:
    docs = ensemble_retrieve(video_id, question, k=5)
    context = format_docs(docs)
   

    
    chain = prompt | llm2 | StrOutputParser()
    
    answer = chain.invoke({
        "context": context,
        "question": question
    })
    
    sources = []
    for d in docs:
        sources.append({
            "timestamp": d.metadata.get("timestamp", ""),
            "url": d.metadata.get("youtube_url", "")
        })
        
    return {
        "answer": answer,
        "sources": sources
    }
