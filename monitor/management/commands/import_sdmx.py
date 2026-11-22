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
                from monitor.models import MappingProfile
                sources=list(extract_sources(options['files']))
                assignments=load_manifest(options['manifest']) if options['manifest'] else {metadata(s)['file_id']:options['program'] for s in sources}
                profile=MappingProfile.objects.get(pk=options['profile']) if options['profile'] else None
                run=import_sources(sources,assignments,profile=profile,report=lambda event:self.stdout.write(str(event)))
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
