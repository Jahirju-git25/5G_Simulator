// ============================================================
//   5G NR Network Simulator - React Frontend
// ============================================================

const { useState, useEffect, useRef, useCallback } = React;

function sinrColor(sinr) {
  if (sinr > 20) return '#3fb950';
  if (sinr > 10) return '#58a6ff';
  if (sinr > 0)  return '#d29922';
  return '#f85149';
}
function rsrpColor(rsrp) {
  if (rsrp > -80)  return '#3fb950';
  if (rsrp > -95)  return '#58a6ff';
  if (rsrp > -110) return '#d29922';
  return '#f85149';
}
function sinrClass(sinr) {
  if (sinr > 20) return 'sig-excellent';
  if (sinr > 10) return 'sig-good';
  if (sinr > 0)  return 'sig-fair';
  return 'sig-poor';
}
function formatThroughput(mbps) {
  if (mbps == null || isNaN(mbps)) return '0 Mbps';
  const v = Number(mbps);
  if (Math.abs(v) >= 1000) return `${(v/1000).toFixed(2)} Gbps`;
  if (Math.abs(v) >= 1)    return `${v.toFixed(1)} Mbps`;
  return `${(v*1000).toFixed(1)} Kbps`;
}
function downloadCanvasWithTitle(sourceCanvas, title, filename) {
  if (!sourceCanvas) return;
  try {
    const titleHeight = 28, padding = 12;
    const outW = sourceCanvas.width || 1;
    const outH = (sourceCanvas.height || 1) + titleHeight + padding;
    const out = document.createElement('canvas');
    out.width = outW; out.height = outH;
    const ctx = out.getContext('2d');
    if (!ctx) return;
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0,0,outW,outH);
    ctx.fillStyle = '#0d1117'; ctx.font = 'bold 16px system-ui';
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(title, outW/2, 8);
    const img = new Image();
    img.onload = () => {
      try {
        ctx.drawImage(img, 0, titleHeight+padding/2, sourceCanvas.width, sourceCanvas.height);
        const link = document.createElement('a');
        link.download = filename || 'chart.png';
        link.href = out.toDataURL('image/png');
        link.click();
      } catch (innerErr) { console.warn('Failed exporting chart image', innerErr); }
    };
    img.src = sourceCanvas.toDataURL('image/png');
  } catch (err) { console.warn('Failed to download chart image', err); }
}

// ─────────────────────────────────────────────
//  Network Canvas
// ─────────────────────────────────────────────
function NetworkCanvas({ state, onPlaceGnb, onPlaceUe, placeMode, selectedUe, setSelectedUe, onCursorMove }) {
  const canvasRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const dragRef = useRef(null);

  const gnbs = state?.gnbs || {};
  const ues  = state?.ues  || {};

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0,0,W,H);
    drawGrid(ctx,W,H);
    const gnbList = Object.values(gnbs);
    for (let i=0;i<gnbList.length;i++)
      for (let j=i+1;j<gnbList.length;j++)
        drawBackhaulLink(ctx,gnbList[i],gnbList[j]);
    Object.values(ues).forEach(ue => {
      if (ue.serving_gnb && gnbs[ue.serving_gnb])
        drawWirelessLink(ctx,ue,gnbs[ue.serving_gnb],ue.sinr);
    });
    gnbList.forEach(gnb => { drawGnB(ctx,gnb,hoveredId===gnb.id); drawSectors(ctx,gnb); });
    Object.values(ues).forEach(ue => { drawUeTrail(ctx,ue); drawUE(ctx,ue,selectedUe===ue.id,hoveredId===ue.id); });
  }, [gnbs,ues,hoveredId,selectedUe]);

  function getCanvasXY(e) {
    const rect = canvasRef.current.getBoundingClientRect();
    const scaleX = canvasRef.current.width  / rect.width;
    const scaleY = canvasRef.current.height / rect.height;
    return { x: (e.clientX-rect.left)*scaleX, y: (e.clientY-rect.top)*scaleY };
  }

  function hitTest(x,y) {
    for (const ue of Object.values(ues))
      if (Math.hypot(x-ue.x, y-ue.y) < 14) return {type:'ue', id:ue.id, data:ue};
    for (const gnb of Object.values(gnbs))
      if (Math.hypot(x-gnb.x, y-gnb.y) < 18) return {type:'gnb', id:gnb.id, data:gnb};
    return null;
  }

  function handleMouseDown(e) {
    if (e.button !== 0) return;
    const {x,y} = getCanvasXY(e);
    if (placeMode === 'gnb') { onPlaceGnb(x,y); return; }
    if (placeMode === 'ue')  { onPlaceUe(x,y);  return; }
    const hit = hitTest(x,y);
    if (hit) {
      dragRef.current = {id:hit.id, type:hit.type, startX:x, startY:y, moved:false};
      if (hit.type==='ue') setSelectedUe(hit.id);
    } else { setSelectedUe(null); }
  }

  function handleMouseMove(e) {
    const {x,y} = getCanvasXY(e);
    if (onCursorMove) onCursorMove(Math.round(x), Math.round(y));
    if (dragRef.current) {
      const d = dragRef.current;
      if (!d.moved && Math.hypot(x-d.startX,y-d.startY) < 4) return;
      d.moved = true;
      if (d.type==='ue')  fetch('/api/move_ue', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ue_id:d.id,x,y})});
      if (d.type==='gnb') fetch('/api/move_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gnb_id:d.id,x,y})});
      return;
    }
    const hit = hitTest(x,y);
    setHoveredId(hit ? hit.id : null);
    setTooltip(hit ? {x, y, type:hit.type, data:hit.data} : null);
  }

  function handleMouseUp() { dragRef.current = null; }

  function handleContextMenu(e) {
    e.preventDefault();
    const {x,y} = getCanvasXY(e);
    const hit = hitTest(x,y);
    if (!hit) return;
    if (hit.type==='ue')  fetch('/api/remove_ue', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ue_id:hit.id})});
    if (hit.type==='gnb') fetch('/api/remove_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gnb_id:hit.id})});
  }

  function drawGrid(ctx,W,H) {
    ctx.save();
    ctx.strokeStyle='rgba(48,54,61,0.4)'; ctx.lineWidth=1;
    for(let x=0;x<=W;x+=50){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
    for(let y=0;y<=H;y+=50){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
    ctx.restore();
  }
  function drawBackhaulLink(ctx,g1,g2) {
    ctx.save();
    ctx.strokeStyle='rgba(88,166,255,0.15)'; ctx.lineWidth=1; ctx.setLineDash([4,8]);
    ctx.beginPath();ctx.moveTo(g1.x,g1.y);ctx.lineTo(g2.x,g2.y);ctx.stroke();
    ctx.setLineDash([]); ctx.restore();
  }
  function drawWirelessLink(ctx,ue,gnb,sinr) {
    const color=sinrColor(sinr);
    const r=parseInt(color.slice(1,3),16),g=parseInt(color.slice(3,5),16),b=parseInt(color.slice(5,7),16);
    ctx.save();
    ctx.strokeStyle=`rgba(${r},${g},${b},0.25)`; ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(ue.x,ue.y);ctx.lineTo(gnb.x,gnb.y);ctx.stroke();
    ctx.restore();
  }
  function drawSectors(ctx,gnb) {
    ctx.save();
    const R = 120;
    if (!gnb.sectors || gnb.sectors <= 1) {
      // Omni — full coverage circle
      ctx.strokeStyle='rgba(88,166,255,0.18)'; ctx.lineWidth=1;
      ctx.setLineDash([4,6]);
      ctx.beginPath(); ctx.arc(gnb.x,gnb.y,R,0,Math.PI*2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle='rgba(88,166,255,0.04)';
      ctx.beginPath(); ctx.arc(gnb.x,gnb.y,R,0,Math.PI*2); ctx.fill();
    } else {
      // Multi-sector wedges
      for(let i=0;i<gnb.sectors;i++){
        const angle=(i/gnb.sectors)*Math.PI*2-Math.PI/2;
        ctx.strokeStyle='rgba(88,166,255,0.15)'; ctx.lineWidth=1;
        ctx.fillStyle='rgba(88,166,255,0.04)';
        ctx.beginPath(); ctx.moveTo(gnb.x,gnb.y);
        ctx.arc(gnb.x,gnb.y,R,angle-(Math.PI/gnb.sectors),angle+(Math.PI/gnb.sectors));
        ctx.closePath(); ctx.fill(); ctx.stroke();
      }
    }
    ctx.restore();
  }
  function drawGnB(ctx,gnb,hovered) {
    const x=gnb.x,y=gnb.y,size=18;
    ctx.save();
    if(hovered){ctx.shadowColor='#58a6ff';ctx.shadowBlur=16;}
    ctx.strokeStyle=hovered?'#74b9ff':'#58a6ff'; ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(x,y-size);ctx.lineTo(x,y+size*0.3);
    ctx.moveTo(x-size*0.6,y-size*0.4);ctx.lineTo(x+size*0.6,y-size*0.4);
    ctx.moveTo(x-size*0.4,y-size*0.1);ctx.lineTo(x+size*0.4,y-size*0.1);
    ctx.moveTo(x-size*0.4,y+size*0.3);ctx.lineTo(x+size*0.4,y+size*0.3);ctx.stroke();
    ctx.beginPath();ctx.arc(x,y,10,0,Math.PI*2);
    ctx.fillStyle=hovered?'rgba(88,166,255,0.3)':'rgba(88,166,255,0.15)';ctx.fill();
    ctx.strokeStyle='#58a6ff';ctx.lineWidth=1.5;ctx.stroke();
    ctx.shadowBlur=0;
    ctx.fillStyle='#e6edf3';ctx.font='bold 10px system-ui';ctx.textAlign='center';
    ctx.fillText(gnb.id,x,y+size+14);
    const cc=gnb.connected_ues||0;
    if(cc>0){ctx.beginPath();ctx.arc(x+12,y-12,9,0,Math.PI*2);ctx.fillStyle='#3fb950';ctx.fill();
      ctx.fillStyle='#0d1117';ctx.font='bold 9px system-ui';ctx.fillText(cc,x+12,y-9);}
    ctx.restore();
  }
  function drawUE(ctx,ue,selected,hovered) {
    const x=ue.x,y=ue.y,size=selected?10:8;
    const sinr=ue.sinr??-999;
    const color=sinr>20?'#3fb950':sinr>10?'#58a6ff':sinr>0?'#d29922':'#f85149';
    const r=parseInt(color.slice(1,3),16),g=parseInt(color.slice(3,5),16),b=parseInt(color.slice(5,7),16);
    ctx.save();
    if(selected||hovered){ctx.shadowColor=color;ctx.shadowBlur=12;}
    ctx.beginPath();ctx.arc(x,y,size,0,Math.PI*2);
    ctx.fillStyle=selected?color:`rgba(${r},${g},${b},0.85)`;ctx.fill();
    ctx.strokeStyle=selected?'#fff':'#1c2128';ctx.lineWidth=selected?2:1.5;ctx.stroke();
    ctx.shadowBlur=0;
    ctx.fillStyle='#8b949e';ctx.font='9px system-ui';ctx.textBaseline='alphabetic';ctx.textAlign='center';
    ctx.fillText(ue.id,x,y+size+10);
    if(ue.throughput>0){ctx.fillStyle=color;ctx.font='bold 8px system-ui';ctx.fillText(`${ue.throughput.toFixed(0)}Mbps`,x,y-size-4);}
    ctx.restore();
  }
  function drawUeTrail(ctx,ue) {
    if(!ue.position_history||ue.position_history.length<2) return;
    const trail=ue.position_history.slice(-20),color=sinrColor(ue.sinr);
    const r=parseInt(color.slice(1,3),16),g=parseInt(color.slice(3,5),16),b=parseInt(color.slice(5,7),16);
    ctx.save();
    for(let i=1;i<trail.length;i++){
      ctx.strokeStyle=`rgba(${r},${g},${b},${(i/trail.length)*0.3})`;ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(trail[i-1].x,trail[i-1].y);ctx.lineTo(trail[i].x,trail[i].y);ctx.stroke();
    }
    ctx.restore();
  }

  return (
    <div className="canvas-container" style={{position:'relative'}}>
      <canvas ref={canvasRef} className="network-canvas" width={800} height={560}
        onMouseDown={handleMouseDown} onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={()=>{dragRef.current=null;setHoveredId(null);setTooltip(null);if(onCursorMove)onCursorMove(0,0);}}
        onContextMenu={handleContextMenu}
        style={{cursor:placeMode?'crosshair':dragRef.current?'grabbing':'grab',width:'100%',height:'100%'}}
      />

      {/* UE colour indicator legend — bottom-left */}
      <div className="legend" style={{position:'absolute',bottom:8,left:8,background:'rgba(13,17,23,0.85)',borderRadius:6,padding:'4px 8px'}}>
        <div className="legend-item"><div className="legend-dot" style={{background:'#58a6ff'}}></div>gNB</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#3fb950'}}></div>UE (Excellent &gt;20dB)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#58a6ff',border:'1px solid #fff'}}></div>UE (Good 10–20dB)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#d29922'}}></div>UE (Fair 0–10dB)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#f85149'}}></div>UE (Poor &lt;0dB)</div>
      </div>

      {/* Hover tooltip */}
      {tooltip && (
        <div className="canvas-tooltip" style={{left:Math.min(tooltip.x+14,620),top:Math.max(tooltip.y-10,4)}}>
          {tooltip.type==='ue' && (<>
            <div className="tooltip-title">📱 {tooltip.data.id}</div>
            <div className="tooltip-row"><span className="tooltip-label">Serving:</span><span className="tooltip-value">{tooltip.data.serving_gnb||'None'}</span></div>
            <div className="tooltip-row"><span className="tooltip-label">RSRP:</span><span className="tooltip-value">{tooltip.data.rsrp?.toFixed(1)} dBm</span></div>
            <div className="tooltip-row"><span className="tooltip-label">SINR:</span><span className={`tooltip-value ${sinrClass(tooltip.data.sinr)}`}>{tooltip.data.sinr?.toFixed(1)} dB</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Throughput:</span><span className="tooltip-value good">{tooltip.data.throughput?.toFixed(1)} Mbps</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Modulation:</span><span className="tooltip-value">{tooltip.data.modulation}</span></div>
            <div style={{borderTop:'1px solid #30363d',marginTop:4,paddingTop:4}}>
              <div className="tooltip-row"><span className="tooltip-label">Canvas X:</span><span className="tooltip-value" style={{color:'#58a6ff'}}>{Math.round(tooltip.data.x)} px</span></div>
              <div className="tooltip-row"><span className="tooltip-label">Canvas Y:</span><span className="tooltip-value" style={{color:'#58a6ff'}}>{Math.round(tooltip.data.y)} px</span></div>
              <div className="tooltip-row"><span className="tooltip-label">Position:</span><span className="tooltip-value" style={{color:'#8b949e'}}>{(tooltip.data.x*5).toFixed(0)}m, {(tooltip.data.y*5).toFixed(0)}m</span></div>
            </div>
          </>)}
          {tooltip.type==='gnb' && (<>
            <div className="tooltip-title">📡 {tooltip.data.id}</div>
            <div className="tooltip-row"><span className="tooltip-label">UEs:</span><span className="tooltip-value">{tooltip.data.connected_ues}</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Throughput:</span><span className="tooltip-value good">{tooltip.data.total_throughput?.toFixed(1)} Mbps</span></div>
            <div className="tooltip-row"><span className="tooltip-label">TX Power:</span><span className="tooltip-value">{tooltip.data.tx_power_dbm} dBm</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Position:</span><span className="tooltip-value" style={{color:'#8b949e'}}>{(tooltip.data.x*5).toFixed(0)}m, {(tooltip.data.y*5).toFixed(0)}m</span></div>
          </>)}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Chart helpers
// ─────────────────────────────────────────────
function LineChart({data,label,color,unit,height=110,xLabel='Time (steps)',yLabel=''}) {
  const canvasRef=useRef(null); const chartRef=useRef(null);
  useEffect(()=>{
    if(!canvasRef.current) return;
    if(chartRef.current) chartRef.current.destroy();
    const len=data.length||1;
    chartRef.current=new Chart(canvasRef.current,{
      type:'line',
      data:{labels:Array.from({length:len},(_,i)=>i),datasets:[{label,data,borderColor:color,borderWidth:1.5,pointRadius:0,fill:true,backgroundColor:`${color}18`}]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        plugins:{legend:{labels:{color:'#8b949e',font:{size:9},boxWidth:8}},tooltip:{callbacks:{label:(ctx)=>`${ctx.parsed.y.toFixed(2)} ${unit}`}}},
        scales:{x:{ticks:{color:'#6e7681',font:{size:8},maxTicksLimit:6},grid:{color:'rgba(48,54,61,0.5)'},title:{display:!!xLabel,text:xLabel,color:'#6e7681',font:{size:8}}},
          y:{ticks:{color:'#6e7681',font:{size:8}},grid:{color:'rgba(48,54,61,0.5)'},title:{display:!!yLabel,text:yLabel,color:'#6e7681',font:{size:8}}}}}
    });
    return()=>{if(chartRef.current){chartRef.current.destroy();chartRef.current=null;}};
  },[data,color,label,unit]);
  return <div style={{height}}><canvas ref={canvasRef}/></div>;
}
function ChartWithDownload({title,filename,children}) {
  const ref=useRef(null);
  return (
    <div style={{position:'relative'}}>
      <div style={{display:'flex',justifyContent:'flex-end',marginBottom:4}}>
        <button onClick={()=>{const c=ref.current?.querySelector('canvas');if(c)downloadCanvasWithTitle(c,title,filename);}}
          style={{background:'rgba(88,166,255,0.15)',border:'1px solid #30363d',borderRadius:4,color:'#58a6ff',fontSize:10,padding:'2px 6px',cursor:'pointer'}}>⬇ PNG</button>
      </div>
      <div ref={ref}>{children}</div>
    </div>
  );
}
function LineChartWithDownload({data,label,color,unit,height=110,xLabel='Time (steps)',yLabel='',title,filename}) {
  return (
    <ChartWithDownload title={title||label} filename={filename||`${label.replace(/\s+/g,'_').toLowerCase()}.png`}>
      <LineChart data={data} label={label} color={color} unit={unit} height={height} xLabel={xLabel} yLabel={yLabel}/>
    </ChartWithDownload>
  );
}
function MultiLineChart({datasets,height=120,xLabel='',yLabel=''}) {
  const canvasRef=useRef(null); const chartRef=useRef(null);
  useEffect(()=>{
    if(!canvasRef.current) return;
    if(chartRef.current) chartRef.current.destroy();
    const len=Math.max(...datasets.map(d=>d.data.length),1);
    chartRef.current=new Chart(canvasRef.current,{
      type:'line',
      data:{labels:Array.from({length:len},(_,i)=>i),datasets:datasets.map(d=>({label:d.label,data:d.data,borderColor:d.color,borderWidth:1.5,pointRadius:0,fill:false}))},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        plugins:{legend:{labels:{color:'#8b949e',font:{size:8},boxWidth:8}}},
        scales:{x:{ticks:{color:'#6e7681',font:{size:8},maxTicksLimit:6},grid:{color:'rgba(48,54,61,0.5)'},title:{display:!!xLabel,text:xLabel,color:'#6e7681',font:{size:8}}},
          y:{ticks:{color:'#6e7681',font:{size:8}},grid:{color:'rgba(48,54,61,0.5)'},title:{display:!!yLabel,text:yLabel,color:'#6e7681',font:{size:8}}}}}
    });
    return()=>{if(chartRef.current){chartRef.current.destroy();chartRef.current=null;}};
  },[datasets]);
  return <div style={{height}}><canvas ref={canvasRef}/></div>;
}
function MultiLineChartWithDownload(props) {
  return (<ChartWithDownload title="Per-UE Throughput" filename="per_ue_throughput.png"><MultiLineChart {...props}/></ChartWithDownload>);
}

// ─────────────────────────────────────────────
//  Pathloss Chart
// ─────────────────────────────────────────────
function PathlossChart({channelCfg}) {
  const canvasRef=useRef(null); const chartRef=useRef(null);
  useEffect(()=>{
    if(!canvasRef.current) return;
    if(chartRef.current) chartRef.current.destroy();
    const distances=Array.from({length:50},(_,i)=>(i+1)*20);
    const datasets=[];
    if(channelCfg?.pathloss_model==='LogDistance'){
      const n=channelCfg?.log_dist_n??3.5,d0=1,f=3.5e9,c=3e8;
      const pl_d0=20*Math.log10(4*Math.PI*d0*f/c);
      datasets.push({label:`Log Dist n=${n.toFixed(1)}`,data:distances.map(d=>pl_d0+10*n*Math.log10(d/d0)),borderColor:'#bc8cff',borderWidth:2,pointRadius:0,fill:false});
    } else {
      datasets.push(
        {label:'UMa LOS', data:distances.map(d=>28+22*Math.log10(Math.sqrt(d**2+(25-1.5)**2))+20*Math.log10(3.5)),borderColor:'#58a6ff',borderWidth:1.5,pointRadius:0,fill:false},
        {label:'UMa NLOS',data:distances.map(d=>13.54+39.08*Math.log10(Math.sqrt(d**2+(25-1.5)**2))+20*Math.log10(3.5)),borderColor:'#58a6ff',borderWidth:1.5,borderDash:[4,4],pointRadius:0,fill:false},
        {label:'UMi LOS', data:distances.map(d=>32.4+21*Math.log10(Math.sqrt(d**2+(10-1.5)**2))+20*Math.log10(3.5)),borderColor:'#3fb950',borderWidth:1.5,pointRadius:0,fill:false},
        {label:'RMa LOS', data:distances.map(d=>20*Math.log10(40*Math.PI*d*3.5/3)+2*d/1000),borderColor:'#d29922',borderWidth:1.5,pointRadius:0,fill:false},
      );
    }
    chartRef.current=new Chart(canvasRef.current,{
      type:'line',data:{labels:distances,datasets},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        plugins:{legend:{labels:{color:'#8b949e',font:{size:9},boxWidth:10}},
          tooltip:{callbacks:{label:(ctx)=>`${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} dB`,title:(items)=>`Distance: ${items[0].label} m`}}},
        scales:{x:{ticks:{color:'#6e7681',font:{size:9},maxTicksLimit:6},grid:{color:'rgba(48,54,61,0.5)'},title:{display:true,text:'Distance (m)',color:'#6e7681',font:{size:9}}},
          y:{ticks:{color:'#6e7681',font:{size:9}},grid:{color:'rgba(48,54,61,0.5)'},title:{display:true,text:'Pathloss (dB)',color:'#6e7681',font:{size:9}}}}}
    });
    return()=>{if(chartRef.current){chartRef.current.destroy();chartRef.current=null;}};
  },[channelCfg?.pathloss_model,channelCfg?.log_dist_n]);
  return <div style={{height:150}}><canvas ref={canvasRef}/></div>;
}
function PathlossChartWithDownload({channelCfg}) {
  const title=channelCfg?.pathloss_model==='LogDistance'
    ?`Log Distance Pathloss (n=${(channelCfg?.log_dist_n??3.5).toFixed(1)})`
    :'Pathloss vs Distance (3GPP TR 38.901)';
  return (<ChartWithDownload title={title} filename="pathloss_vs_distance.png"><PathlossChart channelCfg={channelCfg}/></ChartWithDownload>);
}

// ─────────────────────────────────────────────
//  Accordion Section
// ─────────────────────────────────────────────
function AccordionSection({title,icon,children,defaultOpen=true,badge}) {
  const [open,setOpen]=useState(defaultOpen);
  return (
    <div style={{borderBottom:'1px solid #21262d'}}>
      <div onClick={()=>setOpen(o=>!o)} style={{display:'flex',alignItems:'center',gap:6,padding:'8px 12px',cursor:'pointer',userSelect:'none',background:'rgba(0,0,0,0.15)'}}>
        <span style={{fontSize:12}}>{icon}</span>
        <span style={{fontSize:11,fontWeight:600,color:'#c9d1d9',flex:1}}>{title}</span>
        {badge!=null&&<span style={{fontSize:10,padding:'1px 6px',borderRadius:10,background:'rgba(88,166,255,0.15)',color:'#58a6ff',fontWeight:600}}>{badge}</span>}
        <span style={{color:'#6e7681',fontSize:10}}>{open?'▲':'▼'}</span>
      </div>
      {open&&<div style={{padding:'8px 12px'}}>{children}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Throughput Log
// ─────────────────────────────────────────────
function ThroughputLog({state}) {
  const metrics=state?.metrics||[]; const ues=state?.ues||{}; const ueIds=Object.keys(ues);
  const downloadCSV=()=>{
    if(!metrics.length){alert('No data yet.');return;}
    const header=['time_s',...ueIds,'instant_mbps','cumulative_mb'].join(',');
    const rows=metrics.map(m=>{const u=m.ue_throughputs||{};return[
      m.time?.toFixed(2),
      ...ueIds.map(id=>(u[id]??0).toFixed(2)),
      m.total_throughput?.toFixed(2),
      m.cumulative_mb?.toFixed(2)??'0.00',
    ].join(',');});
    const csv=[header,...rows].join('\n');
    const blob=new Blob([csv],{type:'text/csv'});const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download='throughput_log.csv';a.click();URL.revokeObjectURL(url);
  };
  const thS={padding:'4px 6px',textAlign:'left',fontWeight:700,color:'#8b949e',borderBottom:'1px solid #30363d',whiteSpace:'nowrap',fontSize:9};
  const tdS={padding:'3px 6px',color:'#e6edf3',borderBottom:'1px solid #21262d',whiteSpace:'nowrap',fontSize:9};
  return (
    <div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
        <span style={{fontSize:10,color:'#6e7681'}}>{metrics.length} entries</span>
        <button onClick={downloadCSV} style={{fontSize:10,padding:'3px 8px',borderRadius:4,cursor:'pointer',background:'rgba(63,185,80,0.15)',border:'1px solid rgba(63,185,80,0.3)',color:'#3fb950',fontWeight:600}}>⬇ CSV</button>
      </div>
      <div style={{overflowX:'auto',overflowY:'auto',maxHeight:240,borderRadius:6,border:'1px solid #30363d'}}>
        <table style={{borderCollapse:'collapse',width:'100%',minWidth:280}}>
          <thead><tr style={{background:'#1c2128',position:'sticky',top:0,zIndex:1}}>
            <th style={thS}>Time(s)</th>
            {ueIds.map(id=><th key={id} style={thS}>{id}</th>)}
            <th style={{...thS,color:'#3fb950'}}>Instant(Mbps)</th>
            <th style={{...thS,color:'#58a6ff'}}>Cumul.(Mb)</th>
          </tr></thead>
          <tbody>
            {metrics.length===0&&<tr><td colSpan={ueIds.length+3} style={{color:'#6e7681',textAlign:'center',padding:10,fontSize:10}}>No data yet — start simulation</td></tr>}
            {metrics.slice().reverse().map((m,i)=>{const ueTps=m.ue_throughputs||{};return(
              <tr key={i} style={{background:i%2===0?'#161b22':'#1c2128'}}>
                <td style={tdS}>{m.time?.toFixed(1)}</td>
                {ueIds.map(id=><td key={id} style={{...tdS,color:'#3fb950'}}>{(ueTps[id]??0).toFixed(1)}</td>)}
                <td style={{...tdS,color:'#3fb950',fontWeight:700}}>{m.total_throughput?.toFixed(1)}</td>
                <td style={{...tdS,color:'#58a6ff',fontWeight:700}}>{m.cumulative_mb?.toFixed(1)??'—'}</td>
              </tr>
            );})}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Handover Table
// ─────────────────────────────────────────────
function HandoverTable({handovers,showDownloadButton=false}) {
  const thS={padding:'4px 6px',textAlign:'left',fontWeight:700,color:'#8b949e',borderBottom:'1px solid #30363d',whiteSpace:'nowrap',fontSize:9};
  const tdS={padding:'3px 6px',color:'#e6edf3',borderBottom:'1px solid #21262d',whiteSpace:'nowrap',fontSize:9};
  const downloadCSV=()=>{
    if(!handovers.length){alert('No handover events yet.');return;}
    const header='time_s,ue_id,from_gnb,to_gnb,sinr_dB,rsrp_dBm,type';
    const rows=handovers.map(ho=>[ho.time?.toFixed(2),ho.ue_id||'',ho.serving||'',ho.target||'',ho.sinr?.toFixed(1),ho.rsrp?.toFixed(1),ho.ping_pong?'Ping-Pong':'A3-HO'].join(','));
    const csv=[header,...rows].join('\n');
    const blob=new Blob([csv],{type:'text/csv'});const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download='handover_log.csv';a.click();URL.revokeObjectURL(url);
  };
  return (
    <div>
      {showDownloadButton&&<div style={{display:'flex',justifyContent:'flex-end',marginBottom:6}}><button onClick={downloadCSV} style={{fontSize:10,padding:'3px 8px',borderRadius:4,cursor:'pointer',background:'rgba(63,185,80,0.15)',border:'1px solid rgba(63,185,80,0.3)',color:'#3fb950',fontWeight:600}}>⬇ CSV</button></div>}
      <div style={{overflowX:'auto',overflowY:'auto',maxHeight:300,borderRadius:6,border:'1px solid #30363d'}}>
        <table style={{borderCollapse:'collapse',width:'100%',minWidth:380}}>
          <thead><tr style={{background:'#1c2128',position:'sticky',top:0,zIndex:1}}>
            {['Time','UE','From','To','SINR','RSRP','Type'].map(h=><th key={h} style={thS}>{h}</th>)}
          </tr></thead>
          <tbody>
            {handovers.length===0&&<tr><td colSpan={7} style={{color:'#6e7681',textAlign:'center',padding:10,fontSize:10}}>No handovers yet</td></tr>}
            {handovers.slice().reverse().map((ho,i)=>{const isPP=ho.ping_pong;return(
              <tr key={i} style={{background:i%2===0?'#161b22':'#1c2128'}}>
                <td style={tdS}>{ho.time?.toFixed(1)}</td>
                <td style={{...tdS,color:'#3fb950',fontWeight:700}}>{ho.ue_id||''}</td>
                <td style={{...tdS,color:'#58a6ff'}}>{ho.serving||''}</td>
                <td style={{...tdS,color:'#d29922'}}>{ho.target}</td>
                <td style={{...tdS,color:ho.sinr>10?'#3fb950':ho.sinr>0?'#d29922':'#f85149'}}>{ho.sinr?.toFixed(1)}</td>
                <td style={{...tdS,color:'#8b949e'}}>{ho.rsrp?.toFixed(1)}</td>
                <td style={{...tdS,color:isPP?'#f85149':'#6e7681'}}>{isPP?'⚠ Ping-Pong':'A3 HO'}</td>
              </tr>
            );})}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  File Mobility CSV Uploader
// ─────────────────────────────────────────────
function FileMobilityUploader() {
  const fileInputRef=useRef(null);
  const [status,setStatus]=useState(null);
  const [message,setMessage]=useState('');
  const [loading,setLoading]=useState(false);

  const handleUpload=async(e)=>{
    const file=e.target.files[0];if(!file)return;
    const formData=new FormData();formData.append('file',file);
    setLoading(true);setStatus(null);setMessage('Uploading…');
    try{
      const res=await fetch('/api/upload_mobility_csv',{method:'POST',body:formData});
      const data=await res.json();
      if(data.success){
        const ueList=Object.entries(data.rows).map(([id,n])=>`${id}: ${n} pts`).join(', ');
        setStatus('ok');setMessage(`Loaded ${data.ue_count} UE(s) — ${ueList}`);
      }else{setStatus('err');setMessage(data.error||'Upload failed');}
    }catch(err){setStatus('err');setMessage(`Network error: ${err.message}`);}
    setLoading(false);e.target.value='';
  };

  const downloadTemplate=()=>{
    const csv=['time_stamp,Ue_ID,x_cord,y_cord','0.0,UE-1,100,200','2.0,UE-1,150,220','4.0,UE-1,210,240','6.0,UE-1,270,255','8.0,UE-1,330,260','10.0,UE-1,390,250','0.0,UE-2,600,300','2.0,UE-2,570,320','4.0,UE-2,540,345','6.0,UE-2,510,370','8.0,UE-2,480,390','10.0,UE-2,450,410'].join('\n');
    const blob=new Blob([csv],{type:'text/csv'});const url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download='mobility_trace_template.csv';a.click();URL.revokeObjectURL(url);
  };

  return (
    <div style={{marginTop:6}}>
      <input ref={fileInputRef} type="file" accept=".csv" style={{display:'none'}} onChange={handleUpload}/>
      <button className="btn btn-secondary" style={{width:'100%',fontSize:11,marginBottom:4}}
        onClick={()=>fileInputRef.current&&fileInputRef.current.click()} disabled={loading}>
        {loading?'⏳ Uploading…':'📂 Upload CSV Trace'}
      </button>
      <button onClick={downloadTemplate} style={{width:'100%',fontSize:10,padding:'3px 0',borderRadius:5,cursor:'pointer',background:'transparent',border:'1px dashed #30363d',color:'#6e7681',marginBottom:5}}>
        ⬇ Download CSV Template
      </button>
      <div style={{fontSize:10,color:'#6e7681',background:'#161b22',border:'1px dashed #30363d',borderRadius:6,padding:'5px 8px',fontFamily:'monospace',lineHeight:1.7}}>
        Required columns:<br/>
        <span style={{color:'#58a6ff'}}>time_stamp</span> · <span style={{color:'#58a6ff'}}>Ue_ID</span> · <span style={{color:'#58a6ff'}}>x_cord</span> · <span style={{color:'#58a6ff'}}>y_cord</span>
      </div>
      {message&&(
        <div style={{fontSize:10,marginTop:5,borderRadius:6,padding:'4px 8px',
          color:status==='ok'?'#3fb950':status==='err'?'#f85149':'#8b949e',
          background:status==='ok'?'rgba(63,185,80,0.1)':status==='err'?'rgba(248,81,73,0.1)':'transparent',
          border:`1px solid ${status==='ok'?'rgba(63,185,80,0.3)':status==='err'?'rgba(248,81,73,0.3)':'transparent'}`}}>
          {status==='ok'?'✅ ':status==='err'?'❌ ':'⏳ '}{message}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
//  TopNav
// ─────────────────────────────────────────────
function TopNav({state,scenario,channelCfg}) {
  const isRunning=state?.running||false;
  const metrics=state?.metrics||[];
  const globalStats=state?.global||{};
  const ues=state?.ues||{};
  const totalFromUes=Object.values(ues).reduce((acc,u)=>acc+(Number(u.throughput)||0),0);
  const latestTotal=totalFromUes>0?totalFromUes:(globalStats.total_throughput??0);
  const tpCanvasRef=useRef(null); const avgCanvasRef=useRef(null);
  useEffect(()=>{
    const drawSpark=(canvas,data,color)=>{
      if(!canvas) return;
      const ctx=canvas.getContext('2d');const W=canvas.width,H=canvas.height;
      ctx.clearRect(0,0,W,H);if(!data||!data.length)return;
      const maxV=Math.max(...data,1),minV=Math.min(...data,0),len=data.length;
      ctx.lineWidth=2;ctx.strokeStyle=color;ctx.beginPath();
      for(let i=0;i<len;i++){const x=(i/(len-1||1))*(W-4)+2,v=data[i],y=H-2-((v-minV)/(maxV-minV||1))*(H-4);i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);}
      ctx.stroke();
    };
    drawSpark(tpCanvasRef.current,metrics.map(m=>m.total_throughput||0),'#3fb950');
    drawSpark(avgCanvasRef.current,metrics.map(m=>{const n=m.num_ues??globalStats?.num_ues??0;return n>0?(m.total_throughput||0)/n:0;}),'#58a6ff');
  },[metrics,globalStats]);

  const plBadge=channelCfg?.pathloss_model==='LogDistance'
    ?`LogDist n=${(channelCfg?.log_dist_n??3.5).toFixed(1)}`
    :`3GPP·${scenario}`;

  return (
    <nav className="top-nav">
      <div className="nav-logo"><div className="nav-logo-icon">5G</div>NR Network Simulator</div>
      <span className="nav-badge">{plBadge}</span>
      <span className="nav-badge" style={{borderColor:'rgba(63,185,80,0.3)',color:'#3fb950',background:'rgba(63,185,80,0.1)'}}>{channelCfg?.fading_model||'Rayleigh'}</span>
      <div className="nav-spacer"/>
      <div style={{display:'flex',alignItems:'center',gap:4}}>
        <div className={`sim-status-dot ${isRunning?'running':''}`}></div>
        <span style={{fontSize:11,color:isRunning?'#3fb950':'#6e7681'}}>{isRunning?'LIVE':'IDLE'}</span>
      </div>
      {[
        ['Instant TP',`${(globalStats.total_throughput||0).toFixed(0)} Mbps`,globalStats.total_throughput>100?'good':'warn'],
        ['Cumul. TP',`${(globalStats.cumulative_mb||0).toFixed(1)} Mb`,'good'],
        ['Avg TP',`${(globalStats.avg_throughput_overall??0).toFixed(1)} Mbps`,''],
        ['Avg SINR',`${(globalStats.avg_sinr||0).toFixed(1)} dB`,globalStats.avg_sinr>10?'good':globalStats.avg_sinr>0?'warn':'bad'],
        ['Pkt Loss',`${globalStats.packet_loss||0}%`,globalStats.packet_loss<5?'good':globalStats.packet_loss<20?'warn':'bad'],
        ['Handovers',globalStats.total_handovers||0,''],
        ['Step',state?.step||0,''],
      ].map(([label,value,cls])=>(
        <div key={label} className="nav-stat">
          <div className="nav-stat-label">{label}</div>
          <div className={`nav-stat-value ${cls}`}>{value}</div>
        </div>
      ))}
      <div style={{display:'flex',alignItems:'center',gap:12,marginLeft:12}}>
        <div style={{textAlign:'center',color:'#8b949e',fontSize:11}}>
          <div style={{fontSize:10}}>Total TP</div>
          <canvas ref={tpCanvasRef} width={120} height={28} style={{width:120,height:28}}/>
        </div>
        <div style={{textAlign:'center',color:'#8b949e',fontSize:11}}>
          <div style={{fontSize:10}}>Avg TP/UE</div>
          <canvas ref={avgCanvasRef} width={120} height={28} style={{width:120,height:28}}/>
        </div>
      </div>
    </nav>
  );
}

// ─────────────────────────────────────────────
//  Right Panel
// ─────────────────────────────────────────────
function RightPanel({state,selectedUe,channelCfg}) {
  const [activeTab,setActiveTab]=useState('metrics');
  const ues=state?.ues||{}; const metrics=state?.metrics||[];
  const globalStats=state?.global||{}; const handovers=state?.handover_events||[];
  const totalFromUes=Object.values(ues).reduce((acc,u)=>acc+(Number(u.throughput)||0),0);
  const numUesFromState=Object.keys(ues).length;
  const latestTotal=totalFromUes>0?totalFromUes:(globalStats.total_throughput??0);
  const latestAvgPerUe=numUesFromState>0?(latestTotal/numUesFromState):0;
  const tpHistory=metrics.map(m=>m.total_throughput||0);
  const sinrHistory=metrics.map(m=>m.avg_sinr||0);
  const selectedUeData=selectedUe?ues[selectedUe]:null;
  const ueColors=['#58a6ff','#3fb950','#d29922','#f85149','#bc8cff','#39d353','#ffa657','#ff7b72'];
  const perUeDatasets=Object.values(ues).map((ue,i)=>({label:ue.id,data:ue.throughput_history||[],color:ueColors[i%ueColors.length]}));

  const tabs=[
    {id:'metrics',label:'Metrics',icon:'📊'},
    {id:'ues',label:'UEs',icon:'📱'},
    {id:'charts',label:'Charts',icon:'📈'},
    {id:'handovers',label:'HO',icon:'🔄'},
    {id:'logs',label:'Logs',icon:'📋'},
  ];

  return (
    <div className="right-panel">
      <div style={{display:'flex',borderBottom:'1px solid #21262d',background:'#161b22'}}>
        {tabs.map(t=>(
          <button key={t.id} onClick={()=>setActiveTab(t.id)}
            style={{flex:1,padding:'8px 2px',fontSize:9,border:'none',cursor:'pointer',
              background:activeTab===t.id?'#1c2128':'transparent',
              color:activeTab===t.id?'#58a6ff':'#6e7681',
              borderBottom:activeTab===t.id?'2px solid #58a6ff':'2px solid transparent',
              fontWeight:activeTab===t.id?700:400}}>
            {t.icon}<br/>{t.label}
          </button>
        ))}
      </div>
      <div style={{overflowY:'auto',flex:1}}>

        {/* METRICS TAB — ThroughputLog removed; use Logs tab to download */}
        {activeTab==='metrics'&&(<>
          <AccordionSection title="Network Summary" icon="🌐" defaultOpen={true}>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6,marginBottom:6}}>
              {[
                ['Total TP',`${latestTotal.toFixed(0)} Mbps`,latestTotal>100?'#3fb950':'#d29922'],
                ['Avg/UE',`${latestAvgPerUe.toFixed(1)} Mbps`,'#58a6ff'],
                ['Avg SINR',`${(globalStats.avg_sinr||0).toFixed(1)} dB`,globalStats.avg_sinr>10?'#3fb950':globalStats.avg_sinr>0?'#d29922':'#f85149'],
                ['Pkt Loss',`${globalStats.packet_loss||0}%`,globalStats.packet_loss<5?'#3fb950':globalStats.packet_loss<20?'#d29922':'#f85149'],
                ['Handovers',globalStats.total_handovers||0,'#d29922'],
                ['gNBs/UEs',`${globalStats.num_gnbs||0} / ${globalStats.num_ues||0}`,'#8b949e'],
              ].map(([l,v,c])=>(
                <div key={l} className="stat-card">
                  <div className="stat-card-value" style={{color:c,fontSize:14}}>{v}</div>
                  <div className="stat-card-label">{l}</div>
                </div>
              ))}
            </div>
          </AccordionSection>
          <AccordionSection title="gNB Status" icon="📡" defaultOpen={false}>
            {Object.values(state?.gnbs||{}).length===0&&<div className="loading">No gNBs deployed</div>}
            {Object.values(state?.gnbs||{}).map(gnb=>(
              <AccordionSection key={gnb.id} title={gnb.id} icon="📡" defaultOpen={false} badge={`${gnb.connected_ues||0} UEs`}>
                <div style={{fontSize:10}}>
                  {[['TX Power',`${gnb.tx_power_dbm} dBm`,'#8b949e'],['Throughput',`${gnb.total_throughput?.toFixed(1)} Mbps`,'#3fb950'],['Position',`${gnb.x?.toFixed(0)}px / ${gnb.y?.toFixed(0)}px`,'#58a6ff']].map(([l,v,c])=>(
                    <div key={l} className="tooltip-row" style={{marginBottom:2}}><span className="tooltip-label">{l}:</span><span style={{color:c,fontWeight:600}}>{v}</span></div>
                  ))}
                </div>
              </AccordionSection>
            ))}
            {selectedUeData&&(
              <AccordionSection title={`${selectedUeData.id} Details`} icon="📱" defaultOpen={true}>
                <div style={{fontSize:10}}>
                  {[['Serving gNB',selectedUeData.serving_gnb,'#58a6ff'],['RSRP',`${selectedUeData.rsrp?.toFixed(1)} dBm`,rsrpColor(selectedUeData.rsrp)],['SINR',`${selectedUeData.sinr?.toFixed(1)} dB`,sinrColor(selectedUeData.sinr)],['Throughput',`${selectedUeData.throughput?.toFixed(1)} Mbps`,'#3fb950'],['Modulation',selectedUeData.modulation,'#bc8cff'],['Velocity',`${selectedUeData.velocity?.toFixed(1)} m/s`,'#8b949e'],['Handovers',selectedUeData.handover_count,'#d29922'],['Ping-Pong',selectedUeData.ping_pong_count,'#f85149']].map(([l,v,c])=>(
                    <div key={l} className="tooltip-row" style={{marginBottom:2}}><span className="tooltip-label">{l}:</span><span style={{color:c,fontWeight:600}}>{v}</span></div>
                  ))}
                </div>
              </AccordionSection>
            )}
          </AccordionSection>
        </>)}

        {/* UEs TAB */}
        {activeTab==='ues'&&(<>
          {Object.values(ues).length===0&&<div className="loading">No UEs deployed yet</div>}
          {Object.values(ues).map(ue=>(
            <div key={ue.id} className={`ue-list-item ${selectedUe===ue.id?'selected':''}`}>
              <div className="ue-list-header"><span className="ue-id">{ue.id}</span><span className="ue-serving">{ue.serving_gnb||'Disconnected'}</span></div>
              <div className="ue-metrics-grid">
                <div className="ue-metric"><span className="ue-metric-label">RSRP</span><span className="ue-metric-value" style={{color:rsrpColor(ue.rsrp)}}>{ue.rsrp?.toFixed(0)} dBm</span></div>
                <div className="ue-metric"><span className="ue-metric-label">SINR</span><span className="ue-metric-value" style={{color:sinrColor(ue.sinr)}}>{ue.sinr?.toFixed(1)} dB</span></div>
                <div className="ue-metric"><span className="ue-metric-label">Throughput</span><span className="ue-metric-value" style={{color:'#3fb950'}}>{ue.throughput?.toFixed(0)} Mbps</span></div>
                <div className="ue-metric"><span className="ue-metric-label">Modulation</span><span className="ue-metric-value" style={{color:'#bc8cff'}}>{ue.modulation}</span></div>
                <div className="ue-metric"><span className="ue-metric-label">Handovers</span><span className="ue-metric-value" style={{color:'#d29922'}}>{ue.handover_count}</span></div>
                <div className="ue-metric"><span className="ue-metric-label">Speed</span><span className="ue-metric-value">{ue.velocity?.toFixed(1)} m/s</span></div>
              </div>
            </div>
          ))}
        </>)}

        {/* CHARTS TAB */}
        {activeTab==='charts'&&(<>
          <AccordionSection title="Total Throughput vs Time" icon="📈" defaultOpen={true}>
            <LineChartWithDownload title="Total Throughput vs Time" filename="total_throughput_vs_time.png" data={tpHistory} label="Total Throughput" color="#3fb950" unit="Mbps" xLabel="Time (steps × 100ms)" yLabel="Throughput (Mbps)"/>
          </AccordionSection>
          <AccordionSection title="Per-UE Throughput" icon="📱" defaultOpen={false}>
            {perUeDatasets.length>0?<MultiLineChartWithDownload datasets={perUeDatasets} height={140} xLabel="Time (steps)" yLabel="Mbps"/>:<div className="loading">No UEs deployed</div>}
          </AccordionSection>
          <AccordionSection title="Avg SINR vs Time" icon="📡" defaultOpen={true}>
            <LineChartWithDownload title="Avg SINR vs Time" filename="avg_sinr_vs_time.png" data={sinrHistory} label="Avg SINR" color="#58a6ff" unit="dB" xLabel="Time (steps × 100ms)" yLabel="SINR (dB)"/>
          </AccordionSection>
          <AccordionSection title="Pathloss vs Distance" icon="📉" defaultOpen={false}>
            <PathlossChartWithDownload channelCfg={channelCfg}/>
          </AccordionSection>
          {selectedUe&&ues[selectedUe]&&(<>
            <AccordionSection title={`${selectedUe} — RSRP`} icon="📱" defaultOpen={true}>
              <LineChart data={ues[selectedUe].rsrp_history||[]} label="RSRP" color="#d29922" unit="dBm" height={100} xLabel="Time (steps)" yLabel="RSRP (dBm)"/>
            </AccordionSection>
            <AccordionSection title={`${selectedUe} — Throughput`} icon="📱" defaultOpen={true}>
              <LineChart data={ues[selectedUe].throughput_history||[]} label="Throughput" color="#3fb950" unit="Mbps" height={100} xLabel="Time (steps)" yLabel="Throughput (Mbps)"/>
            </AccordionSection>
          </>)}
        </>)}

        {/* HANDOVERS TAB */}
        {activeTab==='handovers'&&(<>
          <AccordionSection title="Handover Events" icon="🔄" defaultOpen={true} badge={globalStats.total_handovers||0}>
            <HandoverTable handovers={handovers}/>
          </AccordionSection>
        </>)}

        {/* LOGS TAB — both CSV downloads live here */}
        {activeTab==='logs'&&(<>
          <AccordionSection title="Throughput Log (CSV)" icon="📊" defaultOpen={true}>
            <ThroughputLog state={state}/>
          </AccordionSection>
          <AccordionSection title="Handover Log (CSV)" icon="🔄" defaultOpen={true}>
            <HandoverTable handovers={handovers} showDownloadButton={true}/>
          </AccordionSection>
        </>)}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Sidebar
// ─────────────────────────────────────────────
function Sidebar({state,onAddGnb,onAddUe,onStart,onStop,onReset,placeMode,setPlaceMode,
                  scenario,setScenario,simSpeed,setSimSpeed,params,setParams,
                  simDuration,setSimDuration,channelCfg,setChannelCfg,ueConfig,setUeConfig}) {
  const isRunning=state?.running||false;
  const numGnbs=Object.keys(state?.gnbs||{}).length;
  const numUes=Object.keys(state?.ues||{}).length;
  const [gnbConfig,setGnbConfig]=useState({tx_power:43,sectors:3});

  const applyChannelCfg=(patch)=>{
    const next={...channelCfg,...patch};
    setChannelCfg(next);
    fetch('/api/set_channel_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)});
  };
  const handleStart=()=>{
    let dur=simDuration;
    if(dur==null){const inp=window.prompt('Enter simulation duration in seconds:','15');if(inp===null)return;const p=parseFloat(inp);if(Number.isNaN(p)||p<=0){alert('Invalid duration.');return;}dur=p;}
    fetch('/api/start_simulation',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({scenario,speed:simSpeed,duration:dur,pathloss_model:channelCfg.pathloss_model,log_dist_n:channelCfg.log_dist_n,log_dist_shadow:channelCfg.log_dist_shadow,fading_model:channelCfg.fading_model})});
    onStart(dur);
  };
  const handleStop=()=>{fetch('/api/stop_simulation',{method:'POST'});onStop();};
  const handleReset=()=>{fetch('/api/reset',{method:'POST'});onReset();};

  return (
    <div className="sidebar">
      {/* Simulation Control */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Simulation</div>
        <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:8}}>
          <div className={`sim-status-dot ${isRunning?'running':''}`}></div>
          <span style={{fontSize:11,color:isRunning?'#3fb950':'#6e7681'}}>{isRunning?`Running  (t=${state?.sim_time?.toFixed(1)}s)`:'Stopped'}</span>
        </div>
        {!isRunning?<button className="btn btn-success" onClick={handleStart}>▶ Start Simulation</button>
                   :<button className="btn btn-danger"  onClick={handleStop}>⏹ Stop</button>}
        <button className="btn btn-secondary" onClick={handleReset}>↺ Reset</button>
        <div className="form-group" style={{marginTop:8}}>
          <label className="form-label">Simulation Speed: {simSpeed}x</label>
          <input type="range" min="0.5" max="10" step="0.5" value={simSpeed}
            onChange={e=>{const v=parseFloat(e.target.value);setSimSpeed(v);fetch('/api/set_speed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speed:v})});}}
            style={{width:'100%'}}/>
        </div>
      </div>

      {/* Duration */}
      <div className="form-group" style={{marginTop:8,padding:'0 12px'}}>
        <label className="form-label">Sim Duration (seconds)</label>
        <div style={{display:'flex',gap:6}}>
          {[10,20,30,60].map(s=>(
            <button key={s} onClick={()=>setSimDuration(simDuration===s?null:s)}
              style={{flex:1,padding:'4px 0',fontSize:11,borderRadius:6,border:`1px solid ${simDuration===s?'#58a6ff':'#30363d'}`,background:simDuration===s?'rgba(88,166,255,0.15)':'#1c2128',color:simDuration===s?'#58a6ff':'#8b949e',cursor:'pointer'}}>{s}s</button>
          ))}
        </div>
        <div style={{fontSize:10,color:'#6e7681',marginTop:6,textAlign:'center'}}>
          {simDuration==null?'No preset — Start will prompt for duration.':`Selected: ${simDuration}s`}
        </div>
      </div>

      {/* Propagation Model */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Propagation Model</div>
        <div className="form-group">
          <label className="form-label">Pathloss Model</label>
          <select className="form-control" value={channelCfg.pathloss_model} onChange={e=>applyChannelCfg({pathloss_model:e.target.value})}>
            <option value="3GPP">3GPP TR 38.901</option>
            <option value="LogDistance">Log Distance</option>
          </select>
        </div>
        {channelCfg.pathloss_model==='3GPP'&&(<>
          <label className="form-label" style={{marginTop:6}}>Outdoor Scenario</label>
          <div className="scenario-buttons">
            {['UMa','UMi','RMa'].map(s=>(
              <button key={s} className={`scenario-btn ${scenario===s?'active':''}`} onClick={()=>{setScenario(s);applyChannelCfg({scenario:s});}}>
                {s==='UMa'?'🌆':s==='UMi'?'🏢':'🌄'}<br/>{s==='UMa'?'Urban Macro':s==='UMi'?'Urban Micro':'Rural Macro'}
              </button>
            ))}
          </div>
        </>)}
        {channelCfg.pathloss_model==='LogDistance'&&(<>
          <div className="form-group" style={{marginTop:6}}>
            <label className="form-label">Path Loss Exponent (n): {channelCfg.log_dist_n?.toFixed(1)}</label>
            <input type="range" min="1.6" max="6" step="0.1" value={channelCfg.log_dist_n??3.5} onChange={e=>applyChannelCfg({log_dist_n:parseFloat(e.target.value)})} style={{width:'100%'}}/>
          </div>
          <div className="form-group">
            <label className="form-label">Shadow Fading</label>
            <select className="form-control" value={channelCfg.log_dist_shadow} onChange={e=>applyChannelCfg({log_dist_shadow:e.target.value})}>
              <option value="lognormal">Log-Normal</option>
              <option value="none">None</option>
            </select>
          </div>
        </>)}
        <div className="form-group" style={{marginTop:6}}>
          <label className="form-label">Fading Model</label>
          <select className="form-control" value={channelCfg.fading_model} onChange={e=>applyChannelCfg({fading_model:e.target.value})}>
            <option value="Rayleigh">Rayleigh</option>
            <option value="none">None</option>
          </select>
        </div>
        <div style={{fontSize:10,color:'#6e7681',marginTop:6,padding:'4px 6px',background:'rgba(88,166,255,0.06)',borderRadius:6,border:'1px solid rgba(88,166,255,0.15)'}}>
          {channelCfg.pathloss_model==='3GPP'?`3GPP TR 38.901 · ${scenario} · ${channelCfg.fading_model}`:`Log Distance · n=${channelCfg.log_dist_n?.toFixed(1)} · shadow=${channelCfg.log_dist_shadow} · ${channelCfg.fading_model}`}
        </div>
      </div>

      {/* Deploy gNB */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Deploy gNB ({numGnbs})</div>
        <div className="form-group">
          <label className="form-label">TX Power (dBm)</label>
          <input type="range" min="20" max="50" value={gnbConfig.tx_power} onChange={e=>setGnbConfig(p=>({...p,tx_power:parseInt(e.target.value)}))} style={{width:'100%'}}/>
          <div style={{textAlign:'right',fontSize:10,color:'#6e7681'}}>{gnbConfig.tx_power} dBm</div>
        </div>
        <div className="form-group">
          <label className="form-label">Sectors</label>
          <select className="form-control" value={gnbConfig.sectors} onChange={e=>setGnbConfig(p=>({...p,sectors:parseInt(e.target.value)}))}>
            <option value={1}>1 Sector (Omni)</option>
            <option value={3}>3 Sectors</option>
          </select>
        </div>
        <button className={`btn ${placeMode==='gnb'?'btn-primary':'btn-secondary'}`} onClick={()=>setPlaceMode(placeMode==='gnb'?null:'gnb')}>
          📡 {placeMode==='gnb'?'🟢 Placing… (Esc to stop)':'Place gNB'}
        </button>
      </div>

      {/* Deploy UE */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Deploy UE ({numUes})</div>
        <div className="form-group">
          <label className="form-label">Mobility Model</label>
          <select className="form-control" value={ueConfig.mobility} onChange={e=>setUeConfig(p=>({...p,mobility:e.target.value}))}>
            <option value="random_waypoint">Random Waypoint</option>
            <option value="constant_velocity">Constant Velocity</option>
            <option value="pedestrian">Pedestrian</option>
            <option value="file_based">File Based</option>
          </select>
        </div>
        {ueConfig.mobility!=='pedestrian'&&ueConfig.mobility!=='file_based'&&(
          <div className="form-group">
            <label className="form-label">Speed: {ueConfig.speed} m/s</label>
            <input type="range" min="1" max="30" value={ueConfig.speed} onChange={e=>setUeConfig(p=>({...p,speed:parseFloat(e.target.value)}))} style={{width:'100%'}}/>
          </div>
        )}
        {ueConfig.mobility==='pedestrian'&&(
          <div style={{fontSize:10,color:'#8b949e',background:'rgba(88,166,255,0.07)',border:'1px solid rgba(88,166,255,0.2)',borderRadius:6,padding:'6px 8px',marginBottom:6}}>
            🚶 Walk speed 0.8–1.8 m/s · short hops · pause 2–8 s per stop<br/>
            <span style={{color:'#6e7681'}}>Speed slider not used for this model.</span>
          </div>
        )}
        {ueConfig.mobility==='file_based'&&<FileMobilityUploader/>}
        <button className={`btn ${placeMode==='ue'?'btn-primary':'btn-secondary'}`} onClick={()=>setPlaceMode(placeMode==='ue'?null:'ue')}>
          📱 {placeMode==='ue'?'🟢 Placing… (Esc to stop)':'Place UE'}
        </button>
        <button className="btn btn-ghost" onClick={()=>{
          for(let i=0;i<3;i++) setTimeout(()=>fetch('/api/add_ue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:50+Math.random()*700,y:50+Math.random()*480,mobility:ueConfig.mobility,speed:ueConfig.speed})}),i*50);
        }}>⚡ Quick Deploy 3 UEs</button>
      </div>

      {/* Handover Params */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Handover Params</div>
        <div className="form-group">
          <label className="form-label">Hysteresis: {params.hysteresis} dB</label>
          <input type="range" min="0" max="10" step="0.5" value={params.hysteresis}
            onChange={e=>{const v=parseFloat(e.target.value);setParams(p=>({...p,hysteresis:v}));fetch('/api/set_params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hysteresis:v})});}} style={{width:'100%'}}/>
        </div>
        <div className="form-group">
          <label className="form-label">TTT: {params.ttt*100} ms</label>
          <input type="range" min="1" max="10" value={params.ttt}
            onChange={e=>{const v=parseInt(e.target.value);setParams(p=>({...p,ttt:v}));fetch('/api/set_params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ttt_steps:v})});}} style={{width:'100%'}}/>
        </div>
      </div>

      {/* Event Log */}
      <div className="sidebar-section">
        <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:8}}>
          <div className="sidebar-section-title" style={{margin:0}}>Event Log</div>
        </div>
        <div className="event-log">
          {(state?.event_log||[]).slice().reverse().map((ev,i)=>(
            <div key={i} className={`event-item ${ev.message?.includes('Handover')?'event-handover':ev.message?.includes('started')?'event-start':''}`}>
              <span className="event-time">{ev.time?.toFixed(1)}s</span>
              <span className="event-msg">{ev.message}</span>
            </div>
          ))}
          {(!state?.event_log||state.event_log.length===0)&&<div style={{color:'#6e7681',fontSize:10,textAlign:'center',padding:8}}>No events yet</div>}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Main App
// ─────────────────────────────────────────────
function App() {
  const [state,       setState]       = useState(null);
  const [placeMode,   setPlaceMode]   = useState(null);
  const [selectedUe,  setSelectedUe]  = useState(null);
  const [scenario,    setScenario]    = useState('UMa');
  const [simSpeed,    setSimSpeed]    = useState(1);
  const [params,      setParams]      = useState({hysteresis:3,ttt:3});
  const [simDuration, setSimDuration] = useState(null);
  const [darkMode,    setDarkMode]    = useState(true);
  const [cursorPos,   setCursorPos]   = useState({x:0,y:0});
  const [channelCfg,  setChannelCfg]  = useState({pathloss_model:'3GPP',scenario:'UMa',log_dist_n:3.5,log_dist_shadow:'lognormal',fading_model:'Rayleigh'});
  const [ueConfig,    setUeConfig]    = useState({mobility:'random_waypoint',speed:3});
  const simTimerRef = useRef(null);

  useEffect(()=>{ document.documentElement.setAttribute('data-theme',darkMode?'dark':'light'); },[darkMode]);

  useEffect(()=>{
    const es=new EventSource('/api/stream');
    es.onmessage=(e)=>{try{setState(JSON.parse(e.data));}catch{}};
    return()=>es.close();
  },[]);

  const handleStart=useCallback((duration)=>{
    if(simTimerRef.current){clearTimeout(simTimerRef.current);simTimerRef.current=null;}
    simTimerRef.current=setTimeout(()=>{fetch('/api/stop_simulation',{method:'POST'});simTimerRef.current=null;},duration*1000);
  },[]);
  const handleStop=useCallback(()=>{
    if(simTimerRef.current){clearTimeout(simTimerRef.current);simTimerRef.current=null;}
    fetch('/api/stop_simulation',{method:'POST'});
  },[]);
  const handlePlaceGnb=useCallback((x,y)=>{ fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,tx_power:43,num_sectors:3})}); },[]);
  const handlePlaceUe=useCallback((x,y)=>{ fetch('/api/add_ue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,mobility:ueConfig.mobility,speed:ueConfig.speed})}); },[ueConfig]);

  useEffect(()=>{
    const onKey=(e)=>{if(e.key==='Escape')setPlaceMode(null);};
    window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey);
  },[]);

  return (
    <div className="app-container">
      <TopNav state={state} scenario={scenario} channelCfg={channelCfg}/>
      <Sidebar state={state} onAddGnb={handlePlaceGnb} onAddUe={handlePlaceUe}
        onStart={handleStart} onStop={handleStop} onReset={()=>setState(null)}
        placeMode={placeMode} setPlaceMode={setPlaceMode}
        scenario={scenario} setScenario={setScenario}
        simSpeed={simSpeed} setSimSpeed={setSimSpeed}
        params={params} setParams={setParams}
        simDuration={simDuration} setSimDuration={setSimDuration}
        channelCfg={channelCfg} setChannelCfg={setChannelCfg}
        ueConfig={ueConfig} setUeConfig={setUeConfig}/>
      <div className="main-area">
        <div className="canvas-toolbar">
          <span className="canvas-toolbar-title">Network Topology</span>
          <div style={{flex:1}}/>
          {placeMode&&(
            <div className="placement-indicator" style={{position:'static',transform:'none',fontSize:11,padding:'4px 12px'}}>
              Click to place {placeMode==='gnb'?'📡 gNB':'📱 UE'} — or press Esc to cancel
            </div>
          )}
          <button className="btn btn-ghost" style={{width:'auto',fontSize:10,padding:'4px 10px'}} onClick={()=>{
            fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:200,y:200})});
            setTimeout(()=>fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:600,y:200})}),50);
            setTimeout(()=>fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:400,y:440})}),100);
          }}>⚡ Default Topology</button>
        </div>

        <NetworkCanvas state={state}
          onPlaceGnb={handlePlaceGnb} onPlaceUe={handlePlaceUe}
          placeMode={placeMode} selectedUe={selectedUe} setSelectedUe={setSelectedUe}
          onCursorMove={(x,y)=>setCursorPos({x,y})}/>

        {/* ── Cursor / status bar ── */}
        <div style={{flexShrink:0,padding:'4px 12px',background:'var(--bg-secondary)',borderTop:'1px solid var(--border)',display:'flex',alignItems:'center',gap:16,fontSize:11}}>
          <span style={{color:'var(--text-muted)'}}>Canvas Cursor:</span>
          <span style={{color:'#58a6ff',fontFamily:'monospace'}}>X: <strong>{cursorPos.x} px</strong> ({(cursorPos.x*5).toFixed(0)} m)</span>
          <span style={{color:'#58a6ff',fontFamily:'monospace'}}>Y: <strong>{cursorPos.y} px</strong> ({(cursorPos.y*5).toFixed(0)} m)</span>
          <span style={{color:'var(--text-muted)'}}>|</span>
          <span style={{color:'#3fb950',fontFamily:'monospace'}}>gNBs: {Object.keys(state?.gnbs||{}).length} &nbsp;|&nbsp; UEs: {Object.keys(state?.ues||{}).length}</span>
          {placeMode&&<span style={{color:'#d29922'}}>📍 Placing: {placeMode.toUpperCase()}</span>}
          <div style={{marginLeft:'auto'}}>
            <button onClick={()=>setDarkMode(d=>!d)} title={darkMode?'Switch to Light Mode':'Switch to Dark Mode'}
              style={{display:'flex',alignItems:'center',gap:6,padding:'4px 12px',borderRadius:20,cursor:'pointer',
                border:`1px solid ${darkMode?'#58a6ff':'#d0d7de'}`,background:darkMode?'#161b22':'#ffffff',
                color:darkMode?'#e6edf3':'#1f2328',fontSize:11,fontWeight:600,transition:'all 0.3s'}}>
              <div style={{width:32,height:16,borderRadius:8,position:'relative',background:darkMode?'#58a6ff':'#d0d7de',transition:'background 0.3s'}}>
                <div style={{position:'absolute',top:2,left:darkMode?16:2,width:12,height:12,borderRadius:'50%',background:'white',transition:'left 0.3s'}}/>
              </div>
              {darkMode?'🌙 Dark':'☀️ Light'}
            </button>
          </div>
        </div>
      </div>
      <RightPanel state={state} selectedUe={selectedUe} channelCfg={channelCfg}/>
    </div>
  );
}

ReactDOM.render(<App/>, document.getElementById('root'));
