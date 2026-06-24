# Slim Python 3.12 base image — matches what Railway and our GitHub Actions CI
# use, and tiny enough (~50MB before deps) to keep cold-start pulls fast.
FROM python:3.12-slim

# tulipy is a C extension that compiles from source on install (no prebuilt wheel
# for it exists), so the slim base image needs gcc + Python headers.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# tulipy 0.4.0 was last updated in 2020 and is incompatible with two newer libs:
#   - numpy 2.x changed C API pointer constness (need numpy<2)
#   - Cython 3.x generates stricter C code than tulipy's source expects (need cython<3)
# Pre-install both at the correct old versions, then build tulipy with
# --no-build-isolation so it reuses these instead of pulling latest into an
# isolated build env.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "numpy<2" "cython<3" "setuptools" "wheel" && \
    pip install --no-cache-dir --no-build-isolation tulipy==0.4.0 && \
    pip install --no-cache-dir -r requirements.txt

# Copy the actual app code AFTER deps are cached.
COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
