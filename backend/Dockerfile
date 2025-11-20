FROM python:3.11-slim

WORKDIR /app

# system deps for building some packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
