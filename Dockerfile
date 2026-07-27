FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip==26.1.2 \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8400 8401
CMD ["python", "-m", "app.main"]
