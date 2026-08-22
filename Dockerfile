# ---- Frontend Build ----
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Backend ----
FROM python:3.13-slim AS backend
WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install --no-cache-dir uv

# 先复制依赖定义，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 复制业务代码
COPY agent/ agent/
COPY flow_config/ flow_config/

# 复制前端产物
COPY --from=frontend-build /app/frontend/dist/ frontend/dist/

EXPOSE 18082

CMD ["uv", "run", "uvicorn", "agent.api.app:app", "--host", "0.0.0.0", "--port", "18082"]
