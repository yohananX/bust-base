"""Database restore management command for PostgreSQL and SQLite."""
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Restore a database backup (PostgreSQL via psql or SQLite copy).'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            type=str,
            help='Path to the backup file to restore from',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Required to confirm the restore operation',
        )
        parser.add_argument(
            '--output-dir',
            default=None,
            help='Directory where backups are stored (default: BASE_DIR / backups)',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError(
                'Refusing to restore without --confirm. '
                'This will overwrite the current database.'
            )

        output_dir = Path(options['output_dir'] or (settings.BASE_DIR / 'backups'))
        backup_path = Path(options['backup_file'])

        if not backup_path.is_absolute():
            backup_path = output_dir / backup_path

        if not backup_path.exists():
            raise CommandError(f'Backup file not found: {backup_path}')

        if not backup_path.is_file():
            raise CommandError(f'Backup path is not a file: {backup_path}')

        if backup_path.stat().st_size == 0:
            raise CommandError(f'Backup file is empty: {backup_path}')

        engine = settings.DATABASES['default'].get('ENGINE', '')

        if 'postgresql' in engine:
            self._restore_postgresql(backup_path)
        elif 'sqlite' in engine:
            self._restore_sqlite(backup_path)
        else:
            raise CommandError(f'Unsupported database engine: {engine}')

        self.stdout.write(self.style.SUCCESS('Restore completed successfully.'))

    def _restore_postgresql(self, backup_path):
        """Restore PostgreSQL database from a plain SQL dump."""
        psql = 'psql'
        try:
            subprocess.run([psql, '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            raise CommandError('psql not found. Install PostgreSQL client tools.') from exc

        config = settings.DATABASES['default']
        self.stdout.write(f'Restoring PostgreSQL database from {backup_path}...')

        safety_backup = None
        try:
            safety_backup = self._create_safety_backup()
            self.stdout.write(f'Safety backup created: {safety_backup}')
        except CommandError as exc:
            self.stderr.write(f'Warning: could not create safety backup: {exc}')

        env = {
            **subprocess.os.environ,
            'PGDATABASE': config['NAME'],
            'PGUSER': config.get('USER', ''),
            'PGPASSWORD': config.get('PASSWORD', ''),
            'PGHOST': config.get('HOST', 'localhost'),
            'PGPORT': str(config.get('PORT', '5432')),
        }

        with open(backup_path, 'r', encoding='utf-8') as f:
            result = subprocess.run(
                [psql, '--no-owner', '--no-acl'],
                stdin=f,
                stderr=subprocess.PIPE,
                env=env,
            )

        if result.returncode != 0:
            error_msg = result.stderr.decode()
            if safety_backup and safety_backup.exists():
                self.stderr.write(
                    f'Restore failed: {error_msg}\n'
                    f'A safety backup is available at: {safety_backup}'
                )
            else:
                self.stderr.write(f'Restore failed: {error_msg}')
            raise CommandError('Restore failed. Check the error message above.')

    def _restore_sqlite(self, backup_path):
        """Restore SQLite database by copying backup file."""
        db_file = Path(settings.DATABASES['default']['NAME'])

        if not db_file.exists():
            raise CommandError(f'Current SQLite database not found: {db_file}')

        self.stdout.write(f'Restoring SQLite database from {backup_path}...')
        self.stdout.write(f'Current database will be overwritten: {db_file}')

        safety_backup = None
        try:
            safety_backup = self._create_safety_backup()
            self.stdout.write(f'Safety backup created: {safety_backup}')
        except CommandError as exc:
            self.stderr.write(f'Warning: could not create safety backup: {exc}')

        try:
            shutil.copy2(backup_path, db_file)
        except OSError as exc:
            if safety_backup and safety_backup.exists():
                self.stderr.write(
                    f'Restore failed: {exc}\n'
                    f'A safety backup is available at: {safety_backup}'
                )
            raise CommandError(f'Restore failed: {exc}') from exc

        size = db_file.stat().st_size / 1024 / 1024
        self.stdout.write(f'Restore complete: {db_file} ({size:.1f} MB)')

    def _create_safety_backup(self):
        """Create a safety backup of the current database before restore."""
        output_dir = settings.BASE_DIR / 'backups'
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        engine = settings.DATABASES['default'].get('ENGINE', '')

        if 'postgresql' in engine:
            safety_path = output_dir / f'pre_restore_backup_{timestamp}.sql'
            config = settings.DATABASES['default']
            env = {
                **subprocess.os.environ,
                'PGDATABASE': config['NAME'],
                'PGUSER': config.get('USER', ''),
                'PGPASSWORD': config.get('PASSWORD', ''),
                'PGHOST': config.get('HOST', 'localhost'),
                'PGPORT': str(config.get('PORT', '5432')),
            }
            cmd = ['pg_dump', '--format=plain', '--no-owner', '--no-acl']
            with open(safety_path, 'wb') as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, env=env)
            if result.returncode != 0:
                raise CommandError(f'Safety backup failed: {result.stderr.decode()}')
        elif 'sqlite' in engine:
            db_file = Path(settings.DATABASES['default']['NAME'])
            safety_path = output_dir / f'pre_restore_backup_{timestamp}.sqlite3'
            shutil.copy2(db_file, safety_path)
        else:
            raise CommandError(f'Unsupported engine for safety backup: {engine}')

        return safety_path
