# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build
# Download only upstream wheels verified by the committed Python 3.14 lock.
COPY requirements.lock ./
RUN pip download --only-binary=:all: --require-hashes --dest /wheels -r requirements.lock

# --------------------------------------------------------------------------
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# UID/GID 1000 matches the pods' securityContext (runAsUser/runAsGroup 1000).
# --only-upgrade zlib1g: pick up the fixed zlib1g even when the base image is
# older than the Debian security update (trivy gate: HIGH CVEs with a fix).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && apt-get install -y --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /app app

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY --from=builder /build/requirements.lock /tmp/requirements.lock
# pip and setuptools are not needed at run time (uvicorn, alembic and the
# CronJobs are plain `python -m ...` entrypoints) and the base image's vendored
# copies (msgpack, urllib3, setuptools) carry HIGH CVEs, so remove them once the
# app deps are installed.
RUN pip install --no-index --find-links=/wheels --require-hashes -r /tmp/requirements.lock \
    && rm -rf /wheels /tmp/requirements.lock \
    && python -m pip uninstall -y pip setuptools wheel \
    && rm -rf /usr/local/lib/python3*/site-packages/pip \
              /usr/local/lib/python3*/site-packages/pip-*.dist-info \
              /usr/local/lib/python3*/site-packages/setuptools \
              /usr/local/lib/python3*/site-packages/setuptools-*.dist-info \
              /usr/local/lib/python3*/site-packages/wheel \
              /usr/local/lib/python3*/site-packages/wheel-*.dist-info \
              /usr/local/lib/python3*/site-packages/pkg_resources \
              /usr/local/lib/python3*/site-packages/_distutils_hack \
              /usr/local/lib/python3*/site-packages/distutils-precedence.pth \
              /usr/local/lib/python3*/ensurepip/_bundled

COPY --chown=app:app . /app

USER 1000:1000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# One worker per pod: scale with replicas. Prometheus metrics then come from
# a single process (see /metrics for the PROMETHEUS_MULTIPROC_DIR option).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
