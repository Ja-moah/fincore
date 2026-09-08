FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN addgroup --system fincore \
    && adduser --system --ingroup fincore fincore

COPY --chown=fincore:fincore . .

RUN SECRET_KEY=collectstatic-build-only-not-a-secret \
    JWT_SIGNING_KEY=collectstatic-build-only-not-a-secret \
    python manage.py collectstatic --noinput

USER fincore

EXPOSE 8000

CMD ["sh", "/app/bin/start.sh"]
