import io,json,tempfile,zipfile,copy
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import TestCase,override_settings
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import QueryDict
from .models import Program,Indicator,Observation,ImportRun,ClassifierSnapshot,ImportJob,MappingProfile
from .streaming import extract_sources,metadata,rows,period_info,validate_profile,Source
from .bulk_import import import_sources
from .queries import select_rows,chart_data
from .sdmx import DataError

class IndustryTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=settings.BASE_DIR.parent)
        self.override=override_settings(MEDIA_ROOT=self.temp.name);self.override.enable()
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.override.disable)
        self.program=Program.objects.create(slug='third',name='Третья программа',summary='',schedule='')
        self.sources=list(extract_sources([settings.BASE_DIR/'tests/fixtures/industry-fragments.zip']))
        self.assignments={metadata(s)['file_id']:'third' for s in self.sources}
    def load(self,sources=None):return import_sources(sources or self.sources,self.assignments)
    def test_unknown_ids_grouping_classifiers_and_periods(self):
        run=self.load();self.assertEqual(run.raw_count,78);self.assertEqual(Indicator.objects.count(),4)
        self.assertEqual(Observation.objects.count(),run.unique_count)
        old=ClassifierSnapshot.objects.get(source__filename='fragment_43007.sdmx',concept='s_OKVED')
        new=ClassifierSnapshot.objects.get(source__filename='fragment_58699.sdmx',concept='s_OKVED2')
        self.assertNotEqual(old.identity,new.identity);self.assertIn('ДОБЫЧА',old.codes['C']);self.assertIn('ОБРАБАТЫВАЮЩИЕ',new.codes['C'].upper())
        self.assertIsNone(old.edition);self.assertIn('w2:p_kfs:61',ClassifierSnapshot.objects.get(source__filename='fragment_43007.sdmx',concept='s_OKFS').codes)
        periods=Observation.objects.filter(indicator__file_id='43909').values_list('period__kind','territory__code','dimensions')
        self.assertTrue(any(k=='cumulative' for k,t,d in periods));self.assertTrue(all(t=='643' and 's_OKSM' in d for k,t,d in periods))
    def test_repeat_import_and_atomic_rollback(self):
        run=self.load();again=self.load();self.assertEqual((again.added,again.updated,again.skipped),(0,0,run.unique_count))
        before=Observation.objects.count()
        with patch('monitor.bulk_import.rows',side_effect=DataError('Injected mid-run failure')):
            with self.assertRaises(DataError):self.load()
        self.assertEqual(Observation.objects.count(),before);self.assertEqual(ImportRun.objects.order_by('-pk').first().status,'error')
        self.assertEqual(self.load().added,0)
    def test_conflicting_duplicates_abort_and_matching_duplicates_count(self):
        source=self.sources[0];info=metadata(source);original=list(rows(source,info));one=original[0]
        with patch('monitor.bulk_import.rows',return_value=iter([one,copy.deepcopy(one)])):
            run=self.load([source]);self.assertEqual((run.raw_count,run.unique_count,run.added),(2,1,1))
        bad=copy.deepcopy(one);bad['raw_value']='999';bad['numeric_value']='999'
        with patch('monitor.bulk_import.rows',return_value=iter([one,bad])):
            with self.assertRaisesMessage(DataError,'Конфликтующие'):self.load([source])
        self.assertEqual(Observation.objects.count(),1)
    def test_multiple_year_files_extend_one_indicator(self):
        source=self.sources[0];info=metadata(source);a=list(rows(source,info))[0];b=copy.deepcopy(a)
        b['period']=period_info('2010','значение показателя за год')
        with patch('monitor.bulk_import.rows',side_effect=[iter([a]),iter([b])]):self.load([source,source])
        self.assertEqual(Indicator.objects.count(),1);self.assertEqual(Observation.objects.count(),2)
    def test_combined_database_filters_and_context(self):
        self.load();row=Observation.objects.filter(indicator__file_id='58699').first()
        params=QueryDict('',mutable=True);params.update(indicator='58699',dim_s_OKVED2=row.dimensions['s_OKVED2'],dim_s_OKFS=row.dimensions['s_OKFS'])
        qs,_,_=select_rows(self.program,params)
        self.assertIn('@>',str(qs.query));self.assertGreater(qs.count(),0)
        self.assertTrue(all(o.dimensions['s_OKFS']==row.dimensions['s_OKFS'] and o.dimensions['s_OKVED2']==row.dimensions['s_OKVED2'] for o in qs))
        self.assertTrue(any('101.АГ'==o.dimensions.get('s_OKVED2') for o in Observation.objects.all()))
    def test_program_creation_and_edit_permission(self):
        call_command('setup_roles',stdout=io.StringIO());user=get_user_model().objects.create_user('operator',password='test')
        user.groups.add(Group.objects.get(name='Оператор загрузки'));self.client.force_login(user)
        data={'slug':'fourth','name':'Четвёртая программа','summary':'Описание','schedule':'','source_urls':'https://example.org/source'}
        response=self.client.post('/programs/new/',data);self.assertEqual(response.status_code,302)
        self.assertEqual(Program.objects.get(slug='fourth').sources[0]['url'],'https://example.org/source')
        data['name']='Исправленное название';self.assertEqual(self.client.post('/programs/fourth/edit/',data).status_code,302)
        user.groups.clear();self.assertEqual(self.client.post('/programs/new/',data).status_code,403)
    def test_bounded_charts_streaming_csv_and_api_same_filter(self):
        self.load();user=get_user_model().objects.create_superuser('admin',password='test');self.client.force_login(user)
        q='program=third&indicator=43909&regions=643'
        result=self.client.get('/api/v1/observations/?'+q).json()
        response=self.client.get('/explore/?'+q+'&format=csv');self.assertTrue(response.streaming)
        import csv
        records=list(csv.reader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(records)-1,result['count'])
        with override_settings(SDMX_MAX_CHART_POINTS=1):
            response=self.client.get('/explore/?'+q);self.assertContains(response,'Уточните территории')
            self.assertEqual(response.context['page'].paginator.count,result['count'])
    def test_profile_is_declarative_and_mapping_does_not_move_indicator(self):
        info=metadata(self.sources[0]);rules=validate_profile(info)
        rules['s_OKATO']['transform']='__import__("os")'
        with self.assertRaises(DataError):validate_profile(info,rules)
        self.load();other=Program.objects.create(slug='other',name='Other',summary='',schedule='')
        assignments={k:'other' for k in self.assignments}
        with self.assertRaisesMessage(DataError,'уже относится'):import_sources(self.sources,assignments)
        self.assertEqual(Indicator.objects.filter(program=self.program).count(),4)
    def test_full_period_key_and_comparability(self):
        annual=period_info('2014','значение показателя за год');dec=period_info('2014','январь-декабрь');march=period_info('2014','январь-март')
        self.assertNotEqual(annual['code'],dec['code']);self.assertNotEqual(dec['code'],march['code'])
        self.assertTrue(march['cumulative']);self.assertEqual(march['end'].month,3)
        self.load();source=Observation.objects.filter(indicator__file_id='43909').select_related('period','territory','indicator','source')
        self.assertTrue(chart_data(list(source))['reason'])
    def test_background_preview_and_explicit_approval(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .jobs import process
        user=get_user_model().objects.create_superuser('jobadmin',password='test');self.client.force_login(user)
        data=(settings.BASE_DIR/'tests/fixtures/industry-fragments.zip').read_bytes()
        response=self.client.post('/imports/new/',{'files':SimpleUploadedFile('fragments.zip',data),'program':'third'})
        self.assertEqual(response.status_code,302);job=ImportJob.objects.get();self.assertEqual(job.state,'preview_pending');self.assertFalse(Observation.objects.exists())
        job.state='preview_running';process(job);job.refresh_from_db();self.assertEqual(job.state,'awaiting_approval')
        self.assertTrue(all(len(p['sample'])<=3 for p in job.preview))
        self.client.post('/imports/'+str(job.pk)+'/',{'confirm_mapping':'yes',**{'program_'+k:'third' for k in self.assignments}})
        job.refresh_from_db();self.assertEqual(job.state,'queued');job.state='importing';process(job);job.refresh_from_db()
        self.assertEqual(job.state,'success');self.assertEqual(Observation.objects.count(),78)
    def test_other_operator_cannot_approve_someone_elses_job(self):
        call_command('setup_roles',stdout=io.StringIO())
        owner=get_user_model().objects.create_user('owner');other=get_user_model().objects.create_user('other')
        other.groups.add(Group.objects.get(name='Оператор загрузки'));self.client.force_login(other)
        job=ImportJob.objects.create(actor=owner)
        self.assertEqual(self.client.get('/imports/'+str(job.pk)+'/').status_code,403)
