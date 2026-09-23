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

# Ensure media and static directories exist with correct permissions
mkdir -p /app/media /app/staticfiles
chown -R $(id -u):$(id -g) /app/media /app/staticfiles

# Apply database migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Execute the command passed to the container
exec "$@"
