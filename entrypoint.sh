#!/bin/sh
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

python manage.py migrate --noinput
exec "$@"
