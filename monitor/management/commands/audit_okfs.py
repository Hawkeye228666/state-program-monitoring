import json
from hashlib import sha256
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from monitor.sdmx import unpack_uploads, DataError
from monitor.okfs_audit import audit_document

class Command(BaseCommand):
    help='Независимый пересчёт всех XML исходного архива: ОКФС, кварталы и контрольные значения (без записи БД)'
    def add_arguments(self,parser):
        parser.add_argument('archive',nargs='?',default=None)
        parser.add_argument('--output')
    def handle(self,*args,**options):
        path=Path(options['archive']) if options['archive'] else next((settings.BASE_DIR/'materials').glob('*.zip'),None)
        if path is None:raise CommandError('Исходный ZIP не найден; укажите путь.')
        try:
            docs=unpack_uploads([(path.name,path.read_bytes())])
            report={'archive':path.name,'archive_sha256':sha256(path.read_bytes()).hexdigest(),'files':[audit_document(d.filename,d.content) for d in sorted(docs,key=lambda d:d.file_id)]}
            report['total_observations']=sum(d['observations'] for d in report['files'])
            payload=json.dumps(report,ensure_ascii=False,indent=2)
            if options['output']:Path(options['output']).write_text(payload+'\n',encoding='utf-8')
            self.stdout.write(payload)
        except (DataError,OSError) as e:raise CommandError(str(e))
