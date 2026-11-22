import hashlib
import json
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from monitor.integrity import canonical, digest
from monitor.models import SourceFile

class Command(BaseCommand):
    help = 'Full ordered row fingerprints for every model and checksum validation of imported source files; no passwords or row contents are printed.'
    def add_arguments(self, parser):
        parser.add_argument('--check-files', action='store_true')
    def handle(self, *args, **options):
        result = {'tables': {}, 'files': {}}
        for model in sorted(apps.get_models(include_auto_created=True), key=lambda m: m._meta.db_table):
            fields = [f.attname for f in model._meta.local_fields]
            hasher=hashlib.sha256();hasher.update(b'[');count=0
            for row in model._base_manager.order_by(model._meta.pk.name).values_list(*fields).iterator(chunk_size=1000):
                if count:hasher.update(b',')
                hasher.update(json.dumps(canonical(row),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8'));count+=1
            hasher.update(b']')
            result['tables'][model._meta.db_table] = {'count': count, 'sha256': hasher.hexdigest()}
        if options['check_files']:
            root = Path(settings.MEDIA_ROOT).resolve()
            for source in SourceFile.objects.order_by('sha256'):
                path = (root / source.original_path).resolve()
                hasher=hashlib.sha256()
                if path.is_relative_to(root) and path.is_file():
                    with path.open('rb') as stream:
                        for chunk in iter(lambda:stream.read(1024*1024),b''):hasher.update(chunk)
                if not path.is_relative_to(root) or not path.is_file() or hasher.hexdigest() != source.sha256:
                    raise CommandError('Source file checksum failed: ' + source.original_path)
                result['files'][source.original_path] = source.sha256
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
