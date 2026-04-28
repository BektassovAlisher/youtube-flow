FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/app

EXPOSE 8000 8501

CMD ["sh", "-c", "uvicorn app.api.api:app --host 0.0.0.0 --port 8000 & streamlit run app/ui/ui.py --server.port 8501 --server.address 0.0.0.0"]



