from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.core.management import call_command
from monitor.models import Observation
class Command(BaseCommand):
    help='Prepare PostgreSQL schema/roles; explicitly load original SDMX with --load-data.'
    def add_arguments(self,parser):parser.add_argument('--load-data',action='store_true')
    def handle(self,*args,**options):
        call_command('wait_for_db');call_command('migrate',interactive=False);call_command('setup_roles')
        if options['load_data']:
            files=sorted((settings.BASE_DIR/'data/sources').glob('*.sdmx'))
            if len(files)!=6:raise CommandError('Expected six original SDMX files.')
            call_command('import_sdmx',*[str(f) for f in files])
            self.stdout.write('Observations: '+str(Observation.objects.count()))
