/* The same filtered server rows feed charts, table and CSV. */
(()=>{
'use strict';
if(!window.Chart)return;
const parse=id=>{const n=document.getElementById(id);return n?JSON.parse(n.textContent):null;};
const p=parse('chart-data'),a=parse('analytics-data'),charts={};
const colors=['#245ec7','#16a085','#de8e28','#8653bd','#d05279','#4c9fb8','#73644a','#ad5271','#4d745c','#7886cc','#ca6c42','#596773'];
const short=(s,n=65)=>s.length>n?s.slice(0,n-1)+'…':s;
Chart.register({id:'paper',beforeDraw(c){const x=c.ctx;x.save();x.fillStyle='#fff';x.fillRect(0,0,c.width,c.height);x.restore();}});
const create=(id,cfg)=>{const el=document.getElementById(id);if(!el)return null;cfg.options={responsive:true,maintainAspectRatio:false,animation:false,...cfg.options};return charts[id]=new Chart(el,cfg);};
const caption=(title,subtitle)=>({title:{display:true,text:short(title,110),font:{size:13},padding:10},subtitle:{display:true,text:short(subtitle,130),font:{size:11},padding:{bottom:14}}});
if(p&&!p.reason){
 const convert=raw=>({labels:raw.labels,datasets:raw.datasets.map((d,i)=>({...d,data:d.data.map(v=>v===null?null:Number(v)),borderColor:colors[i%colors.length],backgroundColor:colors[i%colors.length],borderWidth:2,pointRadius:3,spanGaps:false}))});
 const opts={interaction:{mode:'index',intersect:false},plugins:{...caption(p.title,p.unit),legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}},tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.raw===null?'нет данных':c.raw)+' '+p.unit}}},scales:{y:{title:{display:true,text:p.unit},grid:{color:'#e9edf4'}},x:{grid:{display:false},ticks:{font:{size:10}}}}};
 create('line-chart',{type:'line',data:convert(p.line),options:opts});
 const bar=create('bar-chart',{type:'bar',data:convert(p.bar),options:{...opts,plugins:{...opts.plugins,...caption(p.title,p.bar.datasets[0].label+' · '+p.unit)}}});
 const select=document.getElementById('bar-period');
 if(select&&bar){const ix=p.labels.indexOf(p.bar.datasets[0].label);select.value=String(ix<0?p.labels.length-1:ix);select.addEventListener('change',()=>{const i=Number(select.value);bar.data={labels:p.line.datasets.map(d=>d.label),datasets:[{label:p.labels[i],data:p.line.datasets.map(d=>d.data[i]===null?null:Number(d.data[i])),backgroundColor:colors[0]}]};bar.options.plugins.subtitle.text=p.labels[i]+' · '+p.unit;bar.update();});}
}
const d=a?.dumbbell;
if(d&&!d.reason){
 const wrap=document.getElementById('dumbbell-chart')?.parentElement;if(wrap)wrap.style.height=Math.max(310,160+d.points.length*32)+'px';
 const links={id:'connections',beforeDatasetsDraw(c){const x=c.ctx;x.save();x.strokeStyle='#9aaac0';x.lineWidth=3;d.points.forEach((v,i)=>{const y=c.scales.y.getPixelForValue(i);x.beginPath();x.moveTo(c.scales.x.getPixelForValue(Number(v.start)),y);x.lineTo(c.scales.x.getPixelForValue(Number(v.end)),y);x.stroke();});x.restore();}};
 create('dumbbell-chart',{type:'scatter',plugins:[links],data:{datasets:['start','end'].map((k,i)=>({label:i?d.end:d.start,data:d.points.map((v,j)=>({x:Number(v[k]),y:j})),backgroundColor:colors[i],borderColor:'#fff',borderWidth:1.5,pointRadius:6,pointHoverRadius:8}))},options:{plugins:{...caption(d.start+' → '+d.end+' · '+d.unit,d.cohort+' · n = '+d.n),legend:{position:'bottom'},tooltip:{callbacks:{title:items=>d.points[items[0].dataIndex].name,label:c=>{const v=d.points[c.dataIndex];return[d.start+': '+v.start+' '+d.unit,d.end+': '+v.end+' '+d.unit,'Изменение: '+v.change+' '+d.change_unit];}}}},scales:{x:{title:{display:true,text:d.unit},grid:{color:'#e9edf4'}},y:{min:-0.5,max:d.points.length-0.5,reverse:true,ticks:{stepSize:1,autoSkip:false,callback:v=>Number.isInteger(v)&&d.points[v]?short(d.points[v].name,42):''},grid:{display:false}}}}});
}
const s=a?.scatter;
if(s&&!s.reason){create('scatter-chart',{type:'scatter',data:{datasets:[{label:'Территории',data:s.points.map(v=>({x:Number(v.x),y:Number(v.y)})),pointRadius:5,pointHoverRadius:8,backgroundColor:'#245ec7aa',borderColor:'#245ec7'}]},options:{plugins:{...caption(s.period+' · n = '+s.n,s.cohort),legend:{display:false},tooltip:{callbacks:{title:items=>s.points[items[0].dataIndex].name,label:c=>{const v=s.points[c.dataIndex];return['X ('+s.x_id+'): '+v.x+' '+s.x_unit,'Y ('+s.y_id+'): '+v.y+' '+s.y_unit];}}}},scales:{x:{title:{display:true,text:'X: '+s.x_id+' · '+s.x_unit},grid:{color:'#e9edf4'}},y:{title:{display:true,text:'Y: '+s.y_id+' · '+s.y_unit},grid:{color:'#e9edf4'}}}}});}
const b=a?.boxplot;
if(b&&!b.reason){
 const box={id:'box',beforeDatasetsDraw(c){const x=c.ctx;const px=k=>c.scales.x.getPixelForValue(Number(b[k]));const y=c.scales.y.getPixelForValue(0),h=Math.min(55,(c.chartArea.bottom-c.chartArea.top)*.32);x.save();x.lineWidth=2;x.strokeStyle='#245ec7';x.fillStyle='#245ec733';x.fillRect(px('q1'),y-h/2,Math.max(px('q3')-px('q1'),1),h);x.strokeRect(px('q1'),y-h/2,Math.max(px('q3')-px('q1'),1),h);x.beginPath();x.moveTo(px('low'),y);x.lineTo(px('q1'),y);x.moveTo(px('q3'),y);x.lineTo(px('high'),y);['low','high'].forEach(k=>{x.moveTo(px(k),y-h/3);x.lineTo(px(k),y+h/3);});x.moveTo(px('median'),y-h/2);x.lineTo(px('median'),y+h/2);x.stroke();x.restore();}};
 const stats=[['Нижний ус',b.low],['Q1',b.q1],['Медиана',b.median],['Q3',b.q3],['Верхний ус',b.high]];
 const span=Number(b.maximum)-Number(b.minimum),pad=span?span*.08:Math.max(Math.abs(Number(b.median))*.05,1);
 create('boxplot-chart',{type:'scatter',plugins:[box],data:{datasets:[{label:'Усы, квартили, медиана',data:stats.map(v=>({x:Number(v[1]),y:0})),pointRadius:2,pointHitRadius:8,backgroundColor:'#245ec7'},{label:'Выбросы (1,5 IQR)',data:b.outliers.map(v=>({x:Number(v.value),y:0})),pointRadius:5,backgroundColor:'#d05279'}]},options:{plugins:{...caption(b.period+' · n = '+b.n+' · '+b.unit,b.cohort),legend:{position:'bottom'},tooltip:{callbacks:{title:items=>items[0].datasetIndex?b.outliers[items[0].dataIndex].name:stats[items[0].dataIndex][0],label:c=>(c.datasetIndex?b.outliers[c.dataIndex].value:stats[c.dataIndex][1])+' '+b.unit}}},scales:{x:{min:Number(b.minimum)-pad,max:Number(b.maximum)+pad,title:{display:true,text:b.unit},grid:{color:'#e9edf4'}},y:{min:-1,max:1,display:false}}}});
}
const save=(canvas,name)=>{const link=document.createElement('a');link.download=name+'.png';link.href=canvas.toDataURL('image/png');link.click();};
document.querySelectorAll('[data-export]').forEach(button=>button.addEventListener('click',()=>{const chart=charts[button.dataset.export];if(chart)save(chart.canvas,button.dataset.export);}));
document.getElementById('heat-export')?.addEventListener('click',()=>{
 const table=document.getElementById('heatmap-table');if(!table)return;
 const rows=Array.from(table.rows),cw=135,lw=320,h=54,m=24,heading=80;
 const canvas=document.createElement('canvas');canvas.width=lw+(rows[0].cells.length-1)*cw+m*2;canvas.height=heading+rows.length*h+m;
 const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.fillStyle='#182b49';ctx.font='bold 17px Arial';ctx.fillText(short(p?.title||'Тепловая карта',150),m,26);ctx.font='13px Arial';ctx.fillText((p?.unit||'')+' · Серый: нет данных',m,52);
 rows.forEach((row,ri)=>Array.from(row.cells).forEach((cell,ci)=>{const width=ci?cw:lw,x=m+(ci?lw+(ci-1)*cw:0),y=heading+ri*h,style=getComputedStyle(cell);ctx.fillStyle=ci&&ri?style.backgroundColor:'#f0f4fa';ctx.fillRect(x+1,y+1,width-2,h-2);ctx.fillStyle=ci&&ri?style.color:'#182b49';ctx.font=ri?'12px Arial':'bold 12px Arial';const words=cell.textContent.trim().split(/\s+/);let line='',lines=[];words.forEach(word=>{if(ctx.measureText(line+' '+word).width>width-16&&line){lines.push(line);line=word;}else line+=(line?' ':'')+word;});lines.push(line);lines.slice(0,3).forEach((v,i)=>ctx.fillText(short(v,ci?20:49),x+8,y+16+i*15));}));save(canvas,'heatmap');
});
})();
