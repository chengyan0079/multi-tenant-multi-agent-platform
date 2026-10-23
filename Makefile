# 常用命令（conda env: agent_platform, py3.12）
.PHONY: install dev format test

install:
	conda activate agent_platform && pip install -e ".[dev]"

dev:
	uvicorn backend.main:app --reload --port 8000

format:
	ruff format backend tests
	ruff check --fix backend tests

test:
	pytest -q
