from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import os
from dotenv import load_dotenv
from typing import List
from langchain_core.documents import Document

load_dotenv()

class PersistentChromaStore:
    def __init__(self, persist_directory : str = "db/chroma_db"):
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model="models/embedding-001", 
            api_key=os.getenv("GOOGLE_API_KEY")
        )
        self.persist_directory = persist_directory
        if not os.path.exists(self.persist_directory):
            os.makedirs(self.persist_directory, exist_ok=True)
            
        self.vector_store = Chroma(
            persist_directory=self.persist_directory,
            embedding_function=self.embeddings,
            collection_name="video_transcripts"
        )

    def add_documents(self, documents: List[Document], video_id: str):
        for doc in documents:
            doc.metadata["video_id"] = video_id
        
        self.vector_store.add_documents(documents)
        print(f"✅ Векторная база: добавлено {len(documents)} чанков для видео {video_id}")

    def search(self, query: str, video_id: str, k: int = 5) -> List[Document]:
        return self.vector_store.similarity_search(
            query, 
            k=k, 
            filter={"video_id": video_id}
        )

rag_store = PersistentChromaStore() 

