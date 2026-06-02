FROM python:3.11-slim AS base

WORKDIR /app

# 安装系统依赖（curl 用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 生产依赖（先复制依赖文件以利用 Docker 缓存）
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# 复制应用代码
COPY app/ ./app/

# 设置 PYTHONPATH 确保模块可被正确导入
ENV PYTHONPATH=/app
# 禁用 Python 输出缓冲，确保日志实时输出（对 SSE 流式响应尤为重要）
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 使用 uvicorn 启动服务，监听所有接口
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
