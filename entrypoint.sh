#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
python -c "
import psycopg2, time, os
while True:
    try:
        psycopg2.connect(os.environ['DATABASE_URL'])
        break
    except Exception:
        time.sleep(1)
"
echo "PostgreSQL is ready."

# Ensure media and static directories exist.
# NOTE: no chown here — the container runs as non-root `appuser` (see Dockerfile),
# so chown would always fail with "Operation not permitted" and, with `set -e`,
# kill the container before migrations. Ownership is set at build time and
# preserved via named volumes (see docker-compose.yml). WhiteNoise serves
# /static/ directly from Django, so no host bind-mount is required.
mkdir -p /app/media /app/staticfiles

# Apply database migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Execute the command passed to the container
exec "$@"
