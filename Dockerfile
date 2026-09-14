FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ARRMEDIC_CONFIG_DIR=/config

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 7080

CMD ["uvicorn", "app.bootstrap:app", "--host", "0.0.0.0", "--port", "7080"]
