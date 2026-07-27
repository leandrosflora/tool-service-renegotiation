FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=65534:65534 app ./app

USER 65534:65534

EXPOSE 8400 8401
CMD ["python", "-m", "app.main"]
