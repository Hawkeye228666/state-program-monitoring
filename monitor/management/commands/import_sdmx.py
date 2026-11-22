from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from monitor.sdmx import unpack_uploads, DataError
from monitor.importer import import_documents
class Command(BaseCommand):
    help='Импорт общего ZIP, вложенных ZIP или SDMX/XML без дубликатов'
    def add_arguments(self,parser):
        parser.add_argument('files',nargs='+')
        parser.add_argument('--program')
        parser.add_argument('--manifest')
        parser.add_argument('--profile',type=int)
    def handle(self,*args,**options):
        try:
            if options['program'] or options['manifest']:
                from monitor.bulk_import import import_sources,load_manifest
                from monitor.streaming import extract_sources,metadata
                from monitor.models import MappingProfile,ImportRun
                from django.db import connection
                if options['manifest']:
                    import hashlib,json
                    expected=json.loads(Path(options['manifest']).read_text(encoding='utf-8')).get('archive_sha256')
                    if expected:
                        if len(options['files'])!=1:raise DataError('Manifest с контрольной суммой требует один исходный архив.')
                        h=hashlib.sha256()
                        with Path(options['files'][0]).open('rb') as stream:
                            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
                        if h.hexdigest()!=expected:raise DataError('SHA256 архива не совпадает с manifest.')
                sources=list(extract_sources(options['files']))
                assignments=load_manifest(options['manifest']) if options['manifest'] else {metadata(s)['file_id']:options['program'] for s in sources}
                profile=MappingProfile.objects.get(pk=options['profile']) if options['profile'] else None
                run=ImportRun.objects.create(filenames=[s.filename for s in sources])
                tracker=connection.copy(alias='cli_import_progress')
                def progress(event):
                    import json
                    with tracker.cursor() as cursor:cursor.execute('UPDATE monitor_importrun SET progress=%s::jsonb WHERE id=%s',[json.dumps(event),run.pk])
                    self.stdout.write(str(event))
                try:run=import_sources(sources,assignments,profile=profile,run=run,report=progress)
                finally:tracker.close()
                if options['manifest']:
                    import json
                    from monitor.models import RelatedSeries,Indicator
                    for link in json.loads(Path(options['manifest']).read_text(encoding='utf-8')).get('relationships',[]):
                        RelatedSeries.objects.get_or_create(previous=Indicator.objects.get(file_id=link['previous']),following=Indicator.objects.get(file_id=link['following']),defaults={'explanation':link['explanation']})
                self.stdout.write(f'Run {run.pk}: raw={run.raw_count}, unique={run.unique_count}, added={run.added}, updated={run.updated}, skipped={run.skipped}, rejected={run.rejected}')
                return
            docs=unpack_uploads([(Path(p).name,Path(p).read_bytes()) for p in options['files']])
            run=import_documents(docs)
        except (DataError,OSError) as e:raise CommandError(str(e))
        for d in run.details:self.stdout.write(str(d))
        self.stdout.write(self.style.SUCCESS(f'Добавлено: {run.added}; обновлено: {run.updated}; пропущено: {run.skipped}; ошибок: {run.errors}'))
