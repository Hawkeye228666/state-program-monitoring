"""Chart arithmetic, comparability and use of the shared real-data selection."""
from decimal import Decimal
from types import SimpleNamespace as Obj
import tempfile
from pathlib import Path
from django.conf import settings
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase, override_settings
from .analytics import advanced_charts, dumbbell, scatter, boxplot, quantile


def row(code='r1', value='1', period='2014', indicator='x', unit='процент', kind='subject', okfs=None, extra=None):
    dimensions = {'EI': unit, 'PERIOD': 'Год' if '-Q' not in period else period[-2:]}
    if okfs is not None: dimensions['s_OKFS'] = okfs
    dimensions.update(extra or {})
    return Obj(territory=Obj(code=code, name='Регион '+code, kind=kind),
               period=Obj(code=period, label=period, order=period),
               indicator=Obj(file_id=indicator, name='Показатель '+indicator, unit=unit),
               indicator_id=indicator, dimensions=dimensions,
               dimension_labels={'s_OKFS': {'12': 'Федеральная собственность', '199': 'ВСЕГО (по всем формам собственности)', '200': 'ВСЕГО'}.get(okfs, okfs)},
               source=Obj(metadata={'dimension_codelists': {'s_OKFS': {'12': 'Федеральная собственность', '199': 'ВСЕГО (по всем формам собственности)', '200': 'ВСЕГО'}}}),
               number=Decimal(value) if value is not None else None,
               numeric_text=value, raw_value=value or '')


class ChartArithmeticTests(SimpleTestCase):
    def test_dumbbell_exact_percentage_points_and_missing_not_zero(self):
        rows = [row(value='0.1'), row(value='0.3', period='2015'),
                row(code='r2', value='5'), row(code='r2', value=None, period='2015')]
        chart = dumbbell(rows, QueryDict(''))
        self.assertEqual(chart['reason'], '')
        self.assertEqual(chart['n'], 1)
        self.assertEqual(chart['points'][0]['change'], '0.2')
        self.assertEqual(chart['change_unit'], 'п.п.')
        self.assertEqual(chart['excluded'][0]['code'], 'r2')

    def test_dumbbell_periods_must_be_in_table_and_match_period_type(self):
        rows = [row(), row(period='2015-Q1')]
        self.assertIn('Годовое', dumbbell(rows, QueryDict(''))['reason'])
        self.assertIn('общую выборку', dumbbell([row(), row(period='2015')], QueryDict('compare_end=2016'))['reason'])
        self.assertIn('разных', dumbbell([row()], QueryDict(''))['reason'])

    def test_dumbbell_preserves_quarters_and_source_ownership_label(self):
        rows = [row(value='111.7', period='2014-Q1', okfs='200'), row(value='125', period='2014-Q3', okfs='200')]
        chart = dumbbell(rows, QueryDict(''))
        self.assertEqual(chart['reason'], '')
        self.assertEqual(chart['points'][0]['change'], '13.3')
        self.assertIn('ВСЕГО [200]', chart['cohort'])
        self.assertEqual((chart['start_code'], chart['end_code']), ('2014-Q1', '2014-Q3'))

    def test_level_and_ownership_cohorts_are_not_mixed(self):
        self.assertIn('уровень', dumbbell([row(), row(kind='country')], QueryDict(''))['reason'])
        self.assertIn('форму собственности', dumbbell([row(okfs='200'), row(okfs='12')], QueryDict(''))['reason'])
        self.assertIn('форму собственности', dumbbell([row(okfs='199'), row(okfs='200')], QueryDict(''))['reason'])
        self.assertIn('форму собственности', dumbbell([row(), row(okfs='')], QueryDict(''))['reason'])

    def test_scatter_matches_period_territory_dimensions_but_keeps_axis_units(self):
        rows = [row(code='a', value='1', unit='единица'), row(code='b', value='2', unit='единица'),
                row(code='a', indicator='y', value='10', unit='процент'), row(code='b', indicator='y', value='20', unit='процент'),
                row(code='c', indicator='y', value='30', unit='процент')]
        chart = scatter(rows, QueryDict('scatter_x=x&scatter_y=y&regions=a&regions=b&regions=c&regions=d'))
        self.assertEqual(chart['reason'], '')
        self.assertEqual(chart['n'], 2)
        self.assertEqual((chart['x_unit'], chart['y_unit']), ('единица', 'процент'))
        self.assertEqual({p['code'] for p in chart['excluded']}, {'c', 'd'})
        self.assertEqual(chart['points'][0], {'code': 'a', 'name': 'Регион a', 'x': '1', 'y': '10'})

    def test_scatter_rejects_incompatible_extra_dimensions_and_missing_axis_period(self):
        rows = [row(code='a', okfs='200'), row(code='b', okfs='200'), row(code='a', indicator='y', okfs='12'), row(code='b', indicator='y', okfs='12')]
        self.assertIn('форму собственности', scatter(rows, QueryDict(''))['reason'])
        rows = [row(), row(indicator='y', period='2014-Q1')]
        self.assertIn('Год и квартал', scatter(rows, QueryDict(''))['reason'])

    def test_scatter_requires_two_paired_numeric_territories(self):
        rows = [row(code='a'), row(code='b', value=None), row(code='a', indicator='y'), row(code='b', indicator='y')]
        chart = scatter(rows, QueryDict(''))
        self.assertEqual(chart['n'], 1)
        self.assertIn('минимум две', chart['reason'])
        self.assertEqual(chart['excluded'][0]['reason'], 'нет числового значения X')

    def test_duplicate_observations_never_get_averaged(self):
        rows = [row(), row(value='2'), row(period='2015')]
        self.assertIn('Несколько', dumbbell(rows, QueryDict(''))['reason'])
        self.assertIn('одно наблюдение', boxplot(rows, QueryDict('chart_period=2014'))['reason'])

    def test_boxplot_r7_quartiles_whiskers_outlier_and_count(self):
        rows = [row(code=str(i), value=v) for i, v in enumerate(['1', '2', '3', '4', '100'])]
        chart = boxplot(rows, QueryDict(''))
        self.assertEqual(chart['reason'], '')
        self.assertEqual(chart['n'], 5)
        self.assertEqual([Decimal(chart[k]) for k in ('q1', 'median', 'q3', 'low', 'high')], [2, 3, 4, 1, 4])
        self.assertEqual([p['value'] for p in chart['outliers']], ['100'])
        self.assertEqual((Decimal(chart['lower_fence']), Decimal(chart['upper_fence'])), (Decimal('-1'), Decimal('7')))

    def test_boxplot_zero_and_missing_and_constant_values(self):
        rows = [row(code=str(i), value=v) for i, v in enumerate(['0', '1', '2', '3', None])]
        chart = boxplot(rows, QueryDict(''))
        self.assertEqual(chart['n'], 4)
        self.assertEqual(chart['minimum'], '0')
        self.assertEqual(len(chart['excluded']), 1)
        self.assertEqual(Decimal(chart['q1']), Decimal('.75'))
        chart = boxplot([row(code=str(i), value='5') for i in range(4)], QueryDict(''))
        self.assertEqual(chart['outliers'], [])
        self.assertEqual(Decimal(chart['low']), Decimal(chart['high']))
        self.assertIn('минимум четыре', boxplot([row()], QueryDict(''))['reason'])

    def test_all_empty_charts_explain_absence(self):
        for chart in advanced_charts([], QueryDict('')).values():
            if isinstance(chart, dict): self.assertTrue(chart['reason'])

    def test_large_precision_is_preserved_and_unrenderable_exponent_is_explained(self):
        rows = [row(value='123456789012345678901234567890.1'), row(value='123456789012345678901234567890.3', period='2015')]
        self.assertEqual(advanced_charts(rows, QueryDict(''))['dumbbell']['points'][0]['change'], '0.2')
        chart = advanced_charts([row(value='1e999999999')], QueryDict(''))
        self.assertIn('диапазон', chart['dumbbell']['reason'])


class RealDataChartSelectionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=Path(settings.BASE_DIR).parent)
        cls.override = override_settings(MEDIA_ROOT=cls.tmp.name)
        cls.override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.override.disable()
        cls.tmp.cleanup()

    @classmethod
    def setUpTestData(cls):
        from .tests import original_files
        from .sdmx import parse_document
        from .importer import import_documents
        import_documents([parse_document(name, blob) for name, blob in original_files()])

    def test_real_quarters_delta_and_whole_filtered_dataset(self):
        from .models import Program
        from .queries import select_rows
        params = QueryDict('indicator=44198&regions=643&dim_s_OKFS=200&periods=2014-Q1&periods=2014-Q2&periods=2014-Q3')
        rows, _, _ = select_rows(Program.objects.get(slug='science'), params)
        chart = advanced_charts(rows, params)
        self.assertEqual(len(rows), 3)
        self.assertEqual(chart['selected_count'], 3)
        self.assertEqual(chart['dumbbell']['points'][0]['change'], '13.3')
        self.assertEqual(chart['dumbbell']['change_unit'], 'п.п.')
        self.assertEqual([o.number for o in rows], [Decimal('111.7'), Decimal('120.3'), Decimal('125')])

    def test_real_scatter_pairs_are_exact_filtered_observations(self):
        from .models import Program
        from .queries import select_rows
        params = QueryDict('mode=all&level=subject&periods=2014&scatter_x=43512&scatter_y=43537')
        rows, _, _ = select_rows(Program.objects.get(slug='housing'), params)
        chart = scatter(rows, params)
        self.assertEqual(chart['reason'], '')
        x = {o.territory.code: o for o in rows if o.indicator.file_id == '43512'}
        y = {o.territory.code: o for o in rows if o.indicator.file_id == '43537'}
        self.assertEqual({p['code'] for p in chart['points']}, x.keys() & y.keys())
        for point in chart['points']:
            self.assertEqual(Decimal(point['x']), x[point['code']].number)
            self.assertEqual(Decimal(point['y']), y[point['code']].number)
        self.assertEqual({p['code'] for p in chart['excluded']}, x.keys() ^ y.keys())

    def test_real_boxplot_contains_only_shared_filtered_subjects(self):
        from .models import Program
        from .queries import select_rows
        params = QueryDict('indicator=43537&level=subject&periods=2014')
        rows, _, _ = select_rows(Program.objects.get(slug='housing'), params)
        chart = boxplot(rows, params)
        self.assertEqual(chart['reason'], '')
        self.assertEqual(chart['n'], len(rows))
        actual = sorted(o.number for o in rows)
        self.assertEqual(Decimal(chart['median']), quantile(actual, '0.5'))
        self.assertEqual({p['code'] for p in chart['values']}, {o.territory.code for o in rows})

    def test_authenticated_html_json_csv_and_new_chart_payload_agree(self):
        import csv, io
        from django.contrib.auth import get_user_model
        from .models import Observation
        user = get_user_model().objects.create_superuser('chart-test', 'chart@example.test', None)
        self.client.force_login(user)
        scopes = [set(Observation.objects.filter(indicator__file_id='43537', period__code=period,
                    territory__kind='subject').values_list('territory__code', flat=True)) for period in ('2013', '2014')]
        codes = sorted(scopes[0] & scopes[1])[:5]
        query = 'program=housing&mode=one&indicator=43537&level=subject&periods=2013&periods=2014' + ''.join('&regions='+code for code in codes)
        html = self.client.get('/explore/?'+query)
        self.assertEqual(html.status_code, 200)
        self.assertContains(html, 'id="dumbbell-chart"')
        self.assertContains(html, 'id="boxplot-chart"')
        self.assertContains(html, 'data-export="dumbbell-chart"')
        json = self.client.get('/explore/?'+query+'&format=json').json()
        self.assertEqual(json['analytics'], html.context['analytics'])
        self.assertEqual(json['analytics']['selected_count'], 10)
        csv_response = self.client.get('/explore/?'+query+'&format=csv')
        self.assertEqual(len(list(csv.reader(io.StringIO(csv_response.content.decode('utf-8-sig')), delimiter=';')))-1, 10)
        scatter_response = self.client.get('/explore/?program=housing&mode=all&level=subject&periods=2014&scatter_x=43512&scatter_y=43537')
        self.assertContains(scatter_response, 'id="scatter-chart"')
