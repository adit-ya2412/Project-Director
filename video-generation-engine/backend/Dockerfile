FROM python:3.12-slim

# Pin ffmpeg to the version measured in this image on 2026-08-19
# (Track C §14.6): 7.1.5 on Debian trixie. A bare `apt-get install
# ffmpeg` tracks the base image's snapshot — python:3.12-slim moving
# bookworm → trixie is how §4.2a's "5.1" claim went stale. The
# render cache is already safe across binaries (`ffmpeg_version` is
# in the fingerprint); the pin makes the argv-flag branch and the
# plan's claims deterministic. Epoch `7:` is Debian's package epoch.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg=7:7.1.5-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
