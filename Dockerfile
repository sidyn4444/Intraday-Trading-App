# Slim Python 3.12 base image — matches what Railway and our GitHub Actions CI
# use, and tiny enough (~50MB) to keep cold-start pulls fast.
FROM python:3.12-slim

# Standard practice: keep the app under /app. Everything we COPY ends up here.
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
