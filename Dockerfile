FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8091 \
    CONFIG_PATH=/app/config.yaml

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py ./
RUN mkdir -p /app/data/.chunks /app/data/web/users

EXPOSE 8091

CMD ["python", "server.py"]
