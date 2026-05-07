# Control-panel image: FastAPI + Jinja + a docker CLI for `docker exec`.
# Built on python:3.12-slim because we don't need anything heavier — the
# panel does no inference of its own, it just orchestrates `docker exec`
# into the curl container and streams the output to the browser.
FROM python:3.12-slim

# docker CLI (we mount /var/run/docker.sock from the host; this binary is
# what actually issues the `docker exec` calls).
RUN apt-get update \
 && apt-get install -y --no-install-recommends docker.io ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8083
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8083"]
