FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir aiohttp watchfiles mutagen

COPY app/ ./
COPY static/ /static/

EXPOSE 3010

CMD ["python", "server.py"]