FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir aiohttp watchfiles mutagen

COPY app/ ./

ENV METUBE_URL=http://metube:8081
ENV DOWNLOAD_DIR=/downloads
ENV PORT=3010

EXPOSE 3010

CMD ["python", "server.py"]
