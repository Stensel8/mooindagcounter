FROM python:3.14-slim@sha256:f54c5f39326ef06c7cb7f5fc57025aa5b7a1d3367cea42d8b5d3c8e082338ec5

WORKDIR /app

# Mooindag... Niet als root draaien.
RUN adduser --disabled-password --gecos "" appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
