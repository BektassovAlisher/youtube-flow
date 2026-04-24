from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from typing import TypedDict, List, Annotated, Any
import operator
from dotenv import load_dotenv
import os

load_dotenv()
llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", api_key=os.getenv("GOOGLE_API_KEY"))
llm2 = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.getenv("GROQ_API_KEY"))

class GraphState(TypedDict):
    video_url: str
    transcript: str
    video_metadata: dict
    summary: str
    keywords: List[str]
    podcast_script: str
    audio_path: str
    agent_execution_order: Annotated[List[str], operator.add]
    retry_count: int
    critic_feedback: str
    max_retries: int
    is_valid: bool
    is_suitable: bool 
    cache_hit: bool
    video_category: str
    classification_reason: str
    classification_confidence: float
    skip_audio: bool  
    segments: List[Any]
    vector_index_status: str
    recommendation: dict


def extract_text(result) -> str:
    if isinstance(result.content, list):
        return result.content[0]["text"]
    return result.content