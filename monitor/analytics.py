"""Comparable chart datasets derived only from the shared, filtered observations.

Decimal arithmetic remains on the server. JavaScript converts values solely for
canvas coordinates, never for reported deltas, quantiles or fences.
"""
from collections import defaultdict
from decimal import Decimal, localcontext
from .dimensions import dimension_info


def _number(row):
    return row.number


def _text(number):
    return str(number) if number is not None else None


def _period_kind(period):
    return 'quarter' if '-Q' in period.code else 'year'


def _signature(row):
    # Unit and precision belong to their own axis, PERIOD is carried by the
    # actual period (annual/quarter); all other dimensions must agree.
    dims = [(k, str(v)) for k, v in row.dimensions.items()
            if k not in ('EI', 'UNIT_MULT', 'DECIMALS', 'PERIOD')]
    # Normalise only the named quarters of one period type. Keep other source
    # period categories distinct even if they happen to have a year-like Time.
    period_type = row.dimensions.get('PERIOD', '')
    if '-Q' in row.period.code:
        period_type = 'quarter'
    dims.append(('_period_type', period_type))
    dims.append(('_s_OKFS_state', dimension_info(row)['state']))
    return tuple(sorted(dims))


def _unit(row):
    unit = row.dimensions.get('EI', row.indicator.unit)
    mult = row.dimensions.get('UNIT_MULT')
    return unit + (' · множитель ' + str(mult) if mult else '')


def _cohort_label(row):
    labels = [row.dimension_labels.get(k, str(v)) + ' [' + str(v) + ']'
              for k, v in _signature(row) if not k.startswith('_')]
    if 's_OKFS' not in row.dimensions:
        labels.append('измерение ОКФС отсутствует')
    elif row.dimensions['s_OKFS'] == '':
        labels.append('ОКФС: пропуск')
    elif dimension_info(row)['state'] == 'unknown':
        labels.append('код ОКФС не подтверждён справочником')
    return '; '.join(labels)


def _guard(rows, require_one=True):
    if not rows:
        return 'В выборке нет наблюдений. Измените общие фильтры.'
    if len({r.territory.kind for r in rows}) != 1:
        return 'Выберите один уровень территории: страна, округ, субъект или город. Разные уровни не образуют одну совокупность.'
    if rows[0].territory.kind in ('unknown', 'aggregate'):
        return 'Для сравнения выберите определённый уровень территории: субъекты, округа, города или страну.'
    if require_one and len({r.indicator.file_id for r in rows}) != 1:
        return 'Для этого графика выберите режим «Один показатель».'
    if len({dict(_signature(r))['_period_type'] for r in rows}) != 1:
        return 'Годовое и квартальное наблюдение, а также другие разные типы периода, нельзя объединять в один график.'
    if require_one and len({_unit(r) for r in rows}) != 1:
        return 'Выберите одну единицу измерения и один множитель.'
    if len({_signature(r) for r in rows}) != 1:
        return 'Выберите одну форму собственности и одну комбинацию остальных измерений. Категории ОКФС, включая 199 и 200, не объединяются.'
    return ''


def _territories(rows, params):
    territories = {r.territory.code: r.territory.name for r in rows}
    for code in params.getlist('regions'):
        territories.setdefault(code, code)
    return territories


def _indexed(rows):
    result = defaultdict(list)
    for row in rows:
        result[(row.territory.code, row.period.code)].append(row)
    return result


def _single(rows):
    return rows[0] if len(rows) == 1 else None


def dumbbell(rows, params):
    result = {'reason': _guard(rows), 'points': [], 'excluded': [], 'n': 0}
    if result['reason']:
        return result
    periods = sorted({r.period.code: r.period for r in rows}.values(), key=lambda p: p.order)
    first = params.get('compare_start') or periods[0].code
    last = params.get('compare_end') or periods[-1].code
    selected = {p.code: p for p in periods}
    if first not in selected or last not in selected:
        result['reason'] = 'Оба периода сравнения должны входить в общую выборку таблицы и CSV.'
        return result
    if first == last:
        result['reason'] = 'Выберите два разных периода для сравнения.'
        return result
    if _period_kind(selected[first]) != _period_kind(selected[last]):
        result['reason'] = 'Годовое и квартальное наблюдение нельзя сравнивать как два периода одного ряда.'
        return result
    index = _indexed(rows)
    percentage = '%' in _unit(rows[0]) or 'процент' in _unit(rows[0]).lower()
    result.update(start=selected[first].label, end=selected[last].label,
                  start_code=first, end_code=last, unit=_unit(rows[0]),
                  change_unit='п.п.' if percentage else _unit(rows[0]),
                  title=rows[0].indicator.name, cohort=_cohort_label(rows[0]))
    for code, name in sorted(_territories(rows, params).items(), key=lambda item: item[1]):
        a, b = _single(index[(code, first)]), _single(index[(code, last)])
        if len(index[(code, first)]) > 1 or len(index[(code, last)]) > 1:
            result['reason'] = 'Несколько наблюдений для одной территории и периода. Уточните измерения.'
            result['points'] = []
            return result
        if a is None or b is None or _number(a) is None or _number(b) is None:
            result['excluded'].append({'code': code, 'name': name, 'reason': 'нет числового значения в одном или обоих периодах'})
            continue
        result['points'].append({'code': code, 'name': name, 'start': _text(_number(a)),
                                 'end': _text(_number(b)), 'change': format((_number(b) - _number(a)).normalize(),'f')})
    result['n'] = len(result['points'])
    if not result['n']:
        result['reason'] = 'Нет территорий с числовыми значениями в обоих периодах. Пропуски не заменены нулями.'
    elif result['n'] > 80:
        result['reason'] = 'Для читаемого сравнения оставьте не более 80 территорий в общей выборке.'
    return result


def scatter(rows, params):
    result = {'reason': '', 'points': [], 'excluded': [], 'n': 0}
    if not rows:
        result['reason'] = 'В выборке нет наблюдений.'
        return result
    indicators = sorted({r.indicator.file_id for r in rows})
    x = params.get('scatter_x') or indicators[0]
    y = params.get('scatter_y') or (indicators[1] if len(indicators) > 1 else x)
    if x == y:
        result['reason'] = 'Включите режим «Все показатели программы» и выберите два разных показателя для осей X и Y.'
        return result
    selected = [r for r in rows if r.indicator.file_id in (x, y)]
    if set(r.indicator.file_id for r in selected) != {x, y}:
        result['reason'] = 'Оба показателя должны входить в общую выборку таблицы и CSV. Включите режим «Все показатели программы».'
        return result
    periods = sorted({r.period.code: r.period for r in selected}.values(), key=lambda p: p.order)
    common = set(r.period.code for r in selected if r.indicator.file_id == x) & set(r.period.code for r in selected if r.indicator.file_id == y)
    period = params.get('chart_period') or next((p.code for p in reversed(periods) if p.code in common), periods[-1].code)
    current = [r for r in selected if r.period.code == period]
    xr = [r for r in current if r.indicator.file_id == x]
    yr = [r for r in current if r.indicator.file_id == y]
    if not xr or not yr:
        result['reason'] = 'В выбранном периоде нет данных для одной из осей. Год и квартал не подменяются друг другом.'
        return result
    reason = _guard(xr) or _guard(yr) or _guard(current, require_one=False)
    if reason:
        result['reason'] = reason
        return result
    index_x, index_y = _indexed(xr), _indexed(yr)
    result.update(x_id=x, y_id=y, x_title=xr[0].indicator.name, y_title=yr[0].indicator.name,
                  x_unit=_unit(xr[0]), y_unit=_unit(yr[0]), period=current[0].period.label,
                  period_code=period, cohort=_cohort_label(xr[0]))
    for code, name in sorted(_territories(selected, params).items(), key=lambda item: item[1]):
        a, b = _single(index_x[(code, period)]), _single(index_y[(code, period)])
        if len(index_x[(code, period)]) > 1 or len(index_y[(code, period)]) > 1:
            result['reason'] = 'Несколько значений одной оси для территории. Уточните дополнительные измерения.'
            result['points'] = []
            return result
        if a is None or b is None or _number(a) is None or _number(b) is None:
            missing = []
            if a is None or _number(a) is None: missing.append('X')
            if b is None or _number(b) is None: missing.append('Y')
            result['excluded'].append({'code': code, 'name': name, 'reason': 'нет числового значения ' + ' и '.join(missing)})
            continue
        result['points'].append({'code': code, 'name': name, 'x': _text(_number(a)), 'y': _text(_number(b))})
    result['n'] = len(result['points'])
    if result['n'] < 2:
        result['reason'] = 'Для диаграммы рассеяния нужны минимум две сопоставимые территории с обеими величинами.'
    return result


def quantile(sorted_values, probability):
    """R-7 linear interpolation at (n - 1) p, computed with Decimal."""
    position = Decimal(len(sorted_values) - 1) * Decimal(str(probability))
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def boxplot(rows, params):
    result = {'reason': '', 'excluded': [], 'n': 0, 'outliers': [], 'values': []}
    if not rows:
        result['reason'] = 'В выборке нет наблюдений.'
        return result
    periods = sorted({r.period.code: r.period for r in rows}.values(), key=lambda p: p.order)
    period = params.get('chart_period') or periods[-1].code
    current = [r for r in rows if r.period.code == period]
    result['reason'] = _guard(current)
    if result['reason']:
        return result
    counts = defaultdict(int)
    for row in current: counts[row.territory.code] += 1
    if any(n > 1 for n in counts.values()):
        result['reason'] = 'Для распределения требуется одно наблюдение на территорию. Уточните измерения.'
        return result
    for code, name in sorted(_territories(rows, params).items(), key=lambda item: item[1]):
        row = next((r for r in current if r.territory.code == code), None)
        if row is None or _number(row) is None:
            result['excluded'].append({'code': code, 'name': name, 'reason': 'нет числового значения в выбранном периоде'})
        else:
            result['values'].append({'code': code, 'name': name, 'value': _text(_number(row))})
    nums = sorted(Decimal(p['value']) for p in result['values'])
    result['n'] = len(nums)
    result.update(title=current[0].indicator.name, unit=_unit(current[0]),
                  period=current[0].period.label, period_code=period, cohort=_cohort_label(current[0]))
    if len(nums) < 4:
        result['reason'] = 'Для распределения нужны минимум четыре сопоставимые территории с числовыми значениями.'
        return result
    q1, median, q3 = (quantile(nums, p) for p in ('0.25', '0.5', '0.75'))
    iqr = q3 - q1
    lower, upper = q1 - Decimal('1.5') * iqr, q3 + Decimal('1.5') * iqr
    within = [v for v in nums if lower <= v <= upper]
    result.update(q1=_text(q1), median=_text(median), q3=_text(q3), iqr=_text(iqr),
                  lower_fence=_text(lower), upper_fence=_text(upper),
                  low=_text(within[0]), high=_text(within[-1]), minimum=_text(nums[0]), maximum=_text(nums[-1]))
    result['outliers'] = [point for point in result['values'] if Decimal(point['value']) < lower or Decimal(point['value']) > upper]
    return result


def advanced_charts(rows, params):
    """No extra database query or aggregation: only the table/CSV row set."""
    # Permit exact subtraction/interpolation beyond Decimal's default 28 digits.
    numbers = [r.number for r in rows if r.number is not None]
    if any(v and (v.adjusted() > 307 or v.adjusted() < -307) for v in numbers):
        reason = 'Значение выходит за поддерживаемый числовой диапазон canvas. Точные исходные значения доступны в таблице и CSV.'
        return {**{name: {'reason': reason, 'excluded': [], 'points': [], 'n': 0}
                   for name in ('dumbbell', 'scatter', 'boxplot')}, 'selected_count': len(rows)}
    width = max((len(v.as_tuple().digits) + abs(v.as_tuple().exponent) + abs(v.adjusted()) for v in numbers), default=28)
    with localcontext() as ctx:
        ctx.prec = max(80, width + 20)
        return {'dumbbell': dumbbell(rows, params), 'scatter': scatter(rows, params),
                'boxplot': boxplot(rows, params), 'selected_count': len(rows)}
