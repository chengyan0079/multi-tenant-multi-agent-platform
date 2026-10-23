# 多阶段构建（基于 conda agent_platform 镜像）
FROM continuumio/miniconda3:latest

# 建运行时，避免每次重装
RUN conda create -n agent_platform python=3.12 -y && conda clean -afy
ENV PATH=/opt/conda/envs/agent_platform/bin:$PATH

WORKDIR /app
COPY pyproject.toml README.md ./
COPY backend ./backend
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "backend.main:app_state.fastapi_app"]
