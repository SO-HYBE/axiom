# syntax=docker/dockerfile:1

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AXIOM_HOST=0.0.0.0 \
    AXIOM_PORT=8767 \
    AXIOM_ALLOWED_HOSTS=localhost:8767,127.0.0.1:8767

WORKDIR /app

# Dependencies come from the bundled wheelhouse, so the image build itself does
# not require PyPI access. pypdf is used only by corpus ingestion.
COPY wheelhouse/ ./wheelhouse/
RUN python -m pip install --no-index --find-links ./wheelhouse "pypdf==6.13.0" "setuptools==80.9.0"

COPY pyproject.toml requirements.txt ./
COPY src/ ./src/
COPY data/ ./data/
COPY benchmarks/ ./benchmarks/
COPY runs/ ./runs/
COPY docs/ ./docs/
COPY README.md LICENSE CITATION.cff THIRD_PARTY_NOTICES.md SUBMISSION.md ./

RUN python -m pip install --no-index --find-links ./wheelhouse --no-build-isolation . \
    && useradd --create-home --uid 10001 axiom \
    && mkdir -p /app/runs/scenarios \
    && chown -R axiom:axiom /app/runs

USER axiom

EXPOSE 8767

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8767/healthz',timeout=4).status==200 else 1)"

CMD ["python", "-m", "axiom", "serve"]
