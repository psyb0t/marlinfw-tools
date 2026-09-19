# syntax=docker/dockerfile:1.7
FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

FROM base AS dependencies

COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --prefix=/install \
        --require-hashes \
        --requirement /tmp/requirements.txt

FROM base AS runtime

COPY --from=dependencies /install /usr/local
COPY --chown=65532:65532 marlinfw_tools /app/marlinfw_tools
RUN rm -f /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

USER 65532:65532

ENTRYPOINT ["python", "-m", "marlinfw_tools.cli"]

FROM ghcr.io/astral-sh/ruff:0.16.3@sha256:afcc3c5d8893a58eff0189a7c7757e6a4ead99ced11f5d2649346413bf53245b AS ruff
FROM koalaman/shellcheck-alpine:v0.11.0@sha256:9955be09ea7f0dbf7ae942ac1f2094355bb30d96fffba0ec09f5432207544002 AS shellcheck

FROM base AS test

COPY --from=dependencies /install /usr/local
COPY --from=ruff /ruff /usr/local/bin/ruff
COPY --from=shellcheck /bin/shellcheck /usr/local/bin/shellcheck
COPY marlinfw_tools /work/marlinfw_tools
COPY tests /work/tests
COPY .agents/skills/marlinfw-control/scripts/marlinfw-tools.sh /work/marlinfw-tools.sh
COPY tests/fixtures/docker-fixture.sh /usr/local/bin/docker
RUN chmod 0555 /usr/local/bin/docker

WORKDIR /work
ENV PYTHONPATH=/work

ENTRYPOINT ["python", "-m", "unittest", "discover", "--start-directory", "tests", "--verbose"]
