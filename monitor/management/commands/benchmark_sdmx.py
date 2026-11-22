"""Reproducible full-volume measurements against the configured PostgreSQL."""
import hashlib,json,platform,time
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.db import connection
from monitor.bulk_import import import_sources,load_manifest
from monitor.streaming import extract_sources
from monitor.models import Observation
from monitor.catalog import MAPPING

class Command(BaseCommand):
    help='Полный импорт/повтор и измерения; только настроенный PostgreSQL, без очистки БД.'
    def add_arguments(self,parser):
        parser.add_argument('archive');parser.add_argument('--manifest',required=True)
        parser.add_argument('--report',required=True);parser.add_argument('--repeat',action='store_true')
    def handle(self,*args,**options):
        path=Path(options['archive']);manifest=json.loads(Path(options['manifest']).read_text(encoding='utf-8'))
        hasher=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):hasher.update(chunk)
        if manifest.get('archive_sha256') and hasher.hexdigest()!=manifest['archive_sha256']:raise CommandError('SHA256 архива не совпадает с manifest.')
        before={fid:Observation.objects.filter(indicator__file_id=fid).count() for fid in MAPPING}
        started=time.perf_counter();sources=list(extract_sources([path]))
        proof={'archive_sha256':hasher.hexdigest(),'expanded_xml_bytes':sum(s.size for s in sources),'files':len(sources),'extraction_seconds':time.perf_counter()-started,'python':platform.python_version(),'legacy_before':before,'runs':[]}
        try:
            for _ in range(2 if options['repeat'] else 1):
                run=import_sources(sources,load_manifest(options['manifest']),report=lambda event:self.stdout.write(json.dumps(event,ensure_ascii=False)))
                proof['runs'].append({k:getattr(run,k) for k in ('id','status','raw_count','unique_count','added','updated','skipped','rejected','progress','details')})
            proof['legacy_after']={fid:Observation.objects.filter(indicator__file_id=fid).count() for fid in MAPPING}
            if proof['legacy_after']!=before:raise CommandError('Изменилось количество прежних показателей.')
            with connection.cursor() as c:
                c.execute('SELECT version()');proof['postgresql']=c.fetchone()[0]
                c.execute('ANALYZE monitor_observation')
            proof['queries']={}
            for name,qs in [('combined_dimensions',Observation.objects.filter(indicator__file_id='58699',dimensions__contains={'s_OKVED2':'C','s_OKFS':'61'})),('first_page',Observation.objects.filter(indicator__file_id='58699',dimensions__contains={'s_OKVED2':'C'}).order_by('pk'))]:
                start=time.perf_counter();value=qs.count() if name=='combined_dimensions' else list(qs.values_list('pk',flat=True)[:50])
                proof['queries'][name]={'seconds':time.perf_counter()-start,'count':value if isinstance(value,int) else len(value)}
            proof['status']='success'
        finally:
            target=Path(options['report']);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
