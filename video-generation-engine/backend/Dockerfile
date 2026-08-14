FROM python:3.12-slim

# ffmpeg is pinned by the base image's apt snapshot; the renderer's
# determinism guarantee (Invariant I5) records this version in every
# render fingerprint (see docs/13_Implementation_Guide.md, Phase M8).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
