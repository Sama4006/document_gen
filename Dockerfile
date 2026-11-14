FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend
COPY templates templates
COPY run.py .

ENV CHROMA_DB_PATH=/data/chroma OUTPUT_DIR=/data/output
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "run.py"]
