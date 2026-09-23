from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from typing import TypedDict, List, Annotated, Any
import operator
from dotenv import load_dotenv
import os

load_dotenv()
gemini = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", api_key=os.getenv("GOOGLE_API_KEY"))

gpt_120b = ChatGroq(model="openai/gpt-oss-120b", temperature=0, api_key=os.getenv("GROQ_API_KEY"))

gpt_20b = ChatGroq(model="openai/gpt-oss-20b", api_key=os.getenv("GROQ_API_KEY"))


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
    documents: List[Any]
    vector_index_status: str
    recommendation: dict


def extract_text(result) -> str:
    return result.text