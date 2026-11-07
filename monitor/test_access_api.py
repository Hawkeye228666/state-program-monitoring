import csv
import io
import tempfile
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, Client, override_settings
from .models import Observation, ImportRun
from .importer import import_documents
from .sdmx import unpack_uploads


class AccessApiScenarioTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=Path(settings.BASE_DIR).parent)
        cls.settings_override = override_settings(MEDIA_ROOT=cls.tmp.name)
        cls.settings_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.settings_override.disable(); cls.tmp.cleanup()

    @classmethod
    def setUpTestData(cls):
        call_command('setup_roles', stdout=io.StringIO())
        for username, role in [('analyst','Аналитик'), ('operator','Оператор загрузки'), ('administrator','Администратор')]:
            user = get_user_model().objects.create_user(username, password='test-only-password')
            user.groups.add(Group.objects.get(name=role))
        get_user_model().objects.create_user('unassigned', password='test-only-password')
        cls.archive = next((settings.BASE_DIR/'materials').glob('*.zip')).read_bytes()
        cls.docs = unpack_uploads([('materials.zip',cls.archive)])
        import_documents(cls.docs)

    def sign_in(self, username='analyst'):
        self.assertTrue(self.client.login(username=username,password='test-only-password'))

    def test_anonymous_and_unassigned_access(self):
        for path in ['/', '/explore/', '/upload/', '/history/']:
            self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.client.get('/api/v1/indicators/').status_code,401)
        self.sign_in('unassigned')
        self.assertEqual(self.client.get('/explore/').status_code,403)
        self.assertEqual(self.client.get('/upload/').status_code,403)
        self.assertEqual(self.client.get('/api/v1/observations/').status_code,403)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_health_check_survives_https_redirect_policy(self):
        self.assertEqual(self.client.get('/healthz/').status_code,200)
        self.assertEqual(self.client.get('/accounts/login/').status_code,301)

    @override_settings(SECURE_SSL_REDIRECT=True,SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https'))
    def test_trusted_tls_ingress_does_not_redirect_https_requests(self):
        response=self.client.get('/accounts/login/',HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code,200)

    def test_roles_read_import_and_no_anonymous_mutation(self):
        self.sign_in()
        self.assertEqual(self.client.get('/explore/').status_code,200)
        self.assertEqual(self.client.post('/upload/',{'action':'preview'}).status_code,403)
        self.assertEqual(self.client.get('/api/v1/indicators/').json()['count'],6)
        self.sign_in('operator')
        self.assertEqual(self.client.get('/upload/').status_code,200)
        self.assertEqual(self.client.get('/admin/').status_code,302)
        self.assertEqual(self.client.post('/api/v1/observations/').status_code,405)
        self.assertEqual(self.client.get('/healthz/').json(),{'status':'ok'})

    def test_api_pagination_source_and_exact_decimal_values(self):
        self.sign_in()
        q='/api/v1/observations/?program=housing&indicator=43512&page_size=2'
        page=self.client.get(q).json()
        self.assertEqual(page['count'],1304); self.assertEqual(len(page['results']),2)
        self.assertEqual(page['page'],1); self.assertTrue(page['next'])
        second=self.client.get(page['next']).json()
        self.assertFalse({r['id'] for r in page['results']} & {r['id'] for r in second['results']})
        row=page['results'][0]
        self.assertIsInstance(row['value'],str)
        self.assertEqual(len(row['source']['sha256']),64)
        self.assertEqual(row['okfs']['state'],'absent')
        for value in ['0','501','bad']:
            self.assertEqual(self.client.get(q+'&page_size='+value).status_code,400)
        self.assertEqual(self.client.get(q+'&page=100000').status_code,400)
        indicators=self.client.get('/api/v1/indicators/?program=science&page_size=1').json()
        self.assertEqual(indicators['count'],3); self.assertTrue(indicators['results'][0]['sources'])

    def test_okfs_quarter_api_csv_and_table_agree(self):
        self.sign_in()
        q='program=science&indicator=44198&regions=643&periods=2014-Q1&periods=2014-Q2&periods=2014-Q3&dim_s_OKFS=200'
        api=self.client.get('/api/v1/observations/?'+q).json()
        self.assertEqual(api['count'],3)
        self.assertEqual([r['value'] for r in api['results']],['111.7','120.3','125'])
        self.assertEqual({r['period']['type'] for r in api['results']},{'quarter'})
        self.assertEqual({r['okfs']['code'] for r in api['results']},{'200'})
        table=self.client.get('/explore/?'+q)
        self.assertEqual(table.context['total'],api['count'])
        exported=self.client.get('/explore/?'+q+'&format=csv')
        records=list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual([r[8] for r in records[1:]],[r['value'] for r in api['results']])
        self.assertEqual({r[-3] for r in records[1:]},{'200'})
        self.assertNotContains(table,'ВСЕГО (по всем формам собственности)')
        no199=self.client.get('/api/v1/observations/?program=science&indicator=44198&dim_s_OKFS=199').json()
        self.assertEqual(no199['count'],0)
        no_okfs=self.client.get('/api/v1/observations/?program=science&mode=all&dim_s_OKFS=__absent__').json()
        self.assertEqual(no_okfs['count'],2378)

    def test_real_login_upload_filter_chart_export_with_csrf(self):
        client=Client(enforce_csrf_checks=True)
        client.get('/accounts/login/')
        response=client.post('/accounts/login/',{'username':'operator','password':'test-only-password',
                             'csrfmiddlewaretoken':client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code,302)
        client.get('/upload/')
        csrf=client.cookies['csrftoken'].value
        self.assertEqual(client.post('/upload/',{'action':'preview'}).status_code,403)
        response=client.post('/upload/',{'action':'preview','csrfmiddlewaretoken':csrf,
                             'files':SimpleUploadedFile('materials.zip',self.archive)})
        self.assertEqual(len(response.context['preview']),6)
        from .catalog import MAPPING
        response=client.post('/upload/',{'action':'confirm','csrfmiddlewaretoken':csrf}|
                             {'program_'+d.sha256:MAPPING[d.file_id] for d in self.docs})
        self.assertEqual(response.status_code,302)
        run=ImportRun.objects.first()
        self.assertEqual(run.skipped,6792); self.assertEqual(run.actor.username,'operator')
        self.assertEqual(Observation.objects.count(),6792)
        q='program=housing&indicator=43537&level=subject&periods=2012&periods=2020&compare_start=2012&compare_end=2020&chart_period=2020'
        before=set(Observation.objects.filter(indicator__file_id='43537',territory__kind='subject',period__code='2012').values_list('territory__code',flat=True))
        after=set(Observation.objects.filter(indicator__file_id='43537',territory__kind='subject',period__code='2020').values_list('territory__code',flat=True))
        q+=''.join('&regions='+code for code in sorted(before & after)[:5])
        response=client.get('/explore/?'+q)
        self.assertEqual(response.status_code,200)
        data=response.context['analytics']
        self.assertFalse(data['dumbbell']['reason']); self.assertGreater(data['dumbbell']['n'],3)
        self.assertFalse(data['boxplot']['reason']); self.assertGreater(data['boxplot']['n'],3)
        response=client.get('/explore/?'+q+'&format=csv')
        self.assertGreater(len(response.content),1000)
        client.get('/accounts/login/')
        self.assertEqual(client.post('/accounts/logout/',{'csrfmiddlewaretoken':client.cookies['csrftoken'].value}).status_code,302)
        self.assertEqual(client.get('/explore/').status_code,302)
