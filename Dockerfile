FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.9.3 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY config ./config
RUN uv sync --locked --no-dev && useradd -u 10001 -m arbitrary && mkdir -p data && chown -R arbitrary:arbitrary /app
USER arbitrary
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["flasharb"]
CMD ["observe"]
