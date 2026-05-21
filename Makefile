.PHONY: dev test lint format clean sync

# 取消外部虚拟环境干扰
unexport VIRTUAL_ENV

# 同步依赖到项目 .venv
sync:
	uv sync --all-groups

# 启动开发服务器
dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 运行测试
test:
	uv run pytest

# 运行测试并生成覆盖率报告
test-cov:
	uv run pytest --cov=app --cov-report=term-missing

# 代码检查
lint:
	uv run ruff check .

# 代码格式化
format:
	uv run ruff format .
	uv run ruff check --fix .

# 清理缓存文件
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf .ruff_cache htmlcov .coverage
