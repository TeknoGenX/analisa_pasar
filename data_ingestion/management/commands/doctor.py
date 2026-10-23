#data_ingestion/management/commands/doctor.py
from secrets import token_urlsafe

from celery.exceptions import OperationalError as CeleryOperationalError
from django.conf import settings
from django.core import checks
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections
from redis.exceptions import RedisError

from config.celery import app as celery_app


class Command(BaseCommand):
    help = 'Memeriksa konfigurasi Django serta koneksi database, cache, dan broker Celery'

    def handle(self, *args, **options):
        checks_ok = self._check_django()
        database_ok = self._check_database()
        cache_ok = self._check_cache()
        broker_ok = self._check_broker()

        if not all((checks_ok, database_ok, cache_ok, broker_ok)):
            raise CommandError('Satu atau lebih pemeriksaan gagal; lihat rincian di atas.')

        self.stdout.write(self.style.SUCCESS('Semua pemeriksaan lulus.'))

    def _check_django(self):
        issues = checks.run_checks()
        errors = [issue for issue in issues if isinstance(issue, checks.Error)]

        if errors:
            self.stderr.write(self.style.ERROR(f'Django: {len(errors)} error ditemukan'))
            for issue in issues:
                self.stderr.write(f'  {issue.level_tag}: {issue.msg}')
            return False

        self.stdout.write(self.style.SUCCESS('Django: pemeriksaan konfigurasi lulus'))
        for issue in issues:
            self.stderr.write(self.style.WARNING(f'  {issue.level_tag}: {issue.msg}'))
        return True

    def _check_database(self):
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except DatabaseError as exc:
            self.stderr.write(self.style.ERROR(f'Database ({settings.DATABASES["default"]["ENGINE"]}): gagal — {exc}'))
            return False

        self.stdout.write(self.style.SUCCESS('Database: koneksi lulus'))
        return True

    def _check_cache(self):
        key = f'manage-doctor:{token_urlsafe(12)}'
        try:
            cache.set(key, 'ok', timeout=10)
            cache_ok = cache.get(key) == 'ok'
            cache.delete(key)
        except RedisError as exc:
            self.stderr.write(self.style.ERROR(f'Cache: gagal — {exc}'))
            return False

        if not cache_ok:
            self.stderr.write(self.style.ERROR('Cache: nilai uji tidak dapat dibaca kembali'))
            return False

        self.stdout.write(self.style.SUCCESS('Cache: tulis/baca lulus'))
        return True

    def _check_broker(self):
        try:
            with celery_app.connection_for_write() as connection:
                connection.ensure_connection(max_retries=0, timeout=2)
        except CeleryOperationalError as exc:
            self.stderr.write(self.style.ERROR(f'Celery broker: gagal — {exc}'))
            return False

        self.stdout.write(self.style.SUCCESS('Celery broker: koneksi lulus'))
        return True
