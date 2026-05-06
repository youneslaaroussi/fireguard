FROM python:3.12-slim

WORKDIR /app
COPY apps/api/pyproject.toml ./apps/api/pyproject.toml
COPY apps/api/app ./apps/api/app
WORKDIR /app/apps/api
RUN pip install --no-cache-dir -e ".[bigquery]"
WORKDIR /app
COPY data ./data
WORKDIR /app/apps/api

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
