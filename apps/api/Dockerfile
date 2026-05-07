FROM python:3.12-slim

WORKDIR /app/apps/api
COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
RUN pip install --no-cache-dir -e ".[bigquery]"

WORKDIR /app
COPY data ./data

WORKDIR /app/apps/api
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
