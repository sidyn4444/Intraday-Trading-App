# Slim Python 3.12 base image — matches Railway's Python version and our CI.
# We can use modern Python because we install requirements-prod.txt (no tulipy)
# instead of the full requirements.txt — tulipy is a 2020-vintage C extension
# that doesn't build on Python 3.11+, and the deployed dashboard never imports
# it anyway. Only the local strategy scripts use tulipy.
FROM python:3.12-slim

WORKDIR /app

# Copy ONLY the production requirements first so Docker can cache the
# dependency install layer separately from app code changes.
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-prod.txt

# Copy the actual app code AFTER deps are cached.
COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
