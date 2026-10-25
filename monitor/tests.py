import csv, io, json, tempfile, zipfile
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as XML
from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.http import QueryDict
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from .sdmx import parse_document, unpack_uploads, DataError, NS, MAX_XML
from .importer import import_documents
from .models import Observation, Program, Territory, ImportRun, SourceFile
from .queries import select_rows, chart_data
from .catalog import MAPPING

EXPECTED={'43512':1304,'43537':860,'43563':1024,'43586':1045,'43587':1333,'44198':1226}

def original_files():
    files=[]
    def walk(blob):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for f in z.infolist():
                if f.is_dir():continue
                data=z.read(f)
                if f.filename.endswith('.zip'):walk(data)
                elif f.filename.endswith('.sdmx'):files.append((f.filename,data))
    walk(next((Path(settings.BASE_DIR)/'materials').glob('*.zip')).read_bytes())
    return files

def zipbytes(name,data):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:z.writestr(name,data)
    return b.getvalue()

class ParserSafetyTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.files=original_files()
    def test_each_provided_file_and_independent_counts(self):
        for name,data in self.files:
            with self.subTest(file=name):
                d=parse_document(name,data);root=XML.fromstring(data)
                self.assertEqual(len(d.rows),EXPECTED[d.file_id])
                self.assertEqual(len(d.rows),len(root.findall('.//g:Obs',NS)))
                self.assertEqual(d.name,root.find('m:Description/m:Indicator',NS).attrib['name'])
                self.assertEqual(d.header_id,root.findtext('m:Header/m:ID',namespaces=NS))
                self.assertEqual(d.metadata['missing'],0)
    def test_common_nested_and_multiple_zip(self):
        payload=next((Path(settings.BASE_DIR)/'materials').glob('*.zip')).read_bytes()
        docs=unpack_uploads([('materials.zip',payload)])
        self.assertEqual({d.file_id for d in docs},set(EXPECTED))
        self.assertEqual(len(unpack_uploads([(n+'.zip',zipbytes(n,b)) for n,b in self.files[:2]])),2)
    def test_corrupt_unsupported_and_xxe(self):
        for data in [b'<broken',b'<GenericData/>',b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///C:/Windows/win.ini">]><x>&x;</x>']:
            with self.subTest(data=data),self.assertRaises(DataError):parse_document('x.xml',data)
        with self.assertRaises(DataError):unpack_uploads([('x.txt',b'abc')])
        with self.assertRaises(DataError):unpack_uploads([('x.zip',b'broken')])
    def test_zip_paths_depth_and_limits(self):
        name,data=self.files[0]
        for bad in ['../outside.xml','C:/outside.xml','/outside.xml','a/../../outside.xml','..\\outside.xml']:
            with self.subTest(path=bad),self.assertRaises(DataError):unpack_uploads([('x.zip',zipbytes(bad,data))])
        blob=data
        for x in range(5):blob=zipbytes('x.xml' if x==0 else 'x.zip',blob)
        with self.assertRaises(DataError):unpack_uploads([('x.zip',blob)])
        with self.assertRaises(DataError):parse_document('large.xml',b' '*(MAX_XML+1))
        with patch('monitor.sdmx.MAX_EXPANDED',10),self.assertRaises(DataError):unpack_uploads([('x.zip',zipbytes(name,data))])
        with patch('monitor.sdmx.MAX_ENTRIES',1),self.assertRaises(DataError):unpack_uploads([('x.zip',zipbytes(name,data))])
    def test_quarter_and_ownership_are_preserved(self):
        name,data=next(x for x in self.files if '44198' in x[0]);d=parse_document(name,data)
        self.assertEqual(set(d.periods),{'2014-Q1','2014-Q2','2014-Q3','2015-Q1','2015-Q2','2015-Q3'})
        self.assertEqual({r['dimensions']['s_OKFS'] for r in d.rows},{'200','12','13','14'})
        self.assertEqual(d.rows[0]['numeric_text'],'111.7')
    def test_missing_and_status_and_high_precision(self):
        name,data=self.files[0]
        for raw,expected in [('',None),('…',None),('NaN',None),('0','0'),('123456789012345.123456789','123456789012345.123456789')]:
            root=XML.fromstring(data);obs=root.find('.//g:ObsValue',NS);obs.set('value',raw);obs.set('status','M')
            d=parse_document(name,XML.tostring(root,encoding='utf-8'))
            self.assertEqual(d.rows[0]['numeric_text'],expected);self.assertEqual(d.rows[0]['raw_value'],raw);self.assertEqual(d.rows[0]['status'],{'status':'M'})
    def test_conflicting_duplicates_rejected(self):
        name,data=self.files[0];root=XML.fromstring(data);ds=root.find('m:DataSet',NS)
        import copy
        row=copy.deepcopy(ds[0]);row.find('g:Obs/g:ObsValue',NS).set('value','999');ds.append(row)
        with self.assertRaises(DataError):parse_document(name,XML.tostring(root,encoding='utf-8'))

class FullProjectTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=Path(settings.BASE_DIR).parent);cls.override=override_settings(MEDIA_ROOT=cls.tmp.name);cls.override.enable();super().setUpClass()
    @classmethod
    def tearDownClass(cls):
        cls.override.disable();cls.tmp.cleanup();super().tearDownClass()
    @classmethod
    def setUpTestData(cls):
        cls.files=original_files();cls.docs=[parse_document(n,b) for n,b in cls.files]
        for d in cls.docs:import_documents([d])
    def test_all_database_values_against_independent_xml(self):
        self.assertEqual(Observation.objects.count(),6792)
        for name,data in self.files:
            fileid=name.split('_')[1].split('.')[0]
            db={(o.territory.code,o.period.code,tuple(sorted(o.dimensions.items()))):o for o in Observation.objects.filter(indicator__file_id=fileid).select_related('territory','period')}
            self.assertEqual(len(db),EXPECTED[fileid])
            root=XML.fromstring(data)
            for series in root.findall('m:DataSet/g:Series',NS):
                keys={e.attrib['concept']:e.attrib['value'] for e in series.findall('g:SeriesKey/g:Value',NS)}
                attrs={e.attrib['concept']:e.attrib['value'] for e in series.findall('g:Attributes/g:Value',NS)}
                for obs in series.findall('g:Obs',NS):
                    year=obs.findtext('g:Time',namespaces=NS);period=year
                    quarter={'I квартал':'Q1','II квартал':'Q2','III квартал':'Q3','IV квартал':'Q4'}.get(attrs.get('PERIOD'))
                    if quarter:period+='-'+quarter
                    dims={k:v for k,v in keys.items() if k!='s_OKATO'}|attrs
                    actual=db[(keys['s_OKATO'],period,tuple(sorted(dims.items())))];raw=obs.find('g:ObsValue',NS).attrib['value']
                    self.assertEqual(actual.raw_value,raw);self.assertEqual(actual.number,Decimal(raw.replace(',','.')))
    def test_idempotent_all_files(self):
        r=import_documents(self.docs)
        self.assertEqual((r.added,r.updated,r.skipped,r.errors),(0,0,6792,0));self.assertEqual(Observation.objects.count(),6792)
    def test_update_rule_and_transaction_rollback(self):
        name,data=self.files[0];root=XML.fromstring(data);root.find('.//g:ObsValue',NS).set('value','123.456')
        d=parse_document(name,XML.tostring(root,encoding='utf-8'));r=import_documents([d])
        self.assertEqual((r.updated,r.added),(1,0))
        old=Observation.objects.get(indicator__file_id=d.file_id,territory__code='643',period__code='2013');self.assertEqual(old.number,Decimal('123.456'))
        root.find('.//g:ObsValue',NS).set('value','456.789');d2=parse_document(name,XML.tostring(root,encoding='utf-8'))
        with self.assertRaises(DataError):import_documents([d2,self.docs[1]],{self.docs[1].sha256:'wrong'})
        old.refresh_from_db();self.assertEqual(old.number,Decimal('123.456'));self.assertEqual(ImportRun.objects.first().status,'error')
    def test_region_codes_and_levels(self):
        self.assertTrue(Territory.objects.filter(code='030',kind='district').exists())
        self.assertTrue(Territory.objects.filter(code='643004.АГ',kind='aggregate').exists())
        self.assertEqual(Territory.objects.get(code='15401000000').kind,'municipality')
        self.assertEqual(Territory.objects.get(code='11100000000').kind,'subject')
    def test_one_and_all_modes(self):
        p=Program.objects.get(slug='housing');params=QueryDict('mode=one&indicator=43512&regions=643&periods=2013&periods=2014')
        rows,_,_=select_rows(p,params);self.assertEqual([o.raw_value for o in rows],['35958','29932'])
        rows,_,_=select_rows(p,QueryDict('mode=all&regions=643&periods=2014'))
        self.assertEqual({o.indicator.file_id for o in rows},{'43512','43537','43563'});self.assertEqual(len(rows),3)
        with self.assertRaises(DataError):select_rows(p,QueryDict('mode=one&indicator=44198'))
    def test_additional_dimension_filter(self):
        p=Program.objects.get(slug='science');rows,_,_=select_rows(p,QueryDict('mode=one&indicator=44198&regions=643&dim_s_OKFS=12&periods=2014-Q1'))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0].dimensions['s_OKFS'],'12')
        self.assertEqual(rows[0].raw_value,'111,1')
    def test_table_csv_json_chart_agreement_and_full_export(self):
        q='program=housing&mode=one&indicator=43537&regions=643&periods=2012&periods=2013'
        html=self.client.get('/explore/?'+q);self.assertEqual(html.status_code,200);self.assertEqual(html.context['total'],2)
        api=self.client.get('/explore/?'+q+'&format=json').json();self.assertEqual(api['count'],2)
        csvres=self.client.get('/explore/?'+q+'&format=csv');self.assertTrue(csvres.content.startswith(b'\xef\xbb\xbf'))
        cr=list(csv.reader(io.StringIO(csvres.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual([x[8] for x in cr[1:]],[x['value'] for x in api['rows']])
        self.assertEqual(api['chart']['line']['datasets'][0]['data'],['65.74','70.5'])
        self.assertEqual(html.context['chart'],api['chart'])
        q2='program=housing&mode=one&indicator=43512&submitted=1'
        h=self.client.get('/explore/?'+q2);self.assertEqual(len(h.context['page']),50)
        export=self.client.get('/explore/?'+q2+'&page=2&format=csv')
        self.assertEqual(len(list(csv.reader(io.StringIO(export.content.decode('utf-8-sig')),delimiter=';')))-1,1304)
    def test_empty_results_and_chart_guards(self):
        r=self.client.get('/explore/?program=housing&mode=all&regions=missing');self.assertEqual(r.status_code,200);self.assertContains(r,'нет наблюдений')
        rows,_,_=select_rows(Program.objects.get(slug='science'),QueryDict('mode=one&indicator=44198&regions=643'))
        self.assertFalse(chart_data(rows)['reason']);self.assertTrue(chart_data(rows)['heat_reason'])
        allrows,_,_=select_rows(Program.objects.get(slug='science'),QueryDict('mode=all&regions=643'));self.assertTrue(chart_data(allrows)['reason'])
    def test_pages_filters_and_numeric_sort(self):
        for url in ['/','/programs/housing/','/programs/science/','/upload/','/history/','/explore/']:
            with self.subTest(url=url):self.assertEqual(self.client.get(url).status_code,200)
        q='program=science&mode=one&indicator=44198&regions=643&dim_s_OKFS=12'
        self.client.get('/explore/?'+q+'&save=1');r=self.client.get('/explore/?program=science&restore=1');self.assertEqual(r.status_code,302);self.assertIn('dim_s_OKFS=12',r.url)
        rows,_,_=select_rows(Program.objects.get(slug='housing'),QueryDict('indicator=43537&regions=643&sort=value'));self.assertEqual([o.number for o in rows],sorted(o.number for o in rows))
    def test_upload_preview_confirm_and_double_confirm(self):
        blob=next((Path(settings.BASE_DIR)/'materials').glob('*.zip')).read_bytes()
        r=self.client.post('/upload/',{'action':'preview','files':SimpleUploadedFile('materials.zip',blob)})
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.context['preview']),6);self.assertEqual(Observation.objects.count(),6792)
        data={'action':'confirm'}|{'program_'+d.sha256:MAPPING[d.file_id] for d in self.docs}
        r=self.client.post('/upload/',data);self.assertRedirects(r,'/history/');run=ImportRun.objects.first();self.assertEqual(run.skipped,6792)
        r=self.client.post('/upload/',data);self.assertContains(r,'Предпросмотр истёк');self.assertEqual(Observation.objects.count(),6792)
        r=self.client.post('/upload/',{'action':'preview','files':SimpleUploadedFile('broken.xml',b'<broken')});self.assertContains(r,'повреждённый XML')
    def test_missing_stored_without_zero(self):
        name,data=self.files[0];root=XML.fromstring(data);root.find('.//g:ObsValue',NS).set('value','…');d=parse_document(name,XML.tostring(root,encoding='utf-8'));import_documents([d])
        o=Observation.objects.get(indicator__file_id='43512',territory__code='643',period__code='2013');self.assertIsNone(o.number)
        rows,_,_=select_rows(o.indicator.program,QueryDict('indicator=43512&regions=643&periods=2013'))
        self.assertEqual(chart_data(rows)['line']['datasets'][0]['data'],[None])

    def test_empty_database_is_usable(self):
        from .models import Indicator
        Observation.objects.all().delete();Indicator.objects.all().delete()
        for url in ['/','/explore/','/upload/']:
            self.assertEqual(self.client.get(url).status_code,200)
    def test_multiple_dimension_values_remain_separate(self):
        p=Program.objects.get(slug='science')
        rows,_,_=select_rows(p,QueryDict('indicator=44198&regions=643&periods=2014-Q1&dim_s_OKFS=12&dim_s_OKFS=13'))
        self.assertEqual(len(rows),2)
        self.assertEqual({o.dimensions['s_OKFS'] for o in rows},{'12','13'})
        self.assertEqual(len(chart_data(rows)['line']['datasets']),2)
