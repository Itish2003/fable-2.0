# Fable 2.0's canonical deploy artifact: engine + A2A project agent, one
# uvicorn process. Single process serves the engine's own routes plus /a2a
# and /.well-known/agent-card.json (src/a2a_agent.py, mounted in src/main.py).
# eve-agent/ is retired as a reference implementation and not used here.

FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml && \
    uv pip install --system --no-cache greenlet

COPY src ./src

EXPOSE 8001

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
