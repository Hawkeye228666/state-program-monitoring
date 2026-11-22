"""Durable preview/approval/import queue. Run with `manage.py process_imports`.

Paths never come from an HTTP parameter; jobs live under their UUID in MEDIA_ROOT.
The worker holds a PostgreSQL session advisory lock; a dead worker's uncommitted
publication rolls back and its job is reset on the next worker start.
"""
from pathlib import Path
from django.conf import settings
from django.db import connection,transaction
from .models import ImportJob,ImportRun,MappingProfile,Indicator
from .streaming import Source,extract_sources,metadata,rows,validate_profile,digest
from .bulk_import import import_sources

def process(job):
    try:
        if job.state=='preview_running':
            sources=list(extract_sources(job.payload['uploads']));preview=[]
            for source in sources:
                info=metadata(source);rules=validate_profile(info,job.profile.rules if job.profile else None)
                count=0;sample=[];periods={};states={}
                for row in rows(source,info,rules):
                    count+=1;pc=row['period']['code'];periods[pc]=periods.get(pc,0)+1
                    for code,state in row['dimension_states'].items():
                        counts=states.setdefault(code,{});counts[state]=counts.get(state,0)+1
                    if len(sample)<3:sample.append({'territory':row['territory'],'period':pc,'dimensions':row['dimensions'],'value':row['raw_value']})
                    if count%100000==0:
                        job.message=f'{source.filename}: {count} наблюдений проверено';job.save(update_fields=['message'])
                preview.append({'filename':source.filename,'sha256':source.sha256,'size':source.size,'file_id':info['file_id'],'name':info['name'],'unit':info['unit'],'count':count,'sample':sample,'periods':periods,'states':states,'rules':rules,'metadata':{k:info['metadata'].get(k) for k in ('methodology','organization','forms','comment','classifiers','diagnostics')},'diagnostics':info['metadata'].get('diagnostics',[]),'default':Indicator.objects.filter(file_id=info['file_id']).values_list('program__slug',flat=True).first() or job.payload.get('program','')})
                job.preview=preview;job.save(update_fields=['preview'])
            job.state='awaiting_approval';job.message='Проверьте программу и сопоставление полей. Данные ещё не опубликованы.';job.save()
        else:
            sources=[Source(p['filename'],Path(settings.MEDIA_ROOT)/'sources'/(p['sha256']+'.sdmx'),p['sha256'],p['size']) for p in job.preview]
            run=ImportRun.objects.create(actor=job.actor,filenames=[s.filename for s in sources]);job.run=run;job.save(update_fields=['run'])
            # Separate autocommit connection makes progress visible while publication is atomic.
            progress=connection.copy(alias='import_progress')
            def report(event):
                import json
                with progress.cursor() as c:c.execute('UPDATE monitor_importrun SET progress=%s::jsonb WHERE id=%s',[json.dumps(event),run.pk])
            try:import_sources(sources,job.assignments,actor=job.actor,profile=job.profile,run=run,report=report)
            finally:progress.close()
            job.state='success';job.message='Импорт опубликован целиком.';job.save()
    except Exception as error:
        job.state='error';job.message=str(error);job.save()

def next_job():
    with transaction.atomic():
        job=ImportJob.objects.select_for_update(skip_locked=True).filter(state__in=['preview_pending','queued']).order_by('created').first()
        if job:
            job.state='preview_running' if job.state=='preview_pending' else 'importing';job.save(update_fields=['state'])
    return job
