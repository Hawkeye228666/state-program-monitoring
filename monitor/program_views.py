from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required,permission_required
from django.shortcuts import get_object_or_404,render,redirect
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.views.decorators.http import require_http_methods
from .models import Program,ImportJob,MappingProfile
from .program_forms import ProgramForm
from .access import operator
from .streaming import limit,digest

@login_required
@require_http_methods(['GET','POST'])
def program_edit(request,slug=None):
    if not request.user.has_perm('monitor.change_program' if slug else 'monitor.add_program'):raise PermissionDenied
    instance=get_object_or_404(Program,slug=slug) if slug else None
    form=ProgramForm(request.POST or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        program=form.save()
        if request.GET.get('job'):
            try:
                job=ImportJob.objects.get(pk=request.GET['job'],actor=request.user,state='awaiting_approval')
            except (ImportJob.DoesNotExist,ValueError):job=None
            if job:return redirect('import-job',pk=job.pk)
        return redirect('/upload/?program='+program.slug)
    return render(request,'monitor/program_form.html',{'form':form})

@operator
@require_http_methods(['POST'])
def job_upload(request):
    files=request.FILES.getlist('files')
    if not files or sum(f.size for f in files)>limit('MAX_UPLOAD',128*1024**2):return render(request,'monitor/error.html',{'error':'Выберите файлы в пределах SDMX_MAX_UPLOAD.'},status=400)
    program=request.POST.get('program','')
    if program:get_object_or_404(Program,slug=program)
    profile=get_object_or_404(MappingProfile,pk=request.POST['profile'],confirmed=True) if request.POST.get('profile') else None
    job=ImportJob.objects.create(actor=request.user,state='uploading',profile=profile)
    root=Path(settings.MEDIA_ROOT)/'jobs'/str(job.pk);root.mkdir(parents=True)
    uploads=[]
    for index,file in enumerate(files):
        # User filename never becomes an on-disk path.
        suffix=Path(file.name).suffix.lower()
        if suffix not in ('.zip','.xml','.sdmx'):
            job.state='error';job.message='Разрешены ZIP/SDMX/XML.';job.save();return redirect('import-job',pk=job.pk)
        path=root/(str(index)+suffix)
        with path.open('wb') as out:
            for chunk in file.chunks():out.write(chunk)
        uploads.append(str(path))
    job.payload={'uploads':uploads,'program':program};job.state='preview_pending';job.save()
    return redirect('import-job',pk=job.pk)

@operator
@require_http_methods(['GET','POST'])
@transaction.atomic
def job_detail(request,pk):
    job=get_object_or_404(ImportJob.objects.select_for_update() if request.method=='POST' else ImportJob.objects,pk=pk)
    if job.actor_id!=request.user.pk and not request.user.has_perm('monitor.change_importjob'):raise PermissionDenied
    if request.method=='POST' and job.state=='awaiting_approval' and request.POST.get('confirm_mapping')=='yes':
        assignments={p['file_id']:request.POST.get('program_'+p['file_id'],'') for p in job.preview}
        if all(Program.objects.filter(slug=v).exists() for v in assignments.values()):
            # Per-source auto profiles are persisted for review/reuse; unsupported mappings
            # can be configured and confirmed explicitly in Django Admin.
            for p in job.preview:MappingProfile.objects.get_or_create(name='ЕМИСС '+p['file_id']+' '+digest(p['rules'])[:12],defaults={'rules':p['rules'],'confirmed':True})
            job.assignments=assignments;job.state='queued';job.save()
            return redirect('import-job',pk=pk)
    grouped={}
    for item in job.preview:grouped.setdefault(item['file_id'],item)
    return render(request,'monitor/import_job.html',{'job':job,'grouped':grouped.values(),'programs':Program.objects.all()})
