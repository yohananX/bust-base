"""Database backup management command for PostgreSQL and SQLite."""
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Create a database backup (PostgreSQL via pg_dump or SQLite copy).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default=None,
            help='Directory to store backups (default: BASE_DIR / backups)',
        )
        parser.add_argument(
            '--compress',
            action='store_true',
            help='Compress backup with gzip (PostgreSQL only)',
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'] or (settings.BASE_DIR / 'backups'))
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        engine = settings.DATABASES['default'].get('ENGINE', '')

        if 'postgresql' in engine:
            self._backup_postgresql(output_dir, timestamp, options['compress'])
        elif 'sqlite' in engine:
            self._backup_sqlite(output_dir, timestamp)
        else:
            raise CommandError(f'Unsupported database engine: {engine}')

    def _backup_postgresql(self, output_dir, timestamp, compress):
        """Run pg_dump using Django's DATABASES connection settings."""
        pg_dump = 'pg_dump'
        try:
            subprocess.run([pg_dump, '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise CommandError('pg_dump not found. Install PostgreSQL client tools.') from exc

        config = settings.DATABASES['default']
        filename = f'backup_{timestamp}.sql'
        if compress:
            filename += '.gz'
        output_path = output_dir / filename

        self.stdout.write(f'Backing up PostgreSQL database to {output_path}...')

        env = {
            **subprocess.os.environ,
            'PGDATABASE': config['NAME'],
            'PGUSER': config.get('USER', ''),
            'PGPASSWORD': config.get('PASSWORD', ''),
            'PGHOST': config.get('HOST', 'localhost'),
            'PGPORT': str(config.get('PORT', '5432')),
        }

        cmd = [pg_dump, '--format=plain', '--no-owner', '--no-acl']
        if compress:
            import gzip
            with gzip.open(output_path, 'wb') as gz:
                result = subprocess.run(
                    cmd,
                    stdout=gz,
                    stderr=subprocess.PIPE,
                    env=env,
                )
        else:
            with open(output_path, 'wb') as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    env=env,
                )

        if result.returncode != 0:
            raise CommandError(f'Backup failed: {result.stderr.decode()}')

        size = output_path.stat().st_size / 1024 / 1024
        self.stdout.write(f'Backup complete: {output_path} ({size:.1f} MB)')

    def _backup_sqlite(self, output_dir, timestamp):
        """Copy SQLite database file."""
        db_file = Path(settings.DATABASES['default']['NAME'])
        if not db_file.exists():
            raise CommandError(f'SQLite database not found: {db_file}')

        if not db_file.is_file():
            raise CommandError(f'Database path is not a file: {db_file}')

        output_path = output_dir / f'backup_{timestamp}.sqlite3'
        self.stdout.write(f'Backing up SQLite database to {output_path}...')

        shutil.copy2(db_file, output_path)

        size = output_path.stat().st_size / 1024 / 1024
        self.stdout.write(f'Backup complete: {output_path} ({size:.1f} MB)')
