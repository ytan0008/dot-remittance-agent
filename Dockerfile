FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt && useradd --create-home --uid 10001 finance
COPY finance ./finance
COPY tests ./tests
RUN mkdir -p /app/data && chown finance:finance /app/data
USER finance
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --start-period=20s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["uvicorn", "finance.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
