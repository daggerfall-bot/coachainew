FROM python:3.11-slim

# FFmpeg + tesseract are required by the clip + OCR pipeline.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tesseract-ocr && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
# CPU-only torch for the API image; the GPU worker uses a CUDA base image.
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
EXPOSE 8000
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", "-b", "0.0.0.0:8000"]
