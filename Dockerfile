FROM node:22-bookworm-slim AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Install the Elastic MCP server for use in Cloud Run (no Docker daemon available)
RUN npm install -g @elastic/mcp-server-elasticsearch@0.3.1

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Copy Node runtime + Elastic MCP server binary from the build stage
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node
COPY --from=web-build /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=web-build /usr/local/bin/mcp-server-elasticsearch /usr/local/bin/mcp-server-elasticsearch

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY --from=web-build /app/web/dist ./web/dist

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
