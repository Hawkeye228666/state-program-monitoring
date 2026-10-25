"""ЕМИСС SDMX 1.0 GenericData, встроенные CodeLists и Description/Indicator."""
import hashlib, io, json, re, zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError

MAX_UPLOAD=20*1024*1024
MAX_EXPANDED=80*1024*1024
MAX_XML=15*1024*1024
MAX_DEPTH=3
MAX_ENTRIES=100
M='http://www.SDMX.org/resources/SDMXML/schemas/v1_0/message'
G='http://www.SDMX.org/resources/SDMXML/schemas/v1_0/generic'
S='http://www.SDMX.org/resources/SDMXML/schemas/v1_0/structure'
NS={'m':M,'g':G,'s':S}
LABELS={'EI':'Единица измерения','PERIOD':'Вид периода','UNIT_MULT':'Множитель','s_OKFS':'Форма собственности (ОКФС)'}
class DataError(ValueError): pass

@dataclass
class Document:
    filename:str
    content:bytes
    file_id:str
    metadata_id:str
    header_id:str
    dataset_id:str
    name:str
    unit:str
    metadata:dict
    codelists:dict
    dimension_names:dict
    rows:list
    series_count:int
    sha256:str
    @property
    def territories(self): return len({x['territory'] for x in self.rows})
    @property
    def periods(self): return sorted({x['period'] for x in self.rows})

def unpack_uploads(files):
    """Возвращает документы в памяти. Ничего не распаковывает на диск."""
    state={'bytes':0,'entries':0,'upload':0}; result=[]
    def visit(name,data,depth=0):
        clean=name.replace('\\','/')
        p=PurePosixPath(clean)
        if p.is_absolute() or '..' in p.parts or ':' in clean or '\x00' in clean: raise DataError('Опасный путь в архиве: '+name)
        if depth>MAX_DEPTH: raise DataError('Превышена глубина вложенных архивов (3).')
        state['entries']+=1
        if state['entries']>MAX_ENTRIES: raise DataError('В архиве более 100 файлов.')
        ext=p.suffix.lower()
        if ext=='.zip':
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for item in z.infolist():
                        if item.is_dir(): continue
                        if item.flag_bits & 1: raise DataError('Зашифрованные ZIP не поддерживаются.')
                        if item.file_size>MAX_XML or state['bytes']+item.file_size>MAX_EXPANDED: raise DataError('Превышен лимит распакованных данных (80 МБ) или файла (15 МБ).')
                        state['bytes']+=item.file_size
                        n=item.filename
                        if not item.flag_bits & 0x800:
                            try: n=n.encode('cp437').decode('cp866')
                            except (UnicodeError,LookupError): pass
                        payload=z.read(item)
                        if len(payload)!=item.file_size: raise DataError('Неверный размер элемента ZIP.')
                        visit(n,payload,depth+1)
            except (zipfile.BadZipFile,RuntimeError,NotImplementedError) as e: raise DataError('Повреждённый или неподдерживаемый ZIP.') from e
        elif ext in ('.xml','.sdmx'):
            if len(data)>MAX_XML: raise DataError('Размер XML превышает 15 МБ.')
            result.append(parse_document(p.name,data))
        else: raise DataError('Неподдерживаемый файл: '+name+'. Разрешены ZIP, SDMX и XML.')
    for name,data in files:
        state['upload']+=len(data)
        if state['upload']>MAX_UPLOAD: raise DataError('Общий размер загрузки превышает 20 МБ.')
        visit(name,data)
    if not result: raise DataError('В загрузке нет файлов SDMX/XML.')
    return result

def values(node,path):
    if node is None:return {}
    return {v.attrib['concept']:v.attrib.get('value','') for v in node.findall(path,NS)}

def parse_document(filename,content):
    if len(content)>MAX_XML: raise DataError('XML превышает 15 МБ.')
    try: root=ET.fromstring(content,forbid_dtd=True,forbid_entities=True,forbid_external=True)
    except (DefusedXmlException,ParseError,ValueError) as e: raise DataError('Небезопасный или повреждённый XML: '+str(e)) from e
    if root.tag!='{'+M+'}GenericData': raise DataError('Поддерживается только GenericData SDMX 1.0 (ЕМИСС).')
    indicator=root.find('m:Description/m:Indicator',NS); dataset=root.find('m:DataSet',NS)
    if indicator is None or dataset is None: raise DataError('Нет Description/Indicator или DataSet.')
    metadata_id=indicator.attrib.get('id','')
    match=re.search(r'data_(\d+)',filename)
    file_id=match.group(1) if match else metadata_id
    if not file_id: raise DataError('Не определён идентификатор показателя.')
    if match and metadata_id and file_id!=metadata_id: raise DataError('Идентификатор в имени файла не совпадает с Description/Indicator/@id.')
    name=indicator.attrib.get('name') or 'Название отсутствует в метаданных ('+file_id+')'
    lists={}; names=dict(LABELS)
    for cl in root.findall('m:CodeLists/s:CodeList',NS):
        cid=cl.attrib['id']; names[cid]=cl.findtext('s:Name',default=cid,namespaces=NS)
        lists[cid]={c.attrib['value']:c.findtext('s:Description',default=c.attrib['value'],namespaces=NS) for c in cl.findall('s:Code',NS)}
    def val(tag):
        e=indicator.find('m:'+tag,NS)
        return e.attrib.get('value','') if e is not None else ''
    forms=[{'code':e.attrib.get('value',''),'name':e.findtext('m:Name',default='',namespaces=NS)} for e in indicator.findall('m:Forms/m:Form',NS)]
    metadata={'methodology':val('Methodology'),'organization':val('Organization'),'department':val('Department'),'comment':val('Comment'),'forms':forms,'metadata_xml':ET.tostring(indicator,encoding='unicode'),'prepared':root.findtext('m:Header/m:Prepared',default='',namespaces=NS),'attributes':{},'dimension_values':{},'missing':0,'special':{},'duplicates':0,'raw_times':[]}
    unit=indicator.find('m:Units/m:Unit',NS)
    unit=unit.attrib.get('value','') if unit is not None else ''
    rows=[]; seen={}; raw_times=set(); series=dataset.findall('g:Series',NS)
    dsattrs=values(dataset,'g:Attributes/g:Value')
    for s in series:
        keys=values(s,'g:SeriesKey/g:Value')
        if not keys.get('s_OKATO'): raise DataError('Ряд не содержит территорию s_OKATO.')
        attrs=dsattrs | values(s,'g:Attributes/g:Value')
        for obs in s.findall('g:Obs',NS):
            a=attrs | values(obs,'g:Attributes/g:Value')
            t=obs.findtext('g:Time',default='',namespaces=NS).strip()
            if not re.fullmatch(r'\d{4}(?:-Q[1-4])?',t): raise DataError('Неподдерживаемое значение Time: '+t)
            raw_times.add(t)
            period=t; plabel=t
            kind=a.get('PERIOD','')
            quarters={'I квартал':1,'II квартал':2,'III квартал':3,'IV квартал':4}
            if kind in quarters and len(t)==4: period=f'{t}-Q{quarters[kind]}'; plabel=f'{t}, {kind}'
            dims={k:v for k,v in keys.items() if k!='s_OKATO'}
            # Значимые атрибуты входят в ключ, статусы остаются изменяемыми данными.
            dims.update({k:v for k,v in a.items() if k in ('EI','PERIOD','UNIT_MULT','DECIMALS','FREQ')})
            canonical=json.dumps(dims,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            fingerprint=hashlib.sha256(canonical.encode()).hexdigest()
            value=obs.find('g:ObsValue',NS)
            raw=value.attrib.get('value','') if value is not None else ''
            status={k:v for k,v in a.items() if k not in dims}
            if value is not None: status.update({k:v for k,v in value.attrib.items() if k!='value'})
            num=None
            try:
                dec=Decimal(raw.strip().replace(' ','').replace('\xa0','').replace(',','.'))
                if dec.is_finite(): num=str(dec)
            except InvalidOperation: pass
            if num is None:
                metadata['missing']+=1; metadata['special'][raw]=metadata['special'].get(raw,0)+1
            labels={k:lists.get(k,{}).get(v,v) for k,v in dims.items()}
            row={'territory':keys['s_OKATO'],'territory_name':lists.get('s_OKATO',{}).get(keys['s_OKATO'],keys['s_OKATO']),'period':period,'period_label':plabel,'year':int(t[:4]),'dimension_key':fingerprint,'dimensions':dims,'dimension_labels':labels,'numeric_text':num,'raw_value':raw,'status':status,'attributes':a}
            identity=(row['territory'],period,fingerprint)
            if identity in seen:
                if seen[identity]!=row: raise DataError('Конфликтующие дубликаты наблюдений в '+filename)
                metadata['duplicates']+=1
            else: seen[identity]=row
            rows.append(row)
            for k,v in a.items(): metadata['attributes'].setdefault(k,set()).add(v)
            for k,v in dims.items(): metadata['dimension_values'].setdefault(k,set()).add(v)
    if not rows: raise DataError('Нет наблюдений в '+filename)
    for k in ('attributes','dimension_values'):metadata[k]={a:sorted(b) for a,b in metadata[k].items()}
    metadata['raw_times']=sorted(raw_times)
    metadata['unit_multiplier']='Явный UNIT_MULT отсутствует; масштаб задаётся текстом EI.' if 'UNIT_MULT' not in metadata['attributes'] else metadata['attributes']['UNIT_MULT']
    return Document(filename,content,file_id,metadata_id,root.findtext('m:Header/m:ID',default='',namespaces=NS),root.findtext('m:Header/m:DataSetID',default='',namespaces=NS),name,unit,metadata,lists,names,rows,len(series),hashlib.sha256(content).hexdigest())
