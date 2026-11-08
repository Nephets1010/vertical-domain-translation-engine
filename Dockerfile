# ============================================================
# VDT-MT 多阶段构建镜像
# 阶段1(deps): 锁定并安装 Python 依赖
# 阶段2(runtime): 精简运行环境，非 root 运行
# ============================================================
FROM python:3.11-slim AS deps
WORKDIR /build
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=prod \
    DATABASE_URL=postgresql+psycopg://vdtmt:vdtmt@postgres:5432/vdtmt \
    REDIS_ENABLED=true \
    REDIS_URL=redis://redis:6379/0

# 运行时依赖（含 psycopg 驱动）
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY requirements.txt ./
RUN pip install --no-cache-dir psycopg[binary] prometheus-client

# 源码
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY sample_data ./sample_data

RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000 9090

# 启动前执行迁移，再拉起服务
CMD ["sh", "-c", "alembic upgrade head && uvicorn vdtmt.main:app --host 0.0.0.0 --port 8000"]
