"""COPY to transaction-local staging; publish the entire run atomically.

Malformed/conflicting data rolls back sources, dictionaries and observations together.
ImportRun is committed before staging and records a failure outside that transaction.
"""
import json,time
from pathlib import Path
from django.db import connection,transaction
from django.utils import timezone
from .models import Program,Indicator,Territory,Period,Dimension,DimensionValue,SourceFile,ImportRun,ClassifierSnapshot,MappingProfile,RelatedSeries
from .catalog import territory_kind
from .streaming import extract_sources,metadata,rows,encoded,digest,validate_profile
from .sdmx import DataError

def peak_rss():
    """Process high-water RSS, not server memory; no optional dependencies."""
    import os
    if os.name!='nt':
        import resource,sys
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value if sys.platform=='darwin' else value*1024
    import ctypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(x,ctypes.c_size_t) for x in ['peak','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile']]
    memory=Counters();memory.cb=ctypes.sizeof(memory)
    ctypes.windll.kernel32.GetCurrentProcess.restype=ctypes.c_void_p
    query=ctypes.windll.psapi.GetProcessMemoryInfo;query.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
    if not query(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(memory),memory.cb):return None
    return memory.peak

def import_sources(sources,assignments,actor=None,profile=None,run=None,report=None):
    run=run or ImportRun.objects.create(actor=actor)
    started=time.perf_counter();details=[];raw=0;periods={};territories={}
    # Cooperative writer lock covers bulk and regular loaders (see importer.py).
    try:
        with transaction.atomic(),connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(7291363)')
            cursor.execute("SET LOCAL work_mem='64MB'")
            cursor.execute('DROP TABLE IF EXISTS pg_temp.emiss_duplicates,pg_temp.emiss_unique,pg_temp.emiss_stage')
            cursor.execute('CREATE TEMP TABLE emiss_stage (seq bigserial, file_number integer, indicator_id bigint, territory_code text, period_code text, dimension_key varchar(64), dimensions jsonb, dimension_labels jsonb, numeric_value numeric(80,30), raw_value text, status jsonb, attributes jsonb, dimension_states jsonb, source_id bigint) ON COMMIT DROP')
            for file_number,source in enumerate(sources):
                info=metadata(source);fid=info['file_id'];slug=assignments.get(fid) or assignments.get(source.sha256)
                if not slug:raise DataError('Нужно явное назначение программы для ID '+fid)
                program=Program.objects.get(slug=slug)
                indicator,created=Indicator.objects.get_or_create(file_id=fid,defaults={'program':program,'metadata_id':fid,'name':info['name'],'unit':info['unit'],'methodology':info['metadata']['methodology'],'organization':info['metadata']['organization'],'forms':info['metadata']['forms'],'metadata':info['metadata']})
                if indicator.program_id!=program.pk:raise DataError('Показатель '+fid+' уже относится к '+indicator.program.slug+'. Перенос требует отдельного изменения метаданных.')
                rules=validate_profile(info,profile.rules if profile else None)
                if profile and not profile.confirmed:raise DataError('Сначала подтвердите профиль сопоставления.')
                if not profile:MappingProfile.objects.get_or_create(name='ЕМИСС '+fid+' '+digest(rules)[:12],defaults={'rules':rules,'confirmed':True})
                stored,_=SourceFile.objects.get_or_create(sha256=source.sha256,defaults={'filename':source.filename,'original_path':'sources/'+source.sha256+'.sdmx','size':source.size,'header_id':info['header_id'],'dataset_id':info['dataset_id'],'metadata':info['metadata'],'prepared':info['metadata'].get('prepared','')})
                if info['metadata'].get('diagnostics') and stored.metadata.get('diagnostics')!=info['metadata']['diagnostics']:
                    stored.metadata['diagnostics']=info['metadata']['diagnostics'];stored.save(update_fields=['metadata'])
                for code,codes in info['codelists'].items():
                    ClassifierSnapshot.objects.get_or_create(source=stored,concept=code,defaults={'identity':code.removeprefix('s_'),'digest':digest(codes),'codes':codes})
                observed={};counts=0;sample=[];windows={}
                # COPY accepts text JSON and decimal strings without float conversion.
                with cursor.copy('COPY emiss_stage (file_number,indicator_id,territory_code,period_code,dimension_key,dimensions,dimension_labels,numeric_value,raw_value,status,attributes,dimension_states,source_id) FROM STDIN') as copy:
                    for row in rows(source,info,rules):
                        pc=row['period']['code'];periods.setdefault(pc,row['period']);territories.setdefault(row['territory'],row['territory_name'])
                        copy.write_row((file_number,indicator.pk,row['territory'],pc,row['dimension_key'],encoded(row['dimensions']),encoded(row['dimension_labels']),row['numeric_value'],row['raw_value'],encoded(row['status']),encoded(row['attributes']),encoded(row['dimension_states']),stored.pk))
                        counts+=1;raw+=1;windows[pc]=windows.get(pc,0)+1
                        for code,value in row['dimensions'].items():observed.setdefault(code,set()).add(value)
                        if len(sample)<3:sample.append({'territory':row['territory'],'period':pc,'dimensions':row['dimensions'],'value':row['raw_value']})
                        if counts%100000==0:
                            if report:report({'phase':'staging','file':source.filename,'raw':raw,'file_rows':counts})
                if not counts:raise DataError('Нет наблюдений: '+source.filename)
                for code,vs in observed.items():
                    dim,_=Dimension.objects.get_or_create(indicator=indicator,code=code,defaults={'name':info['names'].get(code,code)})
                    DimensionValue.objects.bulk_create([DimensionValue(dimension=dim,code=v,label=info['codelists'].get(code,{}).get(v,v)) for v in vs],ignore_conflicts=True,batch_size=1000)
                item={'file':source.filename,'sha256':source.sha256,'file_id':fid,'program':slug,'raw':counts,'periods':windows,'sample':sample,'bytes':source.size}
                details.append(item)
                if report:report({'phase':'staged','raw':raw,'files':len(details),'last_file':item})
            Territory.objects.bulk_create([Territory(code=c,name=n,kind=territory_kind(c,n)) for c,n in territories.items()],ignore_conflicts=True,batch_size=1000)
            Period.objects.bulk_create([Period(**value) for value in periods.values()],ignore_conflicts=True,batch_size=1000)
            cursor.execute('ANALYZE emiss_stage')
            if report:report({'phase':'validating','raw':raw,'files':len(details)})
            cursor.execute('''CREATE TEMP TABLE emiss_duplicates ON COMMIT DROP AS SELECT indicator_id,territory_code,period_code,dimension_key,min(seq) AS winner
                FROM emiss_stage GROUP BY 1,2,3,4 HAVING count(*)>1''')
            cursor.execute('SELECT count(*) FROM emiss_duplicates');duplicate_groups=cursor.fetchone()[0]
            if report:report({'phase':'checking_conflicts','raw':raw,'duplicate_groups':duplicate_groups})
            cursor.execute('''SELECT s.indicator_id,s.territory_code,s.period_code,s.dimension_key FROM emiss_stage s JOIN emiss_duplicates d
                USING (indicator_id,territory_code,period_code,dimension_key) GROUP BY 1,2,3,4
                HAVING count(DISTINCT (numeric_value,raw_value,status,attributes,dimensions,dimension_labels,dimension_states))>1 LIMIT 1''')
            if cursor.fetchone():raise DataError('Конфликтующие дубликаты полного ключа; публикация отменена целиком.')
            if report:report({'phase':'resolving_keys','raw':raw,'files':len(details)})
            if duplicate_groups:
                cursor.execute('''DELETE FROM emiss_stage s USING emiss_duplicates d
                    WHERE (s.indicator_id,s.territory_code,s.period_code,s.dimension_key)=(d.indicator_id,d.territory_code,d.period_code,d.dimension_key) AND s.seq<>d.winner''')
            cursor.execute('''CREATE TEMP TABLE emiss_unique ON COMMIT DROP AS
                SELECT s.*,t.id AS territory_id,p.id AS period_id FROM emiss_stage s
                JOIN monitor_territory t ON t.code=s.territory_code JOIN monitor_period p ON p.code=s.period_code''')
            cursor.execute('ANALYZE emiss_unique')
            fields='numeric_value,raw_value,dimensions,dimension_labels,status,attributes,dimension_states'.split(',')
            changed=' OR '.join('o.'+f+' IS DISTINCT FROM s.'+f for f in fields)
            cursor.execute('''SELECT count(*),count(*) FILTER (WHERE o.id IS NULL),count(*) FILTER (WHERE o.id IS NOT NULL AND ('''+changed+'''))
                FROM emiss_unique s LEFT JOIN monitor_observation o ON
                (o.indicator_id,o.territory_id,o.period_id,o.dimension_key)=(s.indicator_id,s.territory_id,s.period_id,s.dimension_key)''')
            unique,added,updated=cursor.fetchone();skipped=unique-added-updated
            cursor.execute('''SELECT s.file_number,count(*),count(*) FILTER (WHERE o.id IS NULL),count(*) FILTER (WHERE o.id IS NOT NULL AND ('''+changed+'''))
                FROM emiss_unique s LEFT JOIN monitor_observation o ON
                (o.indicator_id,o.territory_id,o.period_id,o.dimension_key)=(s.indicator_id,s.territory_id,s.period_id,s.dimension_key) GROUP BY s.file_number''')
            dispositions={sid:(u,a,v) for sid,u,a,v in cursor.fetchall()}
            for file_number,item in enumerate(details):
                u,a,v=dispositions.get(file_number,(0,0,0));item.update(unique=u,added=a,updated=v,skipped=u-a-v,rejected=0,duplicates=item['raw']-u)
            if report:report({'phase':'publishing','raw':raw,'unique':unique,'added':added,'updated':updated,'skipped':skipped})
            cursor.execute('''INSERT INTO monitor_observation (indicator_id,territory_id,period_id,dimension_key,dimensions,dimension_labels,numeric_value,raw_value,status,attributes,dimension_states,source_id,last_import_id)
                SELECT indicator_id,territory_id,period_id,dimension_key,dimensions,dimension_labels,numeric_value,raw_value,status,attributes,dimension_states,source_id,%s FROM emiss_unique
                ON CONFLICT (indicator_id,territory_id,period_id,dimension_key) DO UPDATE SET '''+
                ','.join(f+'=EXCLUDED.'+f for f in fields+['source_id','last_import_id'])+' WHERE '+
                ' OR '.join('monitor_observation.'+f+' IS DISTINCT FROM EXCLUDED.'+f for f in fields),[run.pk])
            cursor.execute('ANALYZE monitor_observation')
            run.status='success';run.raw_count=raw;run.unique_count=unique;run.added=added;run.updated=updated;run.skipped=skipped;run.details=details;run.filenames=[item['file'] for item in details]
            run.progress={'phase':'complete','seconds':round(time.perf_counter()-started,3),'duplicate_raw':raw-unique,'peak_process_rss_bytes':peak_rss()};run.save()
    except BaseException as error:
        run.refresh_from_db();run.status='error';run.errors=1;run.raw_count=raw;run.rejected=raw;run.details=details;run.message=str(error) or type(error).__name__;run.progress={'phase':'rolled_back','seconds':round(time.perf_counter()-started,3)};run.save()
        raise
    return run

def load_manifest(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    for entry in data.get('programs',[]):Program.objects.get_or_create(slug=entry['slug'],defaults={k:v for k,v in entry.items() if k!='slug'})
    return data['assignments']
