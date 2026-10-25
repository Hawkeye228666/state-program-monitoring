import csv, io, json, time, uuid
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from .models import Program, Indicator, Observation, Territory, Period, Dimension, ImportRun
from .catalog import MAPPING
from .sdmx import DataError, unpack_uploads, MAX_UPLOAD
from .importer import import_documents
from .queries import select_rows, chart_data

def home(request):
    programs=Program.objects.annotate(total=Count('indicators__observations'),indicator_count=Count('indicators',distinct=True)).order_by('slug')
    return render(request,'monitor/home.html',{'programs':programs,'observations':Observation.objects.count(),'territories':Territory.objects.filter(observation__isnull=False).distinct().count(),'indicators':Indicator.objects.count(),'periods':Period.objects.order_by('order'),'recent':ImportRun.objects.first()})
def passport(request,slug):
    p=get_object_or_404(Program,slug=slug);entries=[]
    for i in p.indicators.order_by('file_id'):
        q=i.observations.all()
        entries.append({'indicator':i,'count':q.count(),'territories':q.values('territory').distinct().count(),'periods':Period.objects.filter(observation__indicator=i).distinct().order_by('order'),'source':q.select_related('source').first().source if q.exists() else None,'dimensions':i.dimensions.prefetch_related('values')})
    return render(request,'monitor/passport.html',{'program':p,'entries':entries})
def csv_cell(v):
    v=str(v)
    return "'"+v if v.startswith(('=','+','-','@','\t','\r')) else v

def explore(request):
    p=get_object_or_404(Program,slug=request.GET.get('program','housing'));params=request.GET.copy()
    if params.get('restore')=='1':
        saved=request.session.get('filters_'+p.slug)
        if saved:return redirect('/explore/?'+saved)
    if not any(k in params for k in ('mode','indicator','regions','periods','level','sort','submitted')):params.setlist('regions',['643'])
    if params.get('save')=='1':
        saved=params.copy()
        for k in ('save','page','format'):saved.pop(k,None)
        request.session['filters_'+p.slug]=saved.urlencode();messages.success(request,'Фильтры сохранены в этом браузере.')
    try:rows,chosen,mode=select_rows(p,params)
    except DataError as e:return render(request,'monitor/error.html',{'error':str(e)},status=400)
    chart=chart_data(rows,params.get('bar_period',''));fmt=params.get('format','')
    if fmt=='json':return JsonResponse({'count':len(rows),'rows':[{'indicator':o.indicator.file_id,'territory':o.territory.code,'period':o.period.code,'dimensions':o.dimensions,'value':o.numeric_text,'raw_value':o.raw_value,'status':o.status} for o in rows],'chart':chart},json_dumps_params={'ensure_ascii':False})
    if fmt=='csv':
        buf=io.StringIO(newline='');buf.write('\ufeff');writer=csv.writer(buf,delimiter=';')
        writer.writerow(['Программа','ID показателя','Показатель','Код территории','Территория','Уровень территории','Период','Значение исходное','Значение десятичное','Единица','Множитель','Измерения','Статус','Header/ID','DataSetID','SHA256 источника'])
        for o in rows:writer.writerow([csv_cell(v) for v in [p.name,o.indicator.file_id,o.indicator.name,"'"+o.territory.code,o.territory.name,o.territory.get_kind_display(),o.period.label,o.raw_value,o.numeric_text or '',o.dimensions.get('EI',o.indicator.unit),o.dimensions.get('UNIT_MULT','не указан'),o.dimensions_display,json.dumps(o.status,ensure_ascii=False),o.source.header_id,o.source.dataset_id,o.source.sha256]])
        response=HttpResponse(buf.getvalue(),content_type='text/csv; charset=utf-8');response['Content-Disposition']='attachment; filename="monitoring.csv"';return response
    base=Observation.objects.filter(indicator__program=p);dims=Dimension.objects.filter(indicator__program=p).prefetch_related('values')
    if mode=='one':dims=dims.filter(indicator__file_id=chosen)
    combined={}
    for d in dims:
        entry=combined.setdefault(d.code,{'code':d.code,'name':d.name,'options':{}})
        for v in d.values.all():entry['options'][v.code]=v.label
    fields=[]
    for code,entry in sorted(combined.items()):
        entry['options']=[{'code':c,'label':l,'selected':c in params.getlist('dim_'+code)} for c,l in sorted(entry['options'].items())];fields.append(entry)
    page=Paginator(rows,50).get_page(params.get('page',1));query=params.copy()
    for k in ('page','save','format'):query.pop(k,None)
    query['program']=p.slug;active=[]
    for k in params:
        if k in ('regions','periods','level') or k.startswith('dim_'):
            for v in params.getlist(k):
                if v:active.append(k+': '+v)
    return render(request,'monitor/explore.html',{'program':p,'programs':Program.objects.all(),'indicators':p.indicators.order_by('file_id'),'chosen':chosen,'mode':mode,'regions':[{'code':t.code,'name':t.name,'kind':t.get_kind_display(),'selected':t.code in params.getlist('regions')} for t in Territory.objects.filter(observation__in=base).distinct().order_by('kind','name')],'periods':[{'code':x.code,'label':x.label,'selected':x.code in params.getlist('periods')} for x in Period.objects.filter(observation__in=base).distinct().order_by('order')],'fields':fields,'page':page,'total':len(rows),'chart':chart,'query':query.urlencode(),'active':active,'sort':params.get('sort','territory'),'level':params.get('level',''),'levels':Territory._meta.get_field('kind').choices})

@require_http_methods(['GET','POST'])
def upload(request):
    preview=None
    if request.method=='POST':
        try:
            if request.POST.get('action')=='preview':
                files=request.FILES.getlist('files')
                if not files:raise DataError('Выберите один или несколько файлов.')
                if sum(f.size for f in files)>MAX_UPLOAD:raise DataError('Общий размер загрузки превышает 20 МБ.')
                docs=unpack_uploads([(f.name,f.read()) for f in files]);token=uuid.uuid4().hex;stage=Path(settings.MEDIA_ROOT)/'staging'/token;stage.mkdir(parents=True);manifest=[]
                for n,d in enumerate(docs):
                    (stage/f'{n}.sdmx').write_bytes(d.content)
                    manifest.append({'filename':d.filename,'sha256':d.sha256,'file_id':d.file_id,'name':d.name,'unit':d.unit,'header_id':d.header_id,'dataset_id':d.dataset_id,'observations':len(d.rows),'territories':d.territories,'periods':d.periods,'default':MAPPING.get(d.file_id,''),'dimensions':d.metadata['dimension_values']})
                (stage/'manifest.json').write_text(json.dumps({'created':time.time(),'files':manifest}),encoding='utf-8');request.session['upload_token']=token;preview=manifest
            elif request.POST.get('action')=='confirm':
                token=request.session.get('upload_token')
                if not token or len(token)!=32:raise DataError('Предпросмотр истёк. Загрузите файлы заново.')
                stage=Path(settings.MEDIA_ROOT)/'staging'/token;manifest=json.loads((stage/'manifest.json').read_text(encoding='utf-8'))
                if time.time()-manifest['created']>3600:raise DataError('Предпросмотр хранится один час. Загрузите файлы заново.')
                preview=manifest['files'];assignments={f['sha256']:request.POST.get('program_'+f['sha256'],'') for f in preview}
                if any(not Program.objects.filter(slug=v).exists() for v in assignments.values()):raise DataError('Проверьте программу для каждого файла.')
                try:lock=(stage/'import.lock').open('x');lock.close()
                except FileExistsError:raise DataError('Эта загрузка уже обработана. Для повторного импорта создайте новый предпросмотр.')
                docs=unpack_uploads([(f['filename'],(stage/f'{n}.sdmx').read_bytes()) for n,f in enumerate(preview)])
                if [d.sha256 for d in docs]!=[f['sha256'] for f in preview]:raise DataError('Содержимое предпросмотра изменилось.')
                run=import_documents(docs,assignments);request.session.pop('upload_token',None)
                messages.success(request,f'Импорт № {run.pk}: добавлено {run.added}, обновлено {run.updated}, пропущено {run.skipped}, ошибок {run.errors}.');return redirect('history')
            else:raise DataError('Неизвестное действие.')
        except (DataError,OSError,ValueError) as e:
            messages.error(request,str(e))
            if request.POST.get('action')=='preview':ImportRun.objects.create(status='error',errors=1,message=str(e),filenames=[f.name for f in request.FILES.getlist('files')])
    return render(request,'monitor/upload.html',{'preview':preview,'programs':Program.objects.order_by('slug')})
def history(request):return render(request,'monitor/history.html',{'page':Paginator(ImportRun.objects.all(),15).get_page(request.GET.get('page'))})
