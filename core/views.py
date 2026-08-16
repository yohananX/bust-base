from django.db import connection
from django.http import JsonResponse


def health(request):
    """Liveness/readiness probe for deployment platforms."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        return JsonResponse({'status': 'ok', 'database': 'ok'})
    except Exception:
        return JsonResponse({'status': 'degraded', 'database': 'error'}, status=500)