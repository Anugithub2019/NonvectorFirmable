# Streamlit demo image. Expects the DuckDB file and a reachable Neo4j (see docker-compose.yml).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
COPY demo ./demo
COPY ontology ./ontology
COPY sources.yaml ./
ENV NEO4J_URI=bolt://neo4j:7687
EXPOSE 8501
CMD ["uv", "run", "streamlit", "run", "demo/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
