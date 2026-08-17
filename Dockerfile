# Single image shared by both services (api + ui); docker-compose picks the
# command. Keeps the two processes' dependencies in lockstep.
#
# Python 3.12, not the 3.13 the local .venv happens to use: langchain-chroma
# pins numpy<2.0, and numpy 1.26.x has no prebuilt wheel for 3.13 on this
# platform -- pip falls back to a source build that fails with no C compiler
# in the image. 3.12 has real wheels for this whole stack.

FROM python:3.12-slim

# tesseract-ocr: system binary pytesseract shells out to for the OCR fallback
# on scanned PDF pages (ingest.py). curl: used by the api healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Streamlit/FastAPI both bind 0.0.0.0 via the commands in docker-compose.yml;
# these EXPOSE lines are documentation only.
EXPOSE 8000 8501
