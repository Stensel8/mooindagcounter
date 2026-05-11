FROM python:3.14-slim@sha256:1697e8e8d39bf168e177ac6b5fdab6df86d81cfc24dae17dfb96cfc3ef76b4dd

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
