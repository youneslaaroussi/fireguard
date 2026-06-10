FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    numpy \
    pandas \
    scipy \
    scikit-learn \
    matplotlib \
    networkx \
    requests \
    beautifulsoup4 \
    lxml \
    pyarrow \
    duckdb \
    polars \
    sympy

WORKDIR /workspace
