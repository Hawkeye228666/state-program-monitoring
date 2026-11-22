import time
from django.core.management.base import BaseCommand,CommandError
from django.db import connection
from monitor.jobs import next_job,process
from monitor.models import ImportJob,ImportRun

class Command(BaseCommand):
    help='Фоновый обработчик безопасного предпросмотра и подтверждённых импортов.'
    def add_arguments(self,parser):parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(7291364)')
            if not cursor.fetchone()[0]:raise CommandError('Другой обработчик уже работает.')
        try:
            for job in ImportJob.objects.filter(state__in=['preview_running','importing']):
                if job.run_id:ImportRun.objects.filter(pk=job.run_id,status='running').update(status='error',message='Worker interrupted; uncommitted publication rolled back.')
                job.state='preview_pending' if job.state=='preview_running' else 'queued';job.save(update_fields=['state'])
            while True:
                job=next_job()
                if job:process(job)
                elif options['once']:break
                else:time.sleep(2)
                if options['once']:break
        finally:
            with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_unlock(7291364)')
