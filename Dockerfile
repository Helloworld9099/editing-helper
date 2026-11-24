FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COACH_REQUIRE_AUTH=1 \
    COACH_RAG_ENABLED=1

WORKDIR /app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY app.py knowledge_rag.py public_access.py ./
COPY knowledge/sources/ ./knowledge/sources/
RUN python knowledge_rag.py build \
    && python -c 'from collections import Counter; from knowledge_rag import read_notes, SUPPORTED_EDITORS; n=read_notes(); c=Counter(x["editor"] for x in n); assert set(c)==SUPPORTED_EDITORS, f"Missing editors: {SUPPORTED_EDITORS-set(c)}"; print(f"Verified {len(n)} source records across {len(c)} editors")'

USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
