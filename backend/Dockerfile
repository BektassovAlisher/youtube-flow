FROM python:3.11-slim

# ffmpeg: speech recognition fallback (cutting audio for Whisper)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# the embedding model is part of the image: no download at startup, no HuggingFace access needed at runtime
ENV FASTEMBED_CACHE_PATH=/opt/models
RUN python -c "from fastembed import TextEmbedding; \
TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/opt/models')"

COPY . .

ENV PYTHONPATH=/app/app PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "api.api:app", "--host", "0.0.0.0", "--port", "8000"]
