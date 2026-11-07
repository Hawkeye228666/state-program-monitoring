"""Проверки смысловых состояний ОКФС и независимых контрольных чисел XML."""
import copy
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
from django.conf import settings
from django.test import TestCase, override_settings
from .tests import original_files
from .sdmx import parse_document, NS, DataError
from .importer import import_documents
from .dimensions import dimension_info
from .models import Observation, Program, Indicator, Territory, DimensionValue
from .okfs_audit import audit_document


def one_series(files, file_id='44198'):
    name,data=next((n,d) for n,d in files if 'data_'+file_id+'.' in n)
    root=ET.fromstring(data);ds=root.find('m:DataSet',NS)
    for child in list(ds)[1:]:ds.remove(child)
    return name,root,ds

def parsed(name,root):return parse_document(name,ET.tostring(root,encoding='utf-8'))

class OkfsAuditTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass();cls.files=original_files()
    def test_independent_all_six_xml_counts_and_okfs_reference(self):
        results={r['file_id']:r for n,d in self.files if (r:=audit_document(n,d))}
        self.assertEqual({k:v['observations'] for k,v in results.items()},{'43512':1304,'43537':860,'43563':1024,'43586':1045,'43587':1333,'44198':1226})
        self.assertEqual([k for k,v in results.items() if v['okfs_present']],['44198'])
        a=results['44198'];self.assertEqual(a['codes_in_observations'],{'12':536,'13':128,'14':13,'200':549})
        self.assertEqual(a['codelist'],{'12':'Федеральная собственность','13':'Собственность субъектов Российской Федерации','14':'Муниципальная собственность','199':'ВСЕГО (по всем формам собственности)','200':'ВСЕГО'})
        self.assertEqual(a['unused_codes'],['199']);self.assertEqual(a['duplicate_groups_without_quarter'],409);self.assertEqual(a['duplicate_groups_with_quarter'],0)
        self.assertEqual({x['PERIOD']:x['value'].replace(',','.') for x in a['control_643_2014_200']},{'I квартал':'111.7','II квартал':'120.3','III квартал':'125'})
    def test_conflicting_time_and_period_quarter_is_rejected(self):
        name,root,ds=one_series(self.files)
        ds[0].find('g:Obs/g:Time',NS).text='2014-Q2'
        with self.assertRaisesMessage(DataError,'разные кварталы'):parsed(name,root)

class OkfsStorageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=settings.BASE_DIR.parent)
        cls.over=override_settings(MEDIA_ROOT=cls.temp.name);cls.over.enable();super().setUpClass();cls.files=original_files()
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass();cls.over.disable();cls.temp.cleanup()
    def test_absent_dimension_not_total_and_repeat_is_idempotent(self):
        name,root,ds=one_series(self.files,'43512');doc=parsed(name,root)
        import_documents([doc]);run=import_documents([doc]);row=Observation.objects.get()
        self.assertNotIn('s_OKFS',row.dimensions);self.assertEqual(dimension_info(row)['state'],'absent');self.assertIsNone(dimension_info(row)['code'])
        self.assertEqual((run.added,run.skipped),(0,1));self.assertEqual(Observation.objects.count(),1)
    def test_declared_empty_and_omitted_okfs_remain_missing(self):
        for omitted in (True,False):
            with self.subTest(omitted=omitted):
                name,root,ds=one_series(self.files)
                key=ds[0].find('g:SeriesKey',NS);node=next(e for e in key if e.attrib.get('concept')=='s_OKFS')
                if omitted:key.remove(node)
                else:node.set('value','')
                doc=parsed(name,root);self.assertEqual(doc.rows[0]['dimensions']['s_OKFS'],'')
                import_documents([doc]);row=Observation.objects.get();self.assertEqual(dimension_info(row)['state'],'missing')
                self.assertEqual(import_documents([doc]).skipped,1);self.assertEqual(Observation.objects.count(),1)
    def test_unknown_raw_code_and_diagnostics_are_preserved(self):
        name,root,ds=one_series(self.files)
        for node in ds[0].findall('g:SeriesKey/g:Value',NS):
            if node.attrib['concept']=='s_OKFS':node.set('value','0999')
        doc=parsed(name,root);self.assertEqual(doc.metadata['diagnostics'][0]['code'],'0999')
        import_documents([doc]);row=Observation.objects.select_related('source').get();info=dimension_info(row)
        self.assertEqual((info['state'],info['code'],info['label']),('unknown','0999','0999'));self.assertTrue(info['diagnostic'])
        self.assertEqual(row.dimensions['s_OKFS'],'0999');self.assertEqual(row.source.metadata['diagnostics'][0]['count'],1)
    def test_199_and_200_are_separate_and_unused_codes_not_in_observed_dictionary(self):
        name,root,ds=one_series(self.files);doc=parsed(name,root);import_documents([doc])
        self.assertFalse(DimensionValue.objects.filter(dimension__code='s_OKFS',code='199').exists())
        other=copy.deepcopy(ds[0]);ds.append(other)
        for node in other.findall('g:SeriesKey/g:Value',NS):
            if node.attrib['concept']=='s_OKFS':node.set('value','199')
        doc=parsed(name,root);run=import_documents([doc]);self.assertEqual(run.added,1)
        self.assertEqual({o.dimensions['s_OKFS'] for o in Observation.objects.all()},{'199','200'})
        self.assertEqual(import_documents([doc]).skipped,2);self.assertEqual(Observation.objects.count(),2)
    def test_repeat_import_preserves_edited_reference_metadata(self):
        name,root,ds=one_series(self.files);doc=parsed(name,root);import_documents([doc])
        p=Program.objects.get(slug='science');p.summary='Описание аналитика';p.save()
        i=Indicator.objects.get(file_id='44198');i.name='Название аналитика';i.save()
        t=Territory.objects.get(code='643');t.name='Территория аналитика';t.save()
        v=DimensionValue.objects.get(dimension__indicator=i,dimension__code='s_OKFS',code='200');v.label='Подпись аналитика';v.save()
        import_documents([doc]);p.refresh_from_db();i.refresh_from_db();t.refresh_from_db();v.refresh_from_db()
        self.assertEqual((p.summary,i.name,t.name,v.label),('Описание аналитика','Название аналитика','Территория аналитика','Подпись аналитика'))
        self.assertEqual(Observation.objects.get().dimension_labels['s_OKFS'],'ВСЕГО')

    def test_state_filters_never_alias_codes_or_missing(self):
        from django.http import QueryDict
        from .queries import select_rows
        name,root,ds=one_series(self.files)
        missing=copy.deepcopy(ds[0]);unknown=copy.deepcopy(ds[0]);ds.extend([missing,unknown])
        for series,value in ((missing,''),(unknown,'0999')):
            for node in series.findall('g:SeriesKey/g:Value',NS):
                if node.attrib['concept']=='s_OKFS':node.set('value',value)
        import_documents([parsed(name,root)])
        n,r,_=one_series(self.files,'43586');import_documents([parsed(n,r)])
        program=Program.objects.get(slug='science')
        for token,state,code in (('__missing__','missing',''),('__unknown__','unknown','0999'),('__absent__','absent',None),('200','known','200')):
            with self.subTest(token=token):
                rows,_,_=select_rows(program,QueryDict('mode=all&dim_s_OKFS='+token))
                self.assertEqual(len(rows),1)
                info=dimension_info(rows[0]);self.assertEqual((info['state'],info['code']),(state,code))
