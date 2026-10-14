# One image for the API and the CPU worker; compose picks the command.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv \
    PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 MONSTER_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY monster ./monster
RUN uv sync --locked --no-dev

# Unprivileged by default. uid 1000 matches the owner of DATA_DIR on the home
# server, so creatures/ and the SQLite file stay readable without sudo; compose
# can override with PUID/PGID if a machine numbers its user differently.
RUN useradd --uid 1000 --user-group --no-create-home monster
USER monster

VOLUME /data
EXPOSE 8000
CMD ["uvicorn", "monster.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
