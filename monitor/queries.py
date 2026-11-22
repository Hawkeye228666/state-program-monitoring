"""Единая выборка для HTML, CSV и графиков. Агрегация значений не выполняется."""
from collections import defaultdict
from django.db.models import Q,F
from .models import Observation, Dimension
from .sdmx import DataError
from .dimensions import dimension_info
SORTS={'territory':('territory__name','period__order','indicator__file_id','dimension_key'),'period':('period__order','territory__name','indicator__file_id','dimension_key'),'indicator':('indicator__file_id','territory__name','period__order','dimension_key')}
def select_rows(program,params):
    mode=params.get('mode','one')
    if mode not in ('one','all'):raise DataError('Неизвестный режим запроса.')
    indicators=program.indicators.order_by('file_id')
    chosen=params.get('indicator') or str(indicators.values_list('file_id',flat=True).first() or '')
    if not indicators.exists():return Observation.objects.none(),chosen,mode
    qs=Observation.objects.filter(indicator__program=program).select_related('indicator','territory','period').defer('indicator__metadata','indicator__methodology','indicator__forms').prefetch_related('source')
    if mode=='one':
        if not indicators.filter(file_id=chosen).exists():raise DataError('Показатель не относится к выбранной программе.')
        qs=qs.filter(indicator__file_id=chosen)
    regions=params.getlist('regions'); periods=params.getlist('periods')
    if regions: qs=qs.filter(territory__code__in=regions)
    if periods: qs=qs.filter(period__code__in=periods)
    level=params.get('level','')
    if level: qs=qs.filter(territory__kind=level)
    dims=Dimension.objects.filter(indicator__program=program)
    if mode=='one':dims=dims.filter(indicator__file_id=chosen)
    allowed=set(dims.values_list('code',flat=True))
    for k in params:
        if k.startswith('dim_'):
            code=k[4:]
            if code not in allowed:
                if params.getlist(k):raise DataError('Измерение не относится к выбранным показателям: '+code)
            else:
                vs=[v for v in params.getlist(k) if v!='']
                if vs:
                    condition=Q(pk__in=[])
                    for value in vs:
                        if value=='__absent__':part=~Q(dimensions__has_key=code)
                        elif value=='__missing__':part=Q(**{'dimensions__contains':{code:''}})
                        elif value=='__unknown__':part=Q(dimension_states__contains={code:'unknown'}) | (Q(dimension_states={}) & ~Q(dimensions__contains={code:''}) & Q(**{'dimension_labels__'+code:F('dimensions__'+code)}))
                        elif value=='__aggregate__':part=Q(dimension_states__contains={code:'aggregate'})
                        else:part=Q(dimensions__contains={code:value})
                        condition |= part
                    qs=qs.filter(condition)
    sort=params.get('sort','territory')
    rows=qs.order_by(*SORTS.get(sort,SORTS['territory']))
    if sort in ('value','-value'):
        rows=qs.order_by(F('numeric_value').desc(nulls_last=True) if sort=='-value' else F('numeric_value').asc(nulls_last=True),'pk')
    return rows,chosen,mode

def chart_data(rows,bar_period=''):
    result={'reason':'','heat_reason':'','line':{},'bar':{},'heat':[],'labels':[],'count':len(rows)}
    if not rows:result['reason']='В выборке нет данных. Измените периоды, территории или измерения.';return result
    if len({o.indicator_id for o in rows})!=1:result['reason']='Для графика выберите режим «Один показатель». Показатели с разными единицами не объединяются.';return result
    if len({o.territory.kind for o in rows})!=1:result['reason']='Выберите один уровень территории. Страна, округа, субъекты и города не смешиваются на одном графике.';return result
    period_kinds={(o.period.kind,int(o.period.start.month) if o.period.start else 0,int(o.period.end.month) if o.period.end else 0) if o.period.kind=='cumulative' else ('quarter' if '-Q' in o.period.code else 'year') for o in rows}
    if len(period_kinds)!=1:result['reason']='Годовые и квартальные данные не объединяются в один график.';return result
    okfs={o.dimensions.get('s_OKFS') for o in rows}
    if okfs & {'199','200'} and len(okfs)>1:result['reason']='Выберите одну категорию ОКФС: итоги 199 и 200 и отдельные формы собственности не смешиваются.';return result
    if len({(o.dimensions.get('EI'),o.dimensions.get('UNIT_MULT','')) for o in rows})!=1:result['reason']='Выберите одну единицу измерения и один множитель.';return result
    periods=sorted({o.period.code:o.period for o in rows}.values(),key=lambda p:p.order)
    result['labels']=[p.label for p in periods]; codes=[p.code for p in periods]
    groups=defaultdict(dict); cells=defaultdict(list); names={}
    for o in rows:
        extras=tuple(sorted((k,v) for k,v in o.dimensions.items() if k not in ('PERIOD','EI')))
        key=(o.territory.code,extras)
        extra_label='; '.join(o.dimension_labels.get(k,v) for k,v in extras)
        names[key]=o.territory.name+(' / '+extra_label if extra_label else '')
        if o.period.code in groups[key]:result['reason']='Несколько значений в одной точке. Уточните измерения.';return result
        groups[key][o.period.code]=o
        cells[(o.territory.code,o.period.code)].append(o)
    if len(groups)>12:result['reason']='В выборке более 12 рядов. Оставьте до 12 территорий и комбинаций измерений для читаемого графика.';return result
    result['unit']=rows[0].dimensions.get('EI',rows[0].indicator.unit);result['title']=rows[0].indicator.name
    result['line']={'labels':result['labels'],'datasets':[{'label':names[key],'data':[g[c].numeric_text if c in g else None for c in codes]} for key,g in groups.items()]}
    if bar_period and bar_period not in codes:result['reason']='Период сравнения отсутствует в выборке.';return result
    selected=bar_period or codes[-1];result['bar_period']=selected
    result['bar']={'labels':[names[k] for k in groups],'datasets':[{'label':next(p.label for p in periods if p.code==selected),'data':[g[selected].numeric_text if selected in g else None for g in groups.values()]}]}
    territories=sorted({o.territory.code:o.territory for o in rows}.values(),key=lambda t:t.name)
    if any(len(v)>1 for v in cells.values()):result['heat_reason']='Тепловая карта требует одно значение на регион и период. Выберите одну форму собственности или другие дополнительные измерения.'
    elif len(territories)>50 or len(periods)>30:result['heat_reason']='Для тепловой карты оставьте не более 50 территорий и 30 периодов.'
    else:
        nums=[o.number for o in rows if o.number is not None];lo=min(nums) if nums else 0;hi=max(nums) if nums else 0
        for t in territories:
            vals=[]
            for pc in codes:
                o=cells.get((t.code,pc),[None])[0];number=o.number if o else None
                intensity=0 if number is None else (0.5 if hi==lo else float((number-lo)/(hi-lo)))
                vals.append({'text':o.display if o else 'нет данных','color':'#f0f2f5' if number is None else f'hsl(213 75% {96-intensity*55:.0f}%)','dark':intensity>.65})
            result['heat'].append({'name':t.name,'values':vals})
        result['range']=[str(lo),str(hi)]
    return result
