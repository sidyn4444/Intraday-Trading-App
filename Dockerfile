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

# tulipy 0.4.0 was last updated in 2020 against the numpy 1.x C API. By default
# pip creates a fresh "build env" for tulipy that pulls numpy 2.x, which breaks
# its C extension (`const double * const*` vs `double **` pointer mismatch).
# Pre-install build deps including numpy<2, then install tulipy with
# --no-build-isolation so it reuses the already-installed numpy 1.x.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "numpy<2" "cython" "setuptools" "wheel" && \
    pip install --no-cache-dir --no-build-isolation tulipy==0.4.0 && \
    pip install --no-cache-dir -r requirements.txt

# Copy the actual app code AFTER deps are cached.
COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
