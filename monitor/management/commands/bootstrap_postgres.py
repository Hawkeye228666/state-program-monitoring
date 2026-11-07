from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand,CommandError
from django.core.management import call_command
from monitor.models import Observation
class Command(BaseCommand):
    help='Prepare PostgreSQL schema/roles; explicitly load original SDMX with --load-data.'
    def add_arguments(self,parser):
        group=parser.add_mutually_exclusive_group()
        group.add_argument('--load-data',action='store_true')
        group.add_argument('--load-if-empty',action='store_true')
        parser.add_argument('--create-admin',action='store_true')
    def handle(self,*args,**options):
        call_command('wait_for_db');call_command('migrate',interactive=False);call_command('setup_roles')
        if options['load_data'] or (options['load_if_empty'] and not Observation.objects.exists()):
            files=sorted((settings.BASE_DIR/'data/sources').glob('*.sdmx'))
            if len(files)!=6:raise CommandError('Expected six original SDMX files.')
            call_command('import_sdmx',*[str(f) for f in files])
            self.stdout.write('Observations: '+str(Observation.objects.count()))
        if options['create_admin'] and not get_user_model().objects.filter(is_superuser=True,is_active=True).exists():
            self.stdout.write('First start: create your administrator account. Password input is hidden.')
            call_command('createsuperuser',interactive=True)
            if not get_user_model().objects.filter(is_superuser=True,is_active=True).exists():
                raise CommandError('Administrator was not created. Run the launcher again to finish setup.')
