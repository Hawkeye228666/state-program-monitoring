"""Versioned read-only session-authenticated API; Decimal values are JSON strings."""
from django.core.paginator import Paginator, EmptyPage
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.shortcuts import get_object_or_404
from .access import api_reader
from .dimensions import dimension_info
from .models import Indicator, Program
from .queries import select_rows
from .sdmx import DataError


def source_metadata(source):
    return {'id': source.pk, 'filename': source.filename, 'sha256': source.sha256,
            'header_id': source.header_id, 'dataset_id': source.dataset_id,
            'prepared': source.prepared, 'imported_at': source.created.isoformat()}


def observation_data(o):
    return {'id': o.pk, 'indicator': o.indicator.file_id,
            'territory': {'code': o.territory.code, 'name': o.territory.name, 'level': o.territory.kind},
            'period': {'code': o.period.code, 'label': o.period.label, 'year': o.period.year,
                       'type': 'quarter' if '-Q' in o.period.code else 'year'},
            'value': o.numeric_text, 'raw_value': o.raw_value,
            'unit': o.dimensions.get('EI', o.indicator.unit),
            'dimensions': o.dimensions, 'dimension_labels': o.dimension_labels,
            'okfs': dimension_info(o), 'status': o.status, 'attributes': o.attributes,
            'source': source_metadata(o.source), 'last_import_id': o.last_import_id}


def paginated(request, items, serialize):
    try:
        size = int(request.GET.get('page_size', '50'))
        number = int(request.GET.get('page', '1'))
        if not 1 <= size <= 500 or number < 1:
            raise ValueError
        paginator = Paginator(items, size)
        page = paginator.page(number)
    except (ValueError, EmptyPage):
        return JsonResponse({'error': 'page должен существовать, page_size от 1 до 500.'}, status=400)
    def url(n):
        if n is None: return None
        params = request.GET.copy(); params['page'] = n
        return request.path + '?' + params.urlencode()
    return JsonResponse({'api_version': '1', 'count': paginator.count, 'page': page.number,
                         'page_size': size, 'pages': paginator.num_pages,
                         'next': url(page.next_page_number() if page.has_next() else None),
                         'previous': url(page.previous_page_number() if page.has_previous() else None),
                         'results': [serialize(o) for o in page]}, json_dumps_params={'ensure_ascii': False})


@api_reader
@require_GET
def indicators(request):
    qs = Indicator.objects.select_related('program').order_by('file_id')
    if request.GET.get('program'): qs = qs.filter(program__slug=request.GET['program'])
    if request.GET.getlist('indicator'): qs = qs.filter(file_id__in=request.GET.getlist('indicator'))
    def serialize(i):
        # Portable across PostgreSQL and SQLite, bounded to the actual source records.
        from .models import SourceFile
        sources = SourceFile.objects.filter(observation__indicator=i).distinct().order_by('pk')
        return {'id': i.file_id, 'name': i.name, 'unit': i.unit, 'program': i.program.slug,
                'methodology': i.methodology, 'organization': i.organization,
                'observations': i.observations.count(), 'sources': [source_metadata(s) for s in sources],
                'dimensions': [{'code': d.code, 'name': d.name} for d in i.dimensions.order_by('code')]}
    return paginated(request, qs, serialize)


@api_reader
@require_GET
def observations(request):
    program = get_object_or_404(Program, slug=request.GET.get('program', 'housing'))
    try:
        rows, _, _ = select_rows(program, request.GET)
    except DataError as e:
        return JsonResponse({'error': str(e)}, status=400)
    return paginated(request, rows, observation_data)
