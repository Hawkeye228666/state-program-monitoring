"""Demo roles use Django permissions. External corporate SSO is a separate project."""
from functools import wraps
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse


def reader(view):
    return login_required(permission_required('monitor.view_observation', raise_exception=True)(view))


def operator(view):
    return login_required(permission_required('monitor.add_importrun', raise_exception=True)(view))


def api_reader(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Требуется вход в систему.'}, status=401)
        if not request.user.has_perm('monitor.view_observation'):
            return JsonResponse({'error': 'Нет права просмотра наблюдений.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapped
