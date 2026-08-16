FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBUG=False

# libpq: psycopg2 | pango/cairo/gdk-pixbuf: WeasyPrint PDF rendering | fonts: PDF text
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libharfbuzz-subset0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

RUN addgroup --system --gid 1001 appgroup && adduser --system --uid 1001 --gid 1001 appuser && chown -R appuser:appgroup /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "school.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
