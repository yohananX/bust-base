# Production Runbook

## CI/CD Pipeline

GitHub Actions workflows live in `.github/workflows/`.

### CI (`ci.yml`)
- Triggers: push to `main`/`develop`, pull requests to `main`/`develop`
- Jobs:
  - **lint**: runs `ruff check .`
  - **test**: spins up PostgreSQL service, installs deps, runs `python manage.py test --settings=school.test_settings`
- Artifacts: coverage report uploaded as `coverage-report`

### Deploy (`deploy.yml`)
- Triggers: push to `main`, manual `workflow_dispatch`
- Builds Docker image and pushes to GitHub Container Registry (`ghcr.io`)
- Image tags: `<commit-sha>` and `latest`

### Required GitHub Secrets
- None for public repos (uses `GITHUB_TOKEN`)
- For private registries: add `CR_PAT` or configure registry credentials

---

## Database Backups

### Manual Backup

```powershell
# SQLite (local/dev)
python manage.py backup_database --settings=school.test_settings

# PostgreSQL (production)
$env:DATABASE_URL='postgres://user:pass@host:5432/dbname'
python manage.py backup_database --compress
```

Backups are stored in `./backups/` by default. Use `--output-dir` to change location.

### Automated Backups

**Option A — Cron on host:**
```cron
0 2 * * * cd /app && python manage.py backup_database --compress >> /var/log/db-backup.log 2>&1
```

**Option B — Docker Compose scheduled task:**
Add a `backup` service to `docker-compose.yml`:
```yaml
backup:
  image: ghcr.io/your-org/bust-base:latest
  command: python manage.py backup_database --compress
  env_file: .env
  volumes:
    - media_data:/app/media
    - backup_data:/app/backups
  restart: unless-stopped
```
Then trigger via `docker compose exec backup python manage.py backup_database`.

**Option C — Managed DB backups:**
Use your cloud provider's automated PostgreSQL backups (RDS, Cloud SQL, Supabase, etc.).

---

## Database Restore

### List available backups

```powershell
# Local backups directory
dir backups\

# Docker volume
docker compose exec web dir /app/backups
```

### Restore from backup

**Important:** Restore overwrites the current database. All data since the backup will be lost.

```powershell
# SQLite (local/dev)
python manage.py restore_database backup_20260101_020000.sqlite3 --confirm

# PostgreSQL (production)
$env:DATABASE_URL='postgres://user:pass@host:5432/dbname'
python manage.py restore_database backup_20260101_020000.sql --confirm
```

### Post-restore steps

1. Run migrations if needed:
   ```powershell
   python manage.py migrate --noinput
   ```
2. Collect static files:
   ```powershell
   python manage.py collectstatic --noinput
   ```
3. Restart `web` and `worker` services:
   ```powershell
   docker compose up -d --force-recreate web worker
   ```
4. Verify `/health/` returns `{"status": "ok"}`

### What restore covers

- **Database data**: all tables, users, students, fees, payments, etc.
- **NOT covered**: media files (logos, receipts, proof images), static files, logs
- For full recovery, also backup the `media/` directory:
  ```powershell
  # Tar media directory alongside DB backup
  tar -czf backups/media_20260101.tar.gz media/
  ```

### Safety notes

- Always verify the backup file integrity before restoring
- Test restore procedure in staging first
- Keep at least 3 backup generations
- Store backups off-server (S3, GCS, separate host)
- The `--confirm` flag prevents accidental restores

---

## Credential Setup Guide

### SECRET_KEY
```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Database
- Create a PostgreSQL database and user
- Set `DATABASE_URL` in `.env`
- Example: `postgres://bust_user:strong_password@db.example.com:5432/bustbase`

### Paystack
1. Sign up at https://paystack.com
2. Go to Settings → Developers → API Keys
3. Copy live secret key (`sk_live_*`) and public key (`pk_live_*`)
4. Set in `.env`

### Brevo (Email)
1. Sign up at https://app.brevo.com
2. Go to SMTP & API → API Keys
3. Create a new API key
4. Set `BREVO_API_KEY` in `.env`
5. Verify your sender domain in Brevo

### AWS S3 (Optional)
1. Create S3 bucket
2. Create IAM user with S3 access
3. Get Access Key ID and Secret Access Key
4. Set `USE_S3=True` and AWS credentials in `.env`

### Sentry (Optional)
1. Sign up at https://sentry.io
2. Create a project
3. Copy DSN from Project Settings → Client Keys
4. Set `SENTRY_DSN` in `.env`

---

## Deployment Checklist

1. Copy `.env.production.example` to `.env` on your production server
2. Generate a real `SECRET_KEY` and set it in `.env`
3. Set `DEBUG=False` in `.env`
4. Configure `ALLOWED_HOSTS` with your real domain(s)
5. Set `DATABASE_URL` to your production PostgreSQL database
6. Add Paystack live keys (`sk_live_*`, `pk_live_*`)
7. Add Brevo API key from https://app.brevo.com/settings/keys/api-key
8. Configure `DEFAULT_FROM_EMAIL` with your verified domain
9. Confirm `SECURE_SSL_REDIRECT=True` and HSTS settings
10. For S3 media: set `USE_S3=True` and AWS credentials
11. For error monitoring: set `SENTRY_DSN`
12. Run migrations: `python manage.py migrate --noinput`
13. Collect static files: `python manage.py collectstatic --noinput`
14. Start `db`, `redis`, `web`, and `worker` services
15. Verify `/health/` endpoint returns `{"status": "ok"}`
16. Check worker queue: `python manage.py qcluster` is running

---

## Rollback

```powershell
# Rollback to previous image
docker compose up -d --force-recreate web worker

# Or specify a previous tag
docker compose up -d --force-recreate web worker
# then update image tag in docker-compose.yml
```

## Caching

- **Development**: `locmem` cache backend (no Redis required)
- **Production**: Redis via `django-redis` at `REDIS_URL`
- Docker Compose includes a `redis` service on port `6379`
- Cache invalidation: restart `web` and `worker` services

## S3 / Media Storage

- Set `USE_S3=True` and configure `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`
- Media files upload to `<bucket>.s3.amazonaws.com/media/`
- Static files remain on WhiteNoise / local storage
- Local fallback: `USE_S3=False` uses filesystem storage at `MEDIA_ROOT`

## Error Monitoring

- Set `SENTRY_DSN` to enable Sentry integration
- Optional: `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_PROFILES_SAMPLE_RATE`
- `send_default_pii=False` — no PII sent to Sentry
- Django exceptions, unhandled errors, and performance traces captured

---

## Monitoring

- Logs: structured JSON to stdout, captured by Docker/Kubernetes
- Health: `/health/` endpoint checks DB connectivity
- Queue: monitor Django-Q2 `queue_limit=50` saturation
- Payments: webhook logs in `fees_webhooklog` table
