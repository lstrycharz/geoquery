FROM python:3.13-slim

# System deps: sqlite is built with extension-loading on debian's libsqlite3;
# build-essential covers any wheels that need to compile (fastembed pulls
# onnxruntime which ships wheels, but readability-lxml depends on libxml2).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so layer cache survives source-only changes.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[semantic,web,report,mcp]"

# Pre-download the fastembed model so the first `geoquery brief` doesn't pay
# the ~50MB download tax on every fresh container. This bakes the model into
# the image (commit point: chunk 7 of the build).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5').embed(['warmup'])"

COPY . .

# Default command runs the CLI. Override with e.g.:
#   docker compose run geoquery brief --company X --market Y
ENTRYPOINT ["python", "-m", "cli"]
CMD ["--help"]
