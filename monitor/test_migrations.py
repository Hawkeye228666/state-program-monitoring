from decimal import Decimal
from django.test import TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
class NativeDecimalMigrationTests(TransactionTestCase):
    def test_existing_postgres_rows_survive_upgrade(self):
        executor=MigrationExecutor(connection);executor.migrate([('monitor','0002_exact_numeric')])
        try:
            apps=executor.loader.project_state([('monitor','0002_exact_numeric')]).apps
            p=apps.get_model('monitor','Program').objects.create(slug='legacy',name='User title',summary='User edit',schedule='')
            i=apps.get_model('monitor','Indicator').objects.create(program=p,file_id='upgrade',metadata_id='upgrade',name='Edited indicator')
            t=apps.get_model('monitor','Territory').objects.create(code='0001',name='Region',kind='subject')
            period=apps.get_model('monitor','Period').objects.create(code='2014-Q1',label='Q1',year=2014,order='2014-Q1')
            source=apps.get_model('monitor','SourceFile').objects.create(sha256='a'*64,filename='x',original_path='x',size=0,header_id='x',dataset_id='x')
            run=apps.get_model('monitor','ImportRun').objects.create(status='success')
            row=apps.get_model('monitor','Observation').objects.create(indicator=i,territory=t,period=period,source=source,last_import=run,dimension_key='a'*64,numeric_text='111.7',raw_value='111,7',dimensions={'s_OKFS':'200'})
            executor=MigrationExecutor(connection);executor.migrate([('monitor','0003_native_decimal')])
            from monitor.models import Observation,Program
            new=Observation.objects.get(pk=row.pk)
            self.assertEqual(new.numeric_value,Decimal('111.7'));self.assertEqual(new.dimensions,{'s_OKFS':'200'})
            self.assertEqual(Program.objects.get(pk=p.pk).summary,'User edit')
        finally:MigrationExecutor(connection).migrate([('monitor','0003_native_decimal')])
