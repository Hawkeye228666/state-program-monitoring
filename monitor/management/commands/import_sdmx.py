from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from monitor.sdmx import unpack_uploads, DataError
from monitor.importer import import_documents
class Command(BaseCommand):
    help='Импорт общего ZIP, вложенных ZIP или SDMX/XML без дубликатов'
    def add_arguments(self,parser): parser.add_argument('files',nargs='+')
    def handle(self,*args,**options):
        try:
            docs=unpack_uploads([(Path(p).name,Path(p).read_bytes()) for p in options['files']])
            run=import_documents(docs)
        except (DataError,OSError) as e:raise CommandError(str(e))
        for d in run.details:self.stdout.write(str(d))
        self.stdout.write(self.style.SUCCESS(f'Добавлено: {run.added}; обновлено: {run.updated}; пропущено: {run.skipped}; ошибок: {run.errors}'))
