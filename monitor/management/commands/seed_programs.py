from django.core.management.base import BaseCommand
from monitor.catalog import seed_programs
class Command(BaseCommand):
    def handle(self,*args,**options):seed_programs()
