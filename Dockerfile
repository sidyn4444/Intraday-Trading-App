# Slim Python 3.12 base image — matches what Railway and our GitHub Actions CI
# use, and tiny enough (~50MB before deps) to keep cold-start pulls fast.
FROM python:3.12-slim

# tulipy is a C extension that compiles from source on install (no prebuilt wheel
# for it exists), so the slim base image needs gcc + Python headers. We install
# them as a CACHED Docker layer so we only pay this cost once — code edits below
# don't bust this layer. `--no-install-recommends` and the rm of /var/lib/apt/lists
# keep the image lean (~150MB total instead of full python:3.12 at ~900MB).
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Standard practice: keep the app under /app.
WORKDIR /app

# Copy ONLY requirements.txt first, install deps, THEN copy the rest of the code.
# This lets Docker cache the dependency install layer — when we change app code
# (the most common edit), the cached pip-install layer is reused and the build
# takes ~5 seconds instead of ~90.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the actual app code AFTER deps are cached.
COPY . .

# Document that the container listens on 8000 by default. This is just metadata —
# the real port comes from the CMD below. Railway/Kubernetes overrides this anyway.
EXPOSE 8000

# Start uvicorn binding to 0.0.0.0 so the container is reachable from outside.
# Reads the PORT env var to support cloud platforms that assign ports dynamically
# (Railway, Heroku, Cloud Run). Defaults to 8000 if PORT isn't set, so `docker run`
# without env vars still works locally.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
