# Una sola imagen para simulador, servidor MCP, orquestador y API. La API sirve el panel ya compilado.
FROM node:22-alpine AS panel
WORKDIR /panel
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY dashboard/ ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY core core
COPY simulator simulator
COPY mcp_servers mcp_servers
COPY api api
COPY ops ops
COPY agents agents
COPY tests/fixtures tests/fixtures
COPY --from=panel /panel/dist dashboard/dist
RUN useradd --create-home teleco
USER teleco
