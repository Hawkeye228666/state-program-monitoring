"""Независимый пересчёт исходных XML для воспроизводимого аудита ОКФС."""
from collections import Counter
from hashlib import sha256
from defusedxml import ElementTree as ET
from .sdmx import NS


def audit_document(filename, content):
    root=ET.fromstring(content,forbid_dtd=True,forbid_entities=True,forbid_external=True)
    fid=root.find('m:Description/m:Indicator',NS).attrib['id']
    codelist={}
    for cl in root.findall('m:CodeLists/s:CodeList',NS):
        if cl.attrib.get('id')=='s_OKFS':
            codelist={e.attrib['value']:e.findtext('s:Description',default=e.attrib['value'],namespaces=NS) for e in cl.findall('s:Code',NS)}
    declared=[e.attrib['value'] for e in root.findall('m:Description/m:Indicator/m:Dimensions/m:Dimension',NS)]
    count=0; codes=Counter(); years=Counter(); periods=Counter(); annual_keys=Counter(); quarter_keys=Counter(); controls=[]; examples={}
    dataset=root.find('m:DataSet',NS)
    def values(node,path):return {e.attrib['concept']:e.attrib.get('value','') for e in node.findall(path,NS)}
    dsattrs=values(dataset,'g:Attributes/g:Value')
    for series in dataset.findall('g:Series',NS):
        keys=values(series,'g:SeriesKey/g:Value');attrs=dsattrs|values(series,'g:Attributes/g:Value')
        for obs in series.findall('g:Obs',NS):
            count+=1; a=attrs|values(obs,'g:Attributes/g:Value')
            time=obs.findtext('g:Time',namespaces=NS);quarter=a.get('PERIOD','');year=time[:4];okfs=keys.get('s_OKFS',a.get('s_OKFS'))
            years[year]+=1;periods[quarter]+=1
            if okfs is not None:
                codes[okfs]+=1;annual_keys[(keys['s_OKATO'],okfs,year)]+=1;quarter_keys[(keys['s_OKATO'],okfs,year,quarter)]+=1
                raw=obs.find('g:ObsValue',NS).attrib.get('value','')
                example={'territory':keys['s_OKATO'],'time':time,'PERIOD':quarter,'value':raw}
                examples.setdefault(okfs,example)
                if keys['s_OKATO']=='643' and year=='2014' and okfs=='200':controls.append(example)
    return {'file':filename,'file_id':fid,'sha256':sha256(content).hexdigest(),'observations':count,'declared_dimensions':declared,'okfs_present':'s_OKFS' in declared or bool(codes),'codelist':codelist,'codes_in_observations':dict(sorted(codes.items())),'unused_codes':sorted(set(codelist)-set(codes)),'years':dict(sorted(years.items())),'periods':dict(sorted(periods.items())),'duplicate_groups_without_quarter':sum(n>1 for n in annual_keys.values()),'duplicate_groups_with_quarter':sum(n>1 for n in quarter_keys.values()),'control_643_2014_200':controls,'examples':examples}
