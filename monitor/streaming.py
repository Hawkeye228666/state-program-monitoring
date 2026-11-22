"""Bounded disk/stream reader for the supplied EMISS GenericData SDMX 1.0.

ZIPs are streamed into private temporary files, XML into content-addressed sources.
Only one bounded Series and embedded dictionaries are retained in memory.
"""
import calendar,hashlib,json,os,re,shutil,tempfile,zipfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path,PurePosixPath
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError
from django.conf import settings
from .sdmx import NS,M,G,S,DataError,values,LABELS

def limit(name,default):return int(getattr(settings,'SDMX_'+name,os.environ.get('SDMX_'+name,default)))
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def safe_path(name):
    name=name.replace('\\','/')
    if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or ':' in name or '\x00' in name:
        raise DataError('Опасный путь ZIP: '+name)
    return name

@dataclass
class Source:
    filename:str
    path:Path
    sha256:str
    size:int

def extract_sources(paths,root=None):
    root=Path(root or settings.MEDIA_ROOT)/'sources';root.mkdir(parents=True,exist_ok=True)
    state={'bytes':0,'entries':0}
    def copy(src,dst,maximum):
        count=0;h=hashlib.sha256()
        while chunk:=src.read(1024*1024):
            count+=len(chunk);state['bytes']+=len(chunk)
            if count>maximum or state['bytes']>limit('MAX_EXPANDED',8*1024**3):raise DataError('Превышен распакованный объём SDMX.')
            dst.write(chunk);h.update(chunk)
        return count,h.hexdigest()
    def visit(name,stream,depth):
        safe_path(name);state['entries']+=1
        if depth>limit('MAX_ARCHIVE_DEPTH',3) or state['entries']>limit('MAX_ENTRIES',256):raise DataError('Превышена глубина или число файлов ZIP.')
        ext=Path(name).suffix.lower()
        if ext=='.zip':
            with tempfile.TemporaryFile(dir=root) as temp:
                copy(stream,temp,limit('MAX_UPLOAD',128*1024**2));temp.seek(0)
                try:
                    with zipfile.ZipFile(temp) as z:
                        for item in z.infolist():
                            safe_path(item.filename)
                            if item.is_dir():continue
                            if item.flag_bits&1 or (item.external_attr>>16)&0o170000==0o120000:raise DataError('Зашифрованные ZIP и символические ссылки запрещены.')
                            with z.open(item) as child:yield from visit(item.filename,child,depth+1)
                except (zipfile.BadZipFile,RuntimeError,NotImplementedError) as error:raise DataError('Повреждённый ZIP.') from error
        elif ext in ('.xml','.sdmx'):
            fd,tempname=tempfile.mkstemp(dir=root,suffix='.partial')
            try:
                with os.fdopen(fd,'wb') as temp:size,sha=copy(stream,temp,limit('MAX_XML',512*1024**2))
                target=root/(sha+'.sdmx')
                if target.exists():os.unlink(tempname)
                else:os.replace(tempname,target)
                yield Source(Path(name).name,target,sha,size)
            finally:
                if os.path.exists(tempname):os.unlink(tempname)
        else:raise DataError('Неподдерживаемый файл '+name)
    for path in paths:
        path=Path(path)
        if path.stat().st_size>limit('MAX_UPLOAD',128*1024**2):raise DataError('Превышен размер загрузки. Настройте SDMX_MAX_UPLOAD.')
        with path.open('rb') as f:yield from visit(path.name,f,0)

def events(path):
    stack=[];series_obs=0
    try:
        for event,e in ET.iterparse(path,events=('start','end'),forbid_dtd=True,forbid_entities=True,forbid_external=True):
            if event=='start':
                stack.append(e)
                if len(stack)>limit('MAX_XML_DEPTH',64):raise DataError('Слишком глубокий XML.')
                if len(stack)==1 and e.tag!='{'+M+'}GenericData':raise DataError('Поддерживается только ЕМИСС GenericData SDMX 1.0.')
                if e.tag=='{'+G+'}Obs':
                    series_obs+=1
                    if series_obs>limit('MAX_SERIES_OBS',4096):raise DataError('Слишком много Obs в одном Series; неподдерживаемая структура.')
            else:
                yield e,stack[-2] if len(stack)>1 else None
                if e.tag in ('{'+G+'}Series','{'+S+'}CodeList','{'+M+'}Indicator'):
                    if len(stack)>1:stack[-2].remove(e)
                    e.clear();series_obs=0
                stack.pop()
    except (DefusedXmlException,ParseError,ValueError) as error:raise DataError('Небезопасный/повреждённый XML: '+str(error)) from error

def metadata(source):
    info={'file_id':'','name':'','metadata':{},'codelists':{},'names':dict(LABELS),'header_id':'','dataset_id':''}
    for e,parent in events(source.path):
        if e.tag=='{'+M+'}Header':
            info['header_id']=e.findtext('m:ID','',NS);info['dataset_id']=e.findtext('m:DataSetID','',NS)
            info['metadata']['prepared']=e.findtext('m:Prepared','',NS)
        elif e.tag=='{'+M+'}Indicator':
            info.update(file_id=e.attrib.get('id',''),name=e.attrib.get('name',''))
            unit=e.find('m:Units/m:Unit',NS);info['unit']=unit.attrib.get('value','') if unit is not None else ''
            for key,tag in [('methodology','Methodology'),('organization','Organization'),('comment','Comment')]:
                element=e.find('m:'+tag,NS);info['metadata'][key]=element.attrib.get('value','') if element is not None else ''
            info['metadata']['forms']=[{'code':x.attrib.get('value',''),'name':x.findtext('m:Name','',NS)} for x in e.findall('m:Forms/m:Form',NS)]
            info['metadata']['declared_dimensions']=[x.attrib['value'] for x in e.findall('m:Dimensions/m:Dimension',NS)]
            info['metadata']['metadata_xml']=ET.tostring(e,encoding='unicode')
            stated=re.search(r'по\s+(\d{4})\s*г',info['name'])
            data_range=e.find('m:DataRange',NS)
            if stated and data_range is not None and data_range.attrib.get('end','').isdigit() and int(data_range.attrib['end'])>int(stated[1]):
                info['metadata']['diagnostics']=[{'type':'title_range_mismatch','message':'Название источника ограничено '+stated[1]+' г., но DataRange заканчивается '+data_range.attrib['end']+'. Фактические наблюдения не отбрасываются.'}]
        elif e.tag=='{'+S+'}CodeList':
            cid=e.attrib['id'];info['names'][cid]=e.findtext('s:Name',cid,NS)
            info['codelists'][cid]={x.attrib['value']:x.findtext('s:Description',x.attrib['value'],NS) for x in e.findall('s:Code',NS)}
        elif e.tag=='{'+G+'}SeriesKey':
            info['fields']=list(values(parent,'g:SeriesKey/g:Value'));break
    if not info['file_id'] or not info['name'] or 'fields' not in info:raise DataError('Нет Indicator/@id, названия или Generic SeriesKey.')
    info['metadata']['dimension_codelists']={k:v for k,v in info['codelists'].items() if k!='s_OKATO'}
    info['metadata']['classifiers']={k:{'identity':k.removeprefix('s_'),'edition':None,'snapshot':digest(v)} for k,v in info['codelists'].items()}
    return info

ROLES={'territory','dimension','unit','multiplier','period','attribute','status'}
def validate_profile(info,rules=None):
    if rules is None:
        if 's_OKATO' not in info['fields']:raise DataError('Неоднозначная территория: подтвердите профиль сопоставления.')
        rules={k:{'role':'territory' if k=='s_OKATO' else 'dimension','codelist':k,'transform':'identity'} for k in info['fields']}
    if not isinstance(rules,dict):raise DataError('Профиль должен быть объектом JSON.')
    for field,rule in rules.items():
        if not isinstance(rule,dict) or set(rule)-{'role','codelist','transform'} or rule.get('role') not in ROLES or rule.get('transform','identity')!='identity':raise DataError('Профиль: разрешены только известные роли и identity; код не исполняется.')
        if rule.get('codelist',field) not in info['codelists']:raise DataError('Нет указанного справочника: '+field)
    if set(info['fields'])-set(rules):raise DataError('Профиль не определяет все поля SeriesKey.')
    if sum(x['role']=='territory' for x in rules.values())!=1:raise DataError('Профиль должен содержать ровно одну территорию.')
    if 's_OKATO' in info['fields'] and rules.get('s_OKATO',{}).get('role')!='territory':raise DataError('s_OKATO должен оставаться основной территорией; s_OKSM — отдельный разрез.')
    return rules

MONTHS=['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь']
def period_info(time,kind):
    if not re.fullmatch(r'\d{4}(?:-Q[1-4])?',time):raise DataError('Неподдерживаемое Time: '+time)
    year=int(time[:4]);q={'I квартал':1,'II квартал':2,'III квартал':3,'IV квартал':4}.get(kind)
    if '-Q' in time:
        actual=int(time[-1])
        if q and q!=actual:raise DataError('Time и PERIOD задают разные кварталы.')
        q=actual
    if q:
        return {'code':f'{year}-Q{q}','label':f'{year}, {q} квартал','year':year,'order':f'{year}-Q{q}','kind':'quarter','start':date(year,3*q-2,1),'end':date(year,3*q,calendar.monthrange(year,3*q)[1]),'cumulative':False,'original':kind or time}
    clean=kind.lower().replace('–','-').replace('—','-').replace(' ','').strip()
    end=None
    if clean=='январь':end=1
    elif clean.startswith('январь-') and clean[7:] in MONTHS:end=MONTHS.index(clean[7:])+1
    if end:
        return {'code':f'{year}-YTD{end:02}','label':f'{year}, {kind}','year':year,'order':f'{year}-Y{end:02}','kind':'cumulative','start':date(year,1,1),'end':date(year,end,calendar.monthrange(year,end)[1]),'cumulative':True,'original':kind}
    if clean not in ('','значениепоказателязагод','год','годовая','январь-декабрь'):
        raise DataError('Неподдерживаемый PERIOD: '+kind)
    return {'code':str(year),'label':str(year),'year':year,'order':f'{year}-00','kind':'year','start':date(year,1,1),'end':date(year,12,31),'cumulative':False,'original':kind or time}

def rows(source,info,rules=None):
    rules=validate_profile(info,rules);lists=info['codelists'];declared=info['metadata']['declared_dimensions'];dsattrs={}
    for e,parent in events(source.path):
        if e.tag=='{'+G+'}Attributes' and parent is not None and parent.tag=='{'+M+'}DataSet':dsattrs=values(parent,'g:Attributes/g:Value')
        if e.tag!='{'+G+'}Series':continue
        keys=values(e,'g:SeriesKey/g:Value');attrs=dsattrs|values(e,'g:Attributes/g:Value')
        territory_field=next(k for k,v in rules.items() if v['role']=='territory')
        territory=keys.get(territory_field,'')
        if not territory:raise DataError('Отсутствует основная территория: '+territory_field)
        for obs in e.findall('g:Obs',NS):
            a=attrs|values(obs,'g:Attributes/g:Value')
            for key,rule in rules.items():
                role=rule['role']
                if role in ('attribute','status'):a[key]=keys.get(key,'')
                elif role in ('unit','multiplier','period'):a[{'unit':'EI','multiplier':'UNIT_MULT','period':'PERIOD'}[role]]=keys.get(key,'')
            time=obs.findtext('g:Time','',NS).strip();period=period_info(time,a.get('PERIOD',''))
            dims={k:v for k,v in keys.items() if rules[k]['role']=='dimension'}
            for key in declared:
                if key!=territory_field and rules.get(key,{'role':'dimension'})['role']=='dimension':dims.setdefault(key,'')
            if 's_OKFS' in a:dims['s_OKFS']=a['s_OKFS']
            dims.update({k:v for k,v in a.items() if k in ('EI','PERIOD','UNIT_MULT','DECIMALS','FREQ')})
            labels={};states={}
            for k,v in dims.items():
                dictionary=rules.get(k,{}).get('codelist',k);label=lists.get(dictionary,{}).get(v,v)
                state='missing' if v=='' else ('known' if v in lists.get(dictionary,{}) or k in ('EI','PERIOD','UNIT_MULT','DECIMALS','FREQ') else 'unknown')
                if label and (re.search(r'(^|\s)(итого|всего|итог)(\s|:|\(|$)',label.lower()) or label.lower().startswith('всего')):state='aggregate'
                states[k]=state;labels[k]=(info['names'].get(dictionary,k)+' / '+label) if k.startswith('s_') else label
            for k in declared:
                if k!=territory_field:states.setdefault(k,'missing')
            value=obs.find('g:ObsValue',NS);raw=value.attrib.get('value','') if value is not None else '';num=None
            try:
                n=Decimal(raw.replace(' ','').replace('\xa0','').replace(',','.'))
                if n.is_finite():
                    parts=n.as_tuple();digits=list(parts.digits);exponent=parts.exponent
                    while digits and digits[-1]==0:digits.pop();exponent+=1
                    if n.adjusted()>=50 or (digits and exponent < -30):raise DataError('Значение превышает NUMERIC(80,30).')
                    num=str(n)
            except InvalidOperation:pass
            status={k:v for k,v in a.items() if k not in dims}
            if value is not None:status.update({k:v for k,v in value.attrib.items() if k!='value'})
            yield {'territory':territory,'territory_name':lists.get(rules[territory_field].get('codelist',territory_field),{}).get(territory,territory),'period':period,'dimensions':dims,'dimension_labels':labels,'dimension_key':digest(dims),'dimension_states':states,'numeric_value':num,'raw_value':raw,'status':status,'attributes':a}
