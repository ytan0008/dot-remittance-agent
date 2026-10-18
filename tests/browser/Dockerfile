FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
RUN pip install --no-cache-dir playwright==1.58.0
WORKDIR /test
COPY tests/browser/smoke.py tests/browser/layout.py ./
CMD ["sh", "-c", "python smoke.py && python layout.py"]
