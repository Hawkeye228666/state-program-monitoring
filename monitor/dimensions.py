"""Состояние измерения отделено от его исходного строкового кода.

Пустое значение объявленного измерения хранится как ''. Отсутствующее
измерение не добавляется в JSON. Ни один из этих случаев не означает 200.
"""

def dimension_info(observation, code='s_OKFS'):
    dims=observation.dimensions
    name='ОКФС' if code=='s_OKFS' else code
    if code not in dims:
        return {'state':'absent','code':None,'label':name+' не применяется (измерение отсутствует)','diagnostic':''}
    raw=dims[code]
    if raw is None or raw=='':
        return {'state':'missing','code':raw,'label':name+' не указан (пропуск)','diagnostic':'Измерение объявлено источником, но значение не заполнено.'}
    source_metadata=observation.source.metadata or {}
    codelists=source_metadata.get('dimension_codelists',{})
    label=observation.dimension_labels.get(code,raw)
    # Старые базы не имели копии справочника в SourceFile.metadata. Исходная
    # подпись подтверждает известный код; повторный импорт дополняет аудит.
    known=(raw in codelists[code]) if code in codelists else label!=raw
    if known:
        return {'state':'known','code':raw,'label':label,'diagnostic':''}
    return {'state':'unknown','code':raw,'label':label,'diagnostic':'Неизвестный код '+name+': '+str(raw)+'. Сохранено исходное значение; соответствие справочнику не подтверждено.'}
