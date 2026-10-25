from pathlib import Path
from django.conf import settings
from django.db import transaction
from .catalog import MAPPING, seed_programs, territory_kind
from .models import Program, Indicator, Territory, Period, Dimension, DimensionValue, Observation, SourceFile, ImportRun
from .sdmx import DataError

def import_documents(documents, assignments=None):
    assignments=assignments or {}
    run=ImportRun.objects.create(filenames=[d.filename for d in documents])
    try:
        with transaction.atomic():
            seed_programs()
            for d in documents:
                slug=assignments.get(d.sha256,MAPPING.get(d.file_id,''))
                try: program=Program.objects.get(slug=slug)
                except Program.DoesNotExist: raise DataError('Выберите программу для '+d.filename)
                indicator,_=Indicator.objects.update_or_create(file_id=d.file_id,defaults={'program':program,'metadata_id':d.metadata_id,'name':d.name,'unit':d.unit,'methodology':d.metadata['methodology'],'organization':d.metadata['organization'],'forms':d.metadata['forms'],'metadata':d.metadata})
                sourcepath='sources/'+d.sha256+'.sdmx'
                target=Path(settings.MEDIA_ROOT)/sourcepath
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists(): target.write_bytes(d.content)
                source,_=SourceFile.objects.get_or_create(sha256=d.sha256,defaults={'filename':d.filename,'original_path':sourcepath,'size':len(d.content),'header_id':d.header_id,'dataset_id':d.dataset_id,'prepared':d.metadata['prepared'],'metadata':d.metadata})
                for code,vs in d.metadata['dimension_values'].items():
                    dim,_=Dimension.objects.update_or_create(indicator=indicator,code=code,defaults={'name':d.dimension_names.get(code,code),'role':'attribute' if code in d.metadata['attributes'] else 'key'})
                    for v in vs:DimensionValue.objects.update_or_create(dimension=dim,code=v,defaults={'label':d.codelists.get(code,{}).get(v,v)})
                territories={}; periods={}
                for row in d.rows:
                    code=row['territory']
                    if code not in territories:
                        territories[code],_=Territory.objects.update_or_create(code=code,defaults={'name':row['territory_name'],'kind':territory_kind(code,row['territory_name'])})
                    pc=row['period']
                    if pc not in periods:periods[pc],_=Period.objects.get_or_create(code=pc,defaults={'label':row['period_label'],'year':row['year'],'order':pc[:4]+('-00' if len(pc)==4 else pc[4:])})
                existing={(o.territory.code,o.period.code,o.dimension_key):o for o in Observation.objects.filter(indicator=indicator).select_related('territory','period')}
                counts={'added':0,'updated':0,'skipped':0,'errors':0}
                for row in d.rows:
                    key=(row['territory'],row['period'],row['dimension_key'])
                    payload={k:row[k] for k in ['dimensions','dimension_labels','numeric_text','raw_value','status','attributes']}
                    old=existing.get(key)
                    if old is None:
                        old=Observation.objects.create(indicator=indicator,territory=territories[row['territory']],period=periods[row['period']],dimension_key=row['dimension_key'],source=source,last_import=run,**payload)
                        existing[key]=old; counts['added']+=1
                    elif all(getattr(old,k)==v for k,v in payload.items()):counts['skipped']+=1
                    else:
                        for k,v in payload.items():setattr(old,k,v)
                        old.source=source;old.last_import=run;old.save();counts['updated']+=1
                for k in ('added','updated','skipped'):setattr(run,k,getattr(run,k)+counts[k])
                run.details.append({'file':d.filename,'file_id':d.file_id,'header_id':d.header_id,'dataset_id':d.dataset_id,'program':slug,**counts})
            run.status='success';run.save()
    except Exception as e:
        run.refresh_from_db();run.status='error';run.errors=1;run.message=str(e);run.save()
        raise
    return run
