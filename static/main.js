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
      } catch (e) { console.warn(e); }
    };
    img.src = sourceCanvas.toDataURL('image/png');
  } catch (e) { console.warn(e); }
}

// ─────────────────────────────────────────────
//  Heatmap overlay
// ─────────────────────────────────────────────
function hslToRgb(h, s, l) {
  let r, g, b;
  if (s === 0) { r = g = b = l; }
  else {
    const q = l < 0.5 ? l*(1+s) : l+s-l*s, p = 2*l-q;
    const hue2rgb = (p,q,t) => {
      if (t<0) t+=1; if (t>1) t-=1;
      if (t<1/6) return p+(q-p)*6*t;
      if (t<1/2) return q;
      if (t<2/3) return p+(q-p)*(2/3-t)*6;
      return p;
    };
    r=hue2rgb(p,q,h+1/3); g=hue2rgb(p,q,h); b=hue2rgb(p,q,h-1/3);
  }
  return [Math.round(r*255), Math.round(g*255), Math.round(b*255)];
}

function drawHeatmap(ctx, W, H, gnbs) {
  const gnbList = Object.values(gnbs);
  if (!gnbList.length) return;
  const step = 8;
  const offscreen = document.createElement('canvas');
  offscreen.width = W; offscreen.height = H;
  const oc = offscreen.getContext('2d');
  const imgData = oc.createImageData(W, H);
  const data = imgData.data;
  for (let py = 0; py < H; py += step) {
    for (let px = 0; px < W; px += step) {
      let bestRsrp = -Infinity;
      for (const gnb of gnbList) {
        const dist = Math.sqrt((px-gnb.x)**2 + (py-gnb.y)**2) || 0.1;
        const rsrp = (gnb.tx_power_dbm||43) - (40 + 30*Math.log10(Math.max(dist,1)));
        if (rsrp > bestRsrp) bestRsrp = rsrp;
      }
      const norm = Math.max(0, Math.min(1, (bestRsrp-(-110))/70));
      const hue = (1-norm)*240;
      const [r,g,b] = hslToRgb(hue/360, 0.95, 0.5);
      const alpha = Math.round(norm*170);
      for (let dy=0; dy<step && py+dy<H; dy++) {
        for (let dx=0; dx<step && px+dx<W; dx++) {
          const i = ((py+dy)*W + (px+dx))*4;
          data[i]=r; data[i+1]=g; data[i+2]=b; data[i+3]=alpha;
        }
      }
    }
  }
  oc.putImageData(imgData, 0, 0);
  ctx.save();
  ctx.filter = 'blur(10px)';
  ctx.drawImage(offscreen, 0, 0);
  ctx.filter = 'none';
  ctx.restore();
}

// ─────────────────────────────────────────────
//  Mobility trace
// ─────────────────────────────────────────────
function drawMobilityTrace(ctx, ue) {
  const hist = ue.position_history;
  if (!hist || hist.length < 2) return;
  const color = sinrColor(ue.sinr);
  const r = parseInt(color.slice(1,3),16);
  const g = parseInt(color.slice(3,5),16);
  const b = parseInt(color.slice(5,7),16);
  ctx.save();
  for (let i = 1; i < hist.length; i++) {
    const alpha = 0.08 + 0.72 * (i / hist.length);
    ctx.strokeStyle = `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(hist[i-1].x, hist[i-1].y);
    ctx.lineTo(hist[i].x, hist[i].y);
    ctx.stroke();
  }
  for (let i = 0; i < hist.length; i += 10) {
    const alpha = 0.15 + 0.65 * (i / hist.length);
    ctx.beginPath();
    ctx.arc(hist[i].x, hist[i].y, 1.5, 0, 2*Math.PI);
    ctx.fillStyle = `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
    ctx.fill();
  }
  ctx.restore();
}

// ─────────────────────────────────────────────
//  Per-UE Mobility Editor
// ─────────────────────────────────────────────
function UeMobilityEditor({ue}) {
  const [model,     setModel]     = useState(ue.mobility_model||'none');
  const [speed,     setSpeed]     = useState(Math.max(1,Math.round(ue.velocity||3)));
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [uploadMsg, setUploadMsg] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  useEffect(()=>{ if(ue.mobility_model) setModel(ue.mobility_model); },[ue.id]);

  const MODELS = [
    {value:'none',             label:'⛔ None (stationary)'},
    {value:'random_walk',      label:'🎲 Random Walk'},
    {value:'random_waypoint',  label:'🗺️ Random Waypoint'},
    {value:'constant_velocity',label:'➡️ Constant Velocity'},
    {value:'pedestrian',       label:'🚶 Pedestrian'},
    {value:'file_based',       label:'📂 File Based (CSV)'},
  ];

  function apply() {
    setSaving(true);
    fetch('/api/set_ue_mobility',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ue_id:ue.id,mobility:model,speed:parseFloat(speed)})
    }).then(r=>r.json()).then(()=>{
      setSaving(false);setSaved(true);setTimeout(()=>setSaved(false),1600);
    }).catch(()=>setSaving(false));
  }

  function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setUploadMsg('');
    const fd = new FormData();
    fd.append('file', file);
    fd.append('speed', speed.toString());  // Include speed parameter
    fetch('/api/upload_mobility_trace',{method:'POST',body:fd})
      .then(r=>r.json())
      .then(d=>{
        setUploading(false);
        setUploadMsg(d.success ? `✅ ${d.message}` : `❌ ${d.error}`);
        if(d.success) setModel('file_based');
      })
      .catch(()=>{setUploading(false);setUploadMsg('❌ Network error');});
    e.target.value='';
  }

  const iS={width:'100%',fontSize:10,padding:'3px 6px',borderRadius:4,
    background:'var(--bg-secondary)',border:'1px solid var(--border)',color:'var(--text-primary)',marginBottom:6};
  const lS={fontSize:9,color:'var(--text-muted)',marginBottom:2,display:'block'};
  const showSpeed = model!=='none' && model!=='pedestrian';

  return (
    <div style={{marginTop:6,padding:'8px 10px',background:'var(--bg-primary)',borderRadius:6,border:'1px solid #30363d'}}>
      <div style={{fontSize:9,fontWeight:700,color:'#58a6ff',marginBottom:6,letterSpacing:'0.5px'}}>✏️ MOBILITY CONFIG</div>
      <label style={lS}>Model</label>
      <select style={iS} value={model} onChange={e=>setModel(e.target.value)}>
        {MODELS.map(m=><option key={m.value} value={m.value}>{m.label}</option>)}
      </select>

      {showSpeed&&(<>
        <label style={lS}>Speed: {speed} m/s</label>
        <input type="range" min="1" max="30" value={speed}
          onChange={e=>setSpeed(parseInt(e.target.value))} style={{width:'100%',marginBottom:4}}/>
        <div style={{display:'flex',justifyContent:'space-between',fontSize:9,color:'#6e7681',marginBottom:6}}>
          <span>1 (walk)</span><span>15 (car)</span><span>30 (fast)</span>
        </div>
      </>)}

      {model==='pedestrian'&&(
        <div style={{fontSize:9,color:'#6e7681',marginBottom:6,lineHeight:1.4}}>
          Speed auto-varies 0.8–1.8 m/s with stop-and-go pauses.
        </div>
      )}

      {model==='file_based'&&(
        <div style={{marginBottom:6}}>
          <div style={{fontSize:9,color:'#6e7681',marginBottom:4,lineHeight:1.5}}>
            Upload CSV: <strong style={{color:'#58a6ff'}}>UE_ID, x, y</strong> (optional: <strong style={{color:'#58a6ff'}}>t/time/timestamp</strong>)<br/>
            Each row = one position at specific timestamp (seconds).<br/>
            If no timestamp column, uses 0.1s intervals automatically.
          </div>
          <input ref={fileRef} type="file" accept=".csv" onChange={handleFileUpload} style={{display:'none'}}/>
          <button onClick={()=>fileRef.current?.click()} disabled={uploading}
            style={{width:'100%',fontSize:10,padding:'4px 0',borderRadius:4,cursor:'pointer',
              background:'#1f6feb',border:'none',color:'#fff',fontWeight:600,marginBottom:4}}>
            {uploading?'⏳ Uploading…':'📂 Choose CSV File'}
          </button>
          {uploadMsg&&(
            <div style={{fontSize:9,color:uploadMsg.startsWith('✅')?'#3fb950':'#f85149',
              padding:'3px 6px',background:'var(--bg-secondary)',borderRadius:3,marginBottom:4,wordBreak:'break-word'}}>
              {uploadMsg}
            </div>
          )}
        </div>
      )}

      <button onClick={apply} disabled={saving}
        style={{width:'100%',fontSize:10,padding:'4px 0',borderRadius:4,cursor:'pointer',
          background:saved?'#238636':'#1f6feb',border:'none',color:'#fff',fontWeight:600}}>
        {saving?'⏳ Applying…':saved?'✅ Applied!':'▶ Apply'}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Charts
// ─────────────────────────────────────────────
function LineChart({data,label,color,unit,height=120}) {
  const ref=useRef(null),chartRef=useRef(null);
  useEffect(()=>{
    if(!ref.current) return;
    if(chartRef.current) chartRef.current.destroy();
    chartRef.current=new Chart(ref.current,{type:'line',
      data:{labels:data.map((_,i)=>i),datasets:[{label:`${label} (${unit})`,data,borderColor:color,backgroundColor:color+'22',borderWidth:1.5,pointRadius:0,tension:0.3,fill:true}]},
      options:{animation:false,responsive:true,maintainAspectRatio:false,
        scales:{x:{display:false},y:{display:true,ticks:{color:'#6e7681',font:{size:9}},grid:{color:'rgba(48,54,61,0.5)'}}},
        plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}}});
    return()=>{if(chartRef.current){chartRef.current.destroy();chartRef.current=null;}};
  },[data.length]);
  useEffect(()=>{
    if(!chartRef.current) return;
    chartRef.current.data.labels=data.map((_,i)=>i);
    chartRef.current.data.datasets[0].data=data;
    chartRef.current.update('none');
  },[data]);
  return <div style={{height,position:'relative'}}><canvas ref={ref}/></div>;
}

function LineChartWithDownload({title,filename,data,label,color,unit,xLabel,yLabel}) {
  const ref=useRef(null),chartRef=useRef(null);
  useEffect(()=>{
    if(!ref.current) return;
    if(chartRef.current) chartRef.current.destroy();
    chartRef.current=new Chart(ref.current,{type:'line',
      data:{labels:data.map((_,i)=>i),datasets:[{label:`${label} (${unit})`,data,borderColor:color,backgroundColor:color+'22',borderWidth:1.5,pointRadius:0,tension:0.3,fill:true}]},
      options:{animation:false,responsive:true,maintainAspectRatio:false,
        scales:{x:{display:true,title:{display:!!xLabel,text:xLabel,color:'#6e7681',font:{size:9}},ticks:{color:'#6e7681',font:{size:8},maxTicksLimit:8}},
          y:{display:true,title:{display:!!yLabel,text:yLabel,color:'#6e7681',font:{size:9}},ticks:{color:'#6e7681',font:{size:9}},grid:{color:'rgba(48,54,61,0.5)'}}},
        plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}}}});
    return()=>{if(chartRef.current){chartRef.current.destroy();chartRef.current=null;}};
  },[data.length]);
  useEffect(()=>{
    if(!chartRef.current) return;
    chartRef.current.data.labels=data.map((_,i)=>i);
    chartRef.current.data.datasets[0].data=data;
    chartRef.current.update('none');
  },[data]);
  return (
    <div>
      <div style={{display:'flex',justifyContent:'flex-end',marginBottom:4}}>
        <button onClick={()=>downloadCanvasWithTitle(ref.current,title,filename)}
          style={{fontSize:9,padding:'2px 8px',borderRadius:4,cursor:'pointer',background:'#21262d',border:'1px solid #30363d',color:'#8b949e'}}>⬇ PNG</button>
      </div>
      <div style={{height:130,position:'relative'}}><canvas ref={ref}/></div>
    </div>
  );
}

function PathlossChart({channelCfg}) {
  const ref=useRef(null),chRef=useRef(null);
  const distances=Array.from({length:100},(_,i)=>(i+1)*10);
  function computePL(d) {
    if(!channelCfg) return 0;
    if(channelCfg.pathloss_model==='LogDistance') {
      const n=channelCfg.log_dist_n||3.0;
      return 20*Math.log10(4*Math.PI*0.5/0.3)+10*n*Math.log10(Math.max(d,1));
    }
    const h_bs=25,h_ut=1.5,fc=3.5,d_bp=4*h_bs*h_ut*fc*1e9/(3e8);
    if(d<d_bp) return 28+22*Math.log10(Math.max(d,1))+20*Math.log10(fc);
    return 28+40*Math.log10(Math.max(d,1))+20*Math.log10(fc)-9*Math.log10(d_bp**2+(h_bs-h_ut)**2);
  }
  useEffect(()=>{
    if(!ref.current) return;
    if(chRef.current) chRef.current.destroy();
    chRef.current=new Chart(ref.current,{type:'line',
      data:{labels:distances,datasets:[{label:'Pathloss (dB)',data:distances.map(computePL),borderColor:'#bc8cff',backgroundColor:'#bc8cff22',borderWidth:1.5,pointRadius:0,tension:0.2,fill:true}]},
      options:{animation:false,responsive:true,maintainAspectRatio:false,
        scales:{x:{display:true,title:{display:true,text:'Distance (m)',color:'#6e7681',font:{size:9}},ticks:{color:'#6e7681',font:{size:8},maxTicksLimit:8}},
          y:{display:true,title:{display:true,text:'Path Loss (dB)',color:'#6e7681',font:{size:9}},ticks:{color:'#6e7681',font:{size:9}},grid:{color:'rgba(48,54,61,0.5)'}}},
        plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false,callbacks:{title:c=>`Dist: ${c[0].label}m`,label:c=>`PL: ${c.parsed.y.toFixed(1)} dB`}}}}});
    return()=>{if(chRef.current){chRef.current.destroy();chRef.current=null;}};
  },[channelCfg]);
  return (
    <div>
      <div style={{display:'flex',justifyContent:'flex-end',marginBottom:4}}>
        <button onClick={()=>downloadCanvasWithTitle(ref.current,
          channelCfg?.pathloss_model==='LogDistance'?`Log Distance PL (n=${(channelCfg?.log_dist_n??3.5).toFixed(1)})`:'Pathloss vs Distance (3GPP TR 38.901)',
          'pathloss_vs_distance.png')}
          style={{fontSize:9,padding:'2px 8px',borderRadius:4,cursor:'pointer',background:'#21262d',border:'1px solid #30363d',color:'#8b949e'}}>⬇ PNG</button>
      </div>
      <div style={{height:130,position:'relative'}}><canvas ref={ref}/></div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Single-UE SINR vs Time chart with HO markers
//  One Chart.js instance per handover UE
// ─────────────────────────────────────────────
function SingleUeHandoverChart({ ueId, color, metrics, handovers }) {
  const canvasRef = useRef(null);
  const chartRef  = useRef(null);

  // Build SINR line data from per-step metrics snapshots
  function getLineData() {
    return metrics
      .filter(m => m.ue_sinrs && ueId in m.ue_sinrs)
      .map(m => ({ x: parseFloat(m.time), y: m.ue_sinrs[ueId] }));
  }

  // Build HO marker data — (time, sinr_at_handover) pairs for this UE
  function getHoData() {
    return handovers
      .filter(h => h.ue_id === ueId)
      .map(h => ({
        x:    parseFloat(h.time),
        y:    parseFloat(h.sinr ?? 0),
        from: h.serving || h.from || '?',
        to:   h.target  || '?',
        rsrp: h.rsrp,
      }));
  }

  // ── initial build ─────────────────────────
  useEffect(() => {
    if (!canvasRef.current) return;
    if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }

    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        datasets: [
          {
            // Dataset 0 — SINR trace line
            label: `${ueId} SINR`,
            data: getLineData(),
            borderColor: color,
            backgroundColor: color + '18',
            borderWidth: 1.8,
            pointRadius: 0,
            tension: 0.25,
            fill: true,
            parsing: false,
            order: 2,
            type: 'line',
          },
          {
            // Dataset 1 — HO event markers (scatter overlay)
            label: `${ueId} HO`,
            data: getHoData(),
            type: 'scatter',
            backgroundColor: '#f85149',
            borderColor: '#ffffff',
            borderWidth: 2,
            pointRadius: 8,
            pointHoverRadius: 10,
            pointStyle: 'circle',
            parsing: false,
            order: 1,
          },
        ],
      },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: {
            type: 'linear',
            title: { display: true, text: 'Simulation Time (s)', color: '#6e7681', font: { size: 9 } },
            ticks: { color: '#6e7681', font: { size: 8 }, maxTicksLimit: 10 },
            grid: { color: 'rgba(48,54,61,0.4)' },
          },
          y: {
            title: { display: true, text: 'SINR (dB)', color: '#6e7681', font: { size: 9 } },
            ticks: { color: '#6e7681', font: { size: 9 } },
            grid: { color: 'rgba(48,54,61,0.4)' },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: ctx => {
                const isHO = ctx[0]?.dataset?.label?.endsWith(' HO');
                return isHO ? `🔴 Handover — ${ueId}` : ueId;
              },
              label: ctx => {
                const isHO = ctx.dataset.label.endsWith(' HO');
                const t    = ctx.parsed.x.toFixed(2);
                const sinr = ctx.parsed.y.toFixed(1);
                if (isHO) {
                  const pt = ctx.raw;
                  return [
                    `  Time  : ${t} s`,
                    `  SINR  : ${sinr} dB  ← serving at HO`,
                    `  From  : ${pt.from}  →  ${pt.to}`,
                    `  RSRP  : ${pt.rsrp?.toFixed(1)} dBm`,
                  ];
                }
                return `  t=${t}s   SINR=${sinr} dB`;
              },
            },
          },
        },
      },
    });

    return () => {
      if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // build once on mount

  // ── live SINR line update ─────────────────
  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.data.datasets[0].data = getLineData();
    chartRef.current.update('none');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metrics]);

  // ── HO markers update ─────────────────────
  useEffect(() => {
    if (!chartRef.current) return;
    chartRef.current.data.datasets[1].data = getHoData();
    chartRef.current.update('none');
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handovers.length]);

  const uHOs    = handovers.filter(h => h.ue_id === ueId);
  const lastHO  = uHOs[uHOs.length - 1];

  return (
    <div style={{
      marginBottom: 12,
      border: `1px solid ${color}33`,
      borderRadius: 6,
      overflow: 'hidden',
      background: 'var(--bg-primary)',
    }}>
      {/* ── Card header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '5px 10px',
        background: `${color}12`,
        borderBottom: `1px solid ${color}33`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            background: color, flexShrink: 0,
          }}/>
          <span style={{ fontSize: 11, fontWeight: 700, color }}>{ueId}</span>
          <span style={{
            fontSize: 9, color: '#6e7681',
            background: 'var(--bg-card)', borderRadius: 10,
            padding: '1px 7px', border: '1px solid var(--border)',
          }}>
            {uHOs.length} handover{uHOs.length !== 1 ? 's' : ''}
          </span>
          {lastHO && (
            <span style={{ fontSize: 9, color: '#8b949e' }}>
              last @ {lastHO.time?.toFixed(1)}s
              &nbsp;·&nbsp;
              {lastHO.serving||lastHO.from} → {lastHO.target}
              &nbsp;·&nbsp;
              SINR {lastHO.sinr?.toFixed(1)} dB
            </span>
          )}
        </div>
        {/* legend hint + download */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: '#6e7681' }}>
            <div style={{
              width: 9, height: 9, borderRadius: '50%',
              background: '#f85149', border: '2px solid #fff', flexShrink: 0,
            }}/>
            <span>HO event</span>
          </div>
          <button
            onClick={() => downloadCanvasWithTitle(
              canvasRef.current,
              `SINR vs Time — ${ueId}`,
              `sinr_${ueId.replace('-','')}.png`,
            )}
            style={{
              fontSize: 9, padding: '2px 7px', borderRadius: 4, cursor: 'pointer',
              background: '#21262d', border: '1px solid #30363d', color: '#8b949e',
            }}
          >⬇ PNG</button>
        </div>
      </div>

      {/* ── Chart ── */}
      <div style={{ height: 180, padding: '6px 8px 4px' }}>
        <canvas ref={canvasRef}/>
      </div>

      {/* ── Per-HO event detail rows ── */}
      <div style={{
        padding: '4px 10px 6px',
        display: 'flex', flexWrap: 'wrap', gap: 4,
      }}>
        {uHOs.map((ho, i) => (
          <div key={i} style={{
            fontSize: 9, padding: '2px 8px', borderRadius: 10,
            background: 'var(--bg-card)', border: '1px solid #30363d',
            color: '#8b949e',
            display: 'flex', alignItems: 'center', gap: 5,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: '#f85149', flexShrink: 0,
            }}/>
            <span style={{ color: '#e6edf3', fontWeight: 600 }}>{ho.time?.toFixed(1)}s</span>
            <span>{ho.serving||ho.from} → {ho.target}</span>
            <span style={{
              color: ho.sinr > 10 ? '#3fb950' : ho.sinr > 0 ? '#d29922' : '#f85149',
              fontWeight: 600,
            }}>{ho.sinr?.toFixed(1)} dB</span>
            {ho.ping_pong && <span style={{ color: '#f85149' }}>⚠ PP</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Container: one SingleUeHandoverChart per HO UE
// ─────────────────────────────────────────────
function HandoverSINRChart({ state }) {
  const metrics   = state?.metrics         || [];
  const handovers = state?.handover_events || [];

  const LINE_COLORS = [
    '#58a6ff','#3fb950','#d29922','#bc8cff',
    '#f0883e','#39d353','#e6edf3','#79c0ff',
  ];

  const hoUeIds = [...new Set(handovers.map(h => h.ue_id))]
    .sort((a, b) => {
      const na = parseInt(a.replace(/\D/g,'')) || 0;
      const nb = parseInt(b.replace(/\D/g,'')) || 0;
      return na - nb;
    });

  if (hoUeIds.length === 0) {
    return (
      <div style={{
        textAlign: 'center', padding: '24px 8px',
        color: '#6e7681', fontSize: 10, lineHeight: 1.8,
      }}>
        <div style={{ fontSize: 24, marginBottom: 6 }}>📡</div>
        No handovers yet.<br/>
        Deploy ≥ 2 gNBs with mobile UEs and start the simulation.
      </div>
    );
  }

  return (
    <div>
      {/* Note explaining SINR-at-handover */}
      <div style={{
        fontSize: 9, color: '#6e7681', lineHeight: 1.5,
        padding: '5px 8px', marginBottom: 8,
        background: 'rgba(88,166,255,0.06)',
        border: '1px solid rgba(88,166,255,0.15)',
        borderRadius: 5,
      }}>
        <strong style={{ color: '#58a6ff' }}>Note:</strong> Handover (A3) triggers on RSRP, not SINR.
        A UE can have decent SINR from its serving cell and still hand over because the target gNB
        offers stronger RSRP (by &gt; hysteresis margin). The 🔴 dot shows the serving-cell SINR
        <em> at the moment</em> the handover executed.
      </div>

      {hoUeIds.map((uid, i) => (
        <SingleUeHandoverChart
          key={uid}
          ueId={uid}
          color={LINE_COLORS[i % LINE_COLORS.length]}
          metrics={metrics}
          handovers={handovers}
        />
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Throughput Log
// ─────────────────────────────────────────────
function ThroughputLog({state}) {
  const metrics=state?.metrics||[];
  const gnbs=state?.gnbs||{};
  const ues=state?.ues||{};

  function downloadCSV() {
    const allUeIds = [];
    metrics.forEach(m => {
      if (m.ue_throughputs) {
        Object.keys(m.ue_throughputs).forEach(uid => {
          if (!allUeIds.includes(uid)) allUeIds.push(uid);
        });
      }
    });
    allUeIds.sort((a,b)=>{
      const na=parseInt(a.replace(/\D/g,''))||0, nb=parseInt(b.replace(/\D/g,''))||0;
      return na-nb;
    });

    const ueToGnb = {};
    Object.values(ues).forEach(u=>{ if(u.serving_gnb) ueToGnb[u.id]=u.serving_gnb; });

    const gnbIds = Object.keys(gnbs).length ? Object.keys(gnbs) : ['unknown'];

    const header = ['time_stamp', 'gnb_id', ...allUeIds.map(uid=>`${uid} TP`), 'Total_Throughput'];
    const rows = [header];

    metrics.forEach(m => {
      const t = (m.time||0).toFixed(2);
      const tpMap = m.ue_throughputs || {};
      const gnbMap = {};
      allUeIds.forEach(uid => {
        const gnbId = ueToGnb[uid] || 'unknown';
        if (!gnbMap[gnbId]) gnbMap[gnbId] = {};
        gnbMap[gnbId][uid] = tpMap[uid] ?? 0;
      });
      const gnbsToEmit = Object.keys(gnbMap).length ? Object.keys(gnbMap) : gnbIds;
      gnbsToEmit.forEach(gnbId => {
        const ueMap = gnbMap[gnbId] || {};
        const ueCols = allUeIds.map(uid => {
          const belongsHere = ueToGnb[uid] === gnbId || (!ueToGnb[uid] && gnbId === 'unknown');
          return belongsHere ? (ueMap[uid] ?? tpMap[uid] ?? 0).toFixed(2) : '';
        });
        const gnbTotal = allUeIds.reduce((sum, uid) => {
          const belongsHere = ueToGnb[uid] === gnbId || (!ueToGnb[uid] && gnbId === 'unknown');
          return sum + (belongsHere ? (ueMap[uid] ?? tpMap[uid] ?? 0) : 0);
        }, 0);
        rows.push([t, gnbId, ...ueCols, gnbTotal.toFixed(2)]);
      });
    });

    const csv = rows.map(r => r.join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'}));
    a.download = 'throughput_log.csv';
    a.click();
  }

  const entries=metrics.slice(-50);
  return (
    <div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:6}}>
        <span style={{fontSize:10,color:'#6e7681'}}>{entries.length} entries</span>
        <button onClick={downloadCSV} style={{fontSize:9,padding:'2px 8px',borderRadius:4,cursor:'pointer',background:'#238636',border:'none',color:'#fff',fontWeight:600}}>↓ CSV</button>
      </div>
      {entries.length===0?(
        <div style={{fontSize:10,color:'#6e7681',textAlign:'center',padding:8}}>No data yet — start simulation</div>
      ):(
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse',fontSize:9}}>
            <thead><tr style={{background:'var(--bg-primary)'}}>
              {['Time(s)','Instant(Mbps)','Cumul.(Mb)'].map(h=>(
                <th key={h} style={{padding:'2px 6px',textAlign:'left',color:'#6e7681',borderBottom:'1px solid #30363d'}}>{h}</th>
              ))}
            </tr></thead>
            <tbody>
              {entries.slice().reverse().map((m,i)=>(
                <tr key={i} style={{borderBottom:'1px solid #21262d'}}>
                  <td style={{padding:'2px 6px',color:'#6e7681'}}>{(m.time||0).toFixed(1)}</td>
                  <td style={{padding:'2px 6px',color:'#3fb950',fontWeight:600}}>{(m.total_throughput||0).toFixed(1)}</td>
                  <td style={{padding:'2px 6px',color:'#58a6ff'}}>{(m.cumulative_mb||0).toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Handover Table
// ─────────────────────────────────────────────
function HandoverTable({handovers,showDownloadButton}) {
  if(!handovers||handovers.length===0)
    return <div style={{fontSize:10,color:'#6e7681',padding:8,textAlign:'center'}}>No handovers yet</div>;
  function downloadCSV() {
    const rows=[['Timestamp(s)','UE_ID','Serving_gNB','Target_gNB','Serving_SINR(dB)','RSRP(dBm)','Remarks']];
    handovers.forEach(h=>rows.push([(h.time||0).toFixed(2),h.ue_id||'',h.serving||h.from||'',h.target||'',(h.sinr||0).toFixed(1),(h.rsrp||0).toFixed(1),h.ping_pong?'Ping-Pong':'']));
    const csv=rows.map(r=>r.join(',')).join('\n');
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
    a.download='handover_log.csv';a.click();
  }
  const tdS={padding:'2px 4px',fontSize:9};
  return (
    <div>
      {showDownloadButton&&(
        <button onClick={downloadCSV} style={{fontSize:10,padding:'4px 10px',borderRadius:4,cursor:'pointer',background:'#238636',border:'none',color:'#fff',fontWeight:600,width:'100%',marginBottom:6}}>⬇ Download Handover CSV</button>
      )}
      <div style={{maxHeight:300,overflowY:'auto'}}>
        <table style={{width:'100%',borderCollapse:'collapse'}}>
          <thead><tr style={{background:'var(--bg-primary)',position:'sticky',top:0}}>
            {['Time','UE','From','To','SINR','RSRP','Note'].map(h=>(
              <th key={h} style={{...tdS,textAlign:'left',color:'#6e7681',fontWeight:600,borderBottom:'1px solid #30363d'}}>{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {[...handovers].reverse().slice(0,500).map((ho,i)=>{
              const ueId=ho.ue_id||ho.ue||'?',fromGnb=ho.serving||ho.from||'?',isPP=ho.ping_pong;
              return (
                <tr key={i} style={{borderBottom:'1px solid #21262d',background:i%2===0?'#161b22':'#1c2128'}}>
                  <td style={tdS}>{ho.time?.toFixed(1)}</td>
                  <td style={{...tdS,color:'#3fb950',fontWeight:700}}>{ueId}</td>
                  <td style={{...tdS,color:'#58a6ff'}}>{fromGnb}</td>
                  <td style={{...tdS,color:'#d29922'}}>{ho.target}</td>
                  <td style={{...tdS,color:ho.sinr>10?'#3fb950':ho.sinr>0?'#d29922':'#f85149'}}>{ho.sinr?.toFixed(1)}</td>
                  <td style={{...tdS,color:'#8b949e'}}>{ho.rsrp?.toFixed(1)}</td>
                  <td style={{...tdS,color:isPP?'#f85149':'#6e7681'}}>{isPP?'⚠ Ping-Pong':'A3 HO'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
  const numUesFromState=Object.keys(ues).length;
  const latestTotal=totalFromUes>0?totalFromUes:(globalStats.total_throughput??0);
  const tpCanvasRef=useRef(null),avgCanvasRef=useRef(null);
  useEffect(()=>{
    const drawSpark=(canvas,data,color)=>{
      if(!canvas) return;
      const ctx=canvas.getContext('2d');const W=canvas.width,H=canvas.height;
      ctx.clearRect(0,0,W,H);if(!data||data.length===0) return;
      const maxV=Math.max(...data,1),minV=Math.min(...data,0),len=data.length;
      ctx.lineWidth=2;ctx.strokeStyle=color;ctx.beginPath();
      for(let i=0;i<len;i++){const x=(i/(len-1||1))*(W-4)+2,v=data[i],y=H-2-((v-minV)/(maxV-minV||1))*(H-4);i===0?ctx.moveTo(x,y):ctx.lineTo(x,y);}
      ctx.stroke();
    };
    const tpHistory=metrics.map(m=>m.total_throughput||0);
    const avgHistory=metrics.map(m=>{const n=(m.num_ues??state?.global?.num_ues??0);return n>0?((m.total_throughput||0)/n):0;});
    drawSpark(tpCanvasRef.current,tpHistory,'#3fb950');
    drawSpark(avgCanvasRef.current,avgHistory,'#58a6ff');
  },[state?.metrics,state?.global]);
  const plBadge=channelCfg?.pathloss_model==='LogDistance'?`LogDist η=${(channelCfg?.log_dist_n??3.5).toFixed(1)}`:`3GPP·${scenario}`;
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
function RightPanel({state,selectedUe,setSelectedUe,channelCfg}) {
  const [activeTab,  setActiveTab]  = useState('metrics');
  const [expandedUe, setExpandedUe] = useState(null);
  const ues=state?.ues||{};
  const metrics=state?.metrics||[];
  const globalStats=state?.global||{};
  const handovers=state?.handover_events||[];
  const totalFromUes=Object.values(ues).reduce((acc,u)=>acc+(Number(u.throughput)||0),0);
  const numUesFromState=Object.keys(ues).length;
  const latestTotal=totalFromUes>0?totalFromUes:(globalStats.total_throughput??0);
  const latestAvgPerUe=numUesFromState>0?(latestTotal/numUesFromState):0;
  const tpHistory=metrics.map(m=>m.total_throughput);
  const sinrHistory=metrics.map(m=>m.avg_sinr);
  const selectedUeData=selectedUe?ues[selectedUe]:null;
  const TABS=[{id:'metrics',icon:'📊',label:'Metrics'},{id:'ues',icon:'📱',label:'UEs'},{id:'charts',icon:'📈',label:'Charts'},{id:'handovers',icon:'🔄',label:'H/O'},{id:'logs',icon:'📋',label:'Logs'}];

  return (
    <div className="right-panel">
      <div style={{display:'flex',borderBottom:'1px solid #30363d',flexShrink:0}}>
        {TABS.map(t=>(
          <div key={t.id} onClick={()=>setActiveTab(t.id)}
            style={{flex:1,padding:'7px 2px',textAlign:'center',fontSize:9,fontWeight:600,cursor:'pointer',
              color:activeTab===t.id?'#58a6ff':'#6e7681',
              borderBottom:activeTab===t.id?'2px solid #58a6ff':'2px solid transparent',
              textTransform:'uppercase',letterSpacing:'0.3px',transition:'color 0.2s',whiteSpace:'nowrap'}}>
            {t.icon} {t.label}
          </div>
        ))}
      </div>
      <div className="panel-content">

        {activeTab==='metrics'&&(<>
          <AccordionSection title="Network Summary" icon="🌐" defaultOpen={true}>
            <div className="stat-grid">
              <div className="stat-card"><div className="stat-card-value" style={{color:'#3fb950'}}>{globalStats.total_throughput?.toFixed(0)||0}<span style={{fontSize:10}}> Mbps</span></div><div className="stat-card-label">Instant TP</div></div>
              <div className="stat-card"><div className="stat-card-value" style={{color:'#58a6ff',fontSize:14}}>{latestAvgPerUe.toFixed(1)}<span style={{fontSize:10}}> Mbps</span></div><div className="stat-card-label">Avg TP/UE</div></div>
              <div className="stat-card" style={{gridColumn:'1/-1'}}><div className="stat-card-value" style={{color:'#39d353',fontSize:13}}>{globalStats.cumulative_mb?.toFixed(1)||0}<span style={{fontSize:10}}> Mb</span><span style={{fontSize:10,color:'#6e7681',marginLeft:8}}>avg {globalStats.avg_throughput_overall?.toFixed(1)||0} Mbps</span></div><div className="stat-card-label">Cumulative TP (session)</div></div>
            </div>
          </AccordionSection>
          <AccordionSection title="Radio Quality" icon="📡" defaultOpen={true}>
            <div className="stat-grid">
              <div className="stat-card"><div className={`stat-card-value ${globalStats.avg_sinr>10?'good':globalStats.avg_sinr>0?'warn':'bad'}`}>{globalStats.avg_sinr?.toFixed(1)||0}<span style={{fontSize:10}}> dB</span></div><div className="stat-card-label">Avg SINR</div></div>
              <div className="stat-card"><div className="stat-card-value" style={{color:globalStats.packet_loss<5?'#3fb950':globalStats.packet_loss<20?'#d29922':'#f85149'}}>{globalStats.packet_loss||0}<span style={{fontSize:10}}>%</span></div><div className="stat-card-label">Pkt Loss</div></div>
            </div>
          </AccordionSection>
          <AccordionSection title="Session" icon="⏱" defaultOpen={false}>
            <div className="stat-grid">
              <div className="stat-card"><div className="stat-card-value" style={{color:'#bc8cff'}}>{globalStats.total_handovers||0}</div><div className="stat-card-label">Handovers</div></div>
              <div className="stat-card"><div className="stat-card-value" style={{color:'#8b949e'}}>{state?.step||0}</div><div className="stat-card-label">Step</div></div>
              <div className="stat-card" style={{gridColumn:'1/-1'}}><div className="stat-card-value" style={{color:'#6e7681',fontSize:14}}>{(state?.sim_time||0).toFixed(1)} s</div><div className="stat-card-label">Sim Time</div></div>
            </div>
          </AccordionSection>
          {selectedUeData&&(
            <AccordionSection title={`${selectedUe} Detail`} icon="📱" defaultOpen={true}>
              <div className="stat-grid">
                {[['RSRP',`${selectedUeData.rsrp?.toFixed(0)} dBm`,'#d29922'],['SINR',`${selectedUeData.sinr?.toFixed(1)} dB`,sinrColor(selectedUeData.sinr)],
                  ['TP',`${selectedUeData.throughput?.toFixed(1)} Mbps`,'#3fb950'],['Mod',selectedUeData.modulation,'#bc8cff'],
                  ['Velocity',`${selectedUeData.velocity?.toFixed(1)} m/s`,'#8b949e'],['Handovers',selectedUeData.handover_count,'#d29922'],['Ping-Pong',selectedUeData.ping_pong_count,'#f85149']].map(([l,v,c])=>(
                  <div key={l} className="stat-card"><div className="stat-card-value" style={{color:c,fontSize:13}}>{v}</div><div className="stat-card-label">{l}</div></div>
                ))}
              </div>
            </AccordionSection>
          )}
          <AccordionSection title="Throughput Log" icon="📊" defaultOpen={false}><ThroughputLog state={state}/></AccordionSection>
        </>)}

        {activeTab==='ues'&&(<>
          {Object.values(ues).length===0&&<div className="loading">No UEs deployed yet</div>}
          {Object.values(ues).map(ue=>{
            const isExpanded=expandedUe===ue.id;
            const mobLabel=ue.mobility_model==='none'?'Static':ue.mobility_model==='random_walk'?'RW':ue.mobility_model==='constant_velocity'?'CV':ue.mobility_model==='path_based'?'Path':ue.mobility_model==='pedestrian'?'Ped':ue.mobility_model==='file_based'?'File':'RWP';
            return (
              <div key={ue.id} className={`ue-list-item ${selectedUe===ue.id?'selected':''}`}>
                <div className="ue-list-header">
                  <span className="ue-id">{ue.id}</span>
                  <span className="ue-serving">{ue.serving_gnb||'Disconnected'}</span>
                  <button onClick={()=>setExpandedUe(isExpanded?null:ue.id)}
                    style={{marginLeft:'auto',fontSize:9,padding:'1px 7px',borderRadius:10,cursor:'pointer',
                      background:isExpanded?'rgba(88,166,255,0.15)':'transparent',
                      border:`1px solid ${isExpanded?'#58a6ff':'#30363d'}`,
                      color:isExpanded?'#58a6ff':'#6e7681'}}>
                    {isExpanded?'▲ config':'▼ config'}
                  </button>
                </div>
                <div className="ue-metrics-grid">
                  <div className="ue-metric"><span className="ue-metric-label">RSRP</span><span className="ue-metric-value" style={{color:rsrpColor(ue.rsrp)}}>{ue.rsrp?.toFixed(0)} dBm</span></div>
                  <div className="ue-metric"><span className="ue-metric-label">SINR</span><span className="ue-metric-value" style={{color:sinrColor(ue.sinr)}}>{ue.sinr?.toFixed(1)} dB</span></div>
                  <div className="ue-metric"><span className="ue-metric-label">Throughput</span><span className="ue-metric-value" style={{color:'#3fb950'}}>{ue.throughput?.toFixed(0)} Mbps</span></div>
                  <div className="ue-metric"><span className="ue-metric-label">Modulation</span><span className="ue-metric-value" style={{color:'#bc8cff'}}>{ue.modulation}</span></div>
                  <div className="ue-metric"><span className="ue-metric-label">Handovers</span><span className="ue-metric-value" style={{color:'#d29922'}}>{ue.handover_count}</span></div>
                  <div className="ue-metric">
                    <span className="ue-metric-label">Mobility</span>
                    <span className="ue-metric-value" style={{color:'#8b949e',fontSize:9}}>
                      {mobLabel} · {(ue.velocity||0).toFixed(1)} m/s
                    </span>
                  </div>
                </div>
                {isExpanded&&<UeMobilityEditor ue={ue}/>}
              </div>
            );
          })}
        </>)}

        {activeTab==='charts'&&(<>
          <AccordionSection title="Total Throughput vs Time" icon="📈" defaultOpen={true}>
            <LineChartWithDownload title="Total Throughput vs Time" filename="total_throughput_vs_time.png" data={tpHistory} label="Total Throughput" color="#3fb950" unit="Mbps" xLabel="Time (steps × 100ms)" yLabel="Throughput (Mbps)"/>
          </AccordionSection>
          <AccordionSection title="Avg SINR vs Time" icon="📡" defaultOpen={true}>
            <LineChartWithDownload title="Avg SINR vs Time" filename="avg_sinr_vs_time.png" data={sinrHistory} label="Avg SINR" color="#58a6ff" unit="dB" xLabel="Time (steps × 100ms)" yLabel="SINR (dB)"/>
          </AccordionSection>

          {/* ── NEW: SINR vs Time for handover UEs ── */}
          <AccordionSection title="SINR vs Time — Handover UEs" icon="🔴" defaultOpen={true}
            badge={[...new Set((state?.handover_events||[]).map(h=>h.ue_id))].length || null}>
            <HandoverSINRChart state={state}/>
          </AccordionSection>

          <AccordionSection title="Pathloss vs Distance" icon="📉" defaultOpen={false}>
            <PathlossChart channelCfg={channelCfg}/>
          </AccordionSection>

          {/* Per-UE detail charts with dropdown selector */}
          <AccordionSection title="Per-UE Charts" icon="📱" defaultOpen={true}>
            {Object.keys(ues).length===0
              ? <div style={{fontSize:10,color:'#6e7681',textAlign:'center',padding:8}}>No UEs deployed</div>
              : (<>
                  <div style={{marginBottom:8}}>
                    <label style={{fontSize:10,color:'var(--text-secondary)',display:'block',marginBottom:4}}>Select UE</label>
                    <select className="form-control"
                      value={selectedUe||''}
                      onChange={e=>setSelectedUe(e.target.value||null)}>
                      <option value="">— pick a UE —</option>
                      {Object.keys(ues).sort((a,b)=>{
                        const na=parseInt(a.replace(/\D/g,''))||0,nb=parseInt(b.replace(/\D/g,''))||0;
                        return na-nb;
                      }).map(uid=>(
                        <option key={uid} value={uid}>
                          {uid} · {ues[uid].serving_gnb||'disconnected'} · {ues[uid].sinr?.toFixed(1)} dB
                        </option>
                      ))}
                    </select>
                  </div>
                  {selectedUe&&ues[selectedUe] ? (<>
                    <div style={{fontSize:10,fontWeight:600,color:'#3fb950',marginBottom:6}}>
                      RSRP: {ues[selectedUe].rsrp?.toFixed(1)} dBm &nbsp;|&nbsp;
                      SINR: {ues[selectedUe].sinr?.toFixed(1)} dB &nbsp;|&nbsp;
                      TP: {ues[selectedUe].throughput?.toFixed(1)} Mbps
                    </div>
                    <div style={{marginBottom:8}}>
                      <div style={{fontSize:10,color:'#d29922',marginBottom:4,fontWeight:600}}>RSRP (dBm)</div>
                      <LineChart data={ues[selectedUe].rsrp_history||[]} label="RSRP" color="#d29922" unit="dBm" height={100}/>
                    </div>
                    <div style={{marginBottom:8}}>
                      <div style={{fontSize:10,color:'#58a6ff',marginBottom:4,fontWeight:600}}>SINR (dB)</div>
                      <LineChart data={ues[selectedUe].sinr_history||[]} label="SINR" color="#58a6ff" unit="dB" height={100}/>
                    </div>
                    <div>
                      <div style={{fontSize:10,color:'#3fb950',marginBottom:4,fontWeight:600}}>Throughput (Mbps)</div>
                      <LineChart data={ues[selectedUe].throughput_history||[]} label="Throughput" color="#3fb950" unit="Mbps" height={100}/>
                    </div>
                  </>) : (
                    <div style={{fontSize:10,color:'#6e7681',textAlign:'center',padding:8}}>
                      Select a UE above or click one on the canvas
                    </div>
                  )}
                </>)
            }
          </AccordionSection>
        </>)}

        {activeTab==='handovers'&&(<>
          <AccordionSection title="Handover Events" icon="🔄" defaultOpen={true} badge={globalStats.total_handovers||0}>
            <HandoverTable handovers={handovers}/>
          </AccordionSection>
        </>)}

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
//  Accordion
// ─────────────────────────────────────────────
function AccordionSection({title,icon,children,defaultOpen=true,badge}) {
  const [open,setOpen]=useState(defaultOpen);
  return (
    <div style={{marginBottom:4,borderRadius:6,overflow:'hidden',border:'1px solid var(--border)'}}>
      <div onClick={()=>setOpen(o=>!o)} style={{display:'flex',alignItems:'center',gap:6,padding:'6px 10px',background:'var(--bg-card)',cursor:'pointer',userSelect:'none'}}>
        <span style={{fontSize:12}}>{icon}</span>
        <span style={{flex:1,fontSize:11,fontWeight:600,color:'var(--text-secondary)'}}>{title}</span>
        {badge!=null&&<span style={{fontSize:9,padding:'1px 6px',borderRadius:10,background:'var(--bg-secondary)',color:'var(--text-muted)',fontWeight:600}}>{badge}</span>}
        <span style={{fontSize:10,color:'var(--text-muted)',transition:'transform 0.2s',transform:open?'rotate(0deg)':'rotate(-90deg)'}}>▼</span>
      </div>
      {open&&<div style={{padding:'8px 10px',background:'var(--bg-secondary)'}}>{children}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Network Canvas
// ─────────────────────────────────────────────
function NetworkCanvas({ state, onPlaceGnb, onPlaceUe, placeMode, selectedUe, setSelectedUe,
                         onCursorMove, showHeatmap, showTraces }) {
  const canvasRef  = useRef(null);
  const [tooltip,   setTooltip]   = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const dragRef    = useRef(null);

  const gnbs = state?.gnbs || {};
  const ues  = state?.ues  || {};

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0,0,W,H);
    drawGrid(ctx,W,H);

    if (showHeatmap && Object.keys(gnbs).length > 0) drawHeatmap(ctx, W, H, gnbs);

    const gnbList = Object.values(gnbs);
    for (let i=0;i<gnbList.length;i++)
      for (let j=i+1;j<gnbList.length;j++)
        drawBackhaulLink(ctx,gnbList[i],gnbList[j]);

    Object.values(ues).forEach(ue => {
      if (ue.serving_gnb && gnbs[ue.serving_gnb])
        drawWirelessLink(ctx,ue,gnbs[ue.serving_gnb],ue.sinr);
    });

    gnbList.forEach(gnb => { drawGnB(ctx,gnb,hoveredId===gnb.id); drawSectors(ctx,gnb); });

    Object.values(ues).forEach(ue => {
      if (showTraces) drawMobilityTrace(ctx, ue);
      else drawUeTrail(ctx, ue);
      drawUE(ctx, ue, selectedUe===ue.id, hoveredId===ue.id);
    });
  }, [gnbs, ues, hoveredId, selectedUe, showHeatmap, showTraces]);

  function drawGrid(ctx,W,H) {
    ctx.strokeStyle='rgba(48,54,61,0.4)'; ctx.lineWidth=1;
    for (let x=0;x<=W;x+=40){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}
    for (let y=0;y<=H;y+=40){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}
  }
  function drawBackhaulLink(ctx,g1,g2) {
    ctx.save();ctx.strokeStyle='rgba(88,166,255,0.2)';ctx.lineWidth=1.5;ctx.setLineDash([6,6]);
    ctx.beginPath();ctx.moveTo(g1.x,g1.y);ctx.lineTo(g2.x,g2.y);ctx.stroke();ctx.setLineDash([]);ctx.restore();
  }
  function drawWirelessLink(ctx,ue,gnb,sinr) {
    const color=sinrColor(sinr);
    const r=parseInt(color.slice(1,3),16),g=parseInt(color.slice(3,5),16),b=parseInt(color.slice(5,7),16);
    ctx.save();ctx.strokeStyle=`rgba(${r},${g},${b},0.5)`;ctx.lineWidth=1.5;ctx.setLineDash([4,8]);
    const cpx=(ue.x+gnb.x)/2+(ue.y-gnb.y)*0.15,cpy=(ue.y+gnb.y)/2-(ue.x-gnb.x)*0.15;
    ctx.beginPath();ctx.moveTo(ue.x,ue.y);ctx.quadraticCurveTo(cpx,cpy,gnb.x,gnb.y);ctx.stroke();ctx.setLineDash([]);ctx.restore();
  }
  function drawSectors(ctx,gnb) {
    if (gnb.num_sectors<=1) return;
    ctx.save();ctx.strokeStyle='rgba(88,166,255,0.2)';ctx.lineWidth=1;
    const radius=100;
    for (let i=0;i<gnb.num_sectors;i++) {
      const azimuth=(gnb.sectors?.[i]?.azimuth||0)*Math.PI/180;
      ctx.beginPath();ctx.moveTo(gnb.x,gnb.y);
      ctx.arc(gnb.x,gnb.y,radius,azimuth-Math.PI/gnb.num_sectors,azimuth+Math.PI/gnb.num_sectors);
      ctx.lineTo(gnb.x,gnb.y);ctx.stroke();
    }
    ctx.restore();
  }
  function drawGnB(ctx, gnb, hovered) {
  const x = gnb.x, y = gnb.y;
  const isAnchor = !!gnb.is_anchor;
  const size     = hovered ? (isAnchor ? 26 : 22) : (isAnchor ? 22 : 18);

  ctx.save();

  if (isAnchor) {
    // ── AnchorGNB: purple star-burst ─────────────────────────────
    const outerR = size;
    const innerR = size * 0.45;
    const points = 8;
    const anchorColor = '#bc8cff';

    if (hovered) { ctx.shadowColor = '#bc8cff'; ctx.shadowBlur = 20; }

    // Pulsing glow ring
    ctx.beginPath();
    ctx.arc(x, y, outerR + 6, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(188,140,255,0.25)';
    ctx.lineWidth   = 4;
    ctx.stroke();

    // Star-burst body
    ctx.beginPath();
    for (let i = 0; i < points * 2; i++) {
      const angle  = (i * Math.PI) / points - Math.PI / 2;
      const radius = i % 2 === 0 ? outerR : innerR;
      const px = x + radius * Math.cos(angle);
      const py = y + radius * Math.sin(angle);
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fillStyle   = 'rgba(188,140,255,0.20)';
    ctx.strokeStyle = anchorColor;
    ctx.lineWidth   = 2.5;
    ctx.fill();
    ctx.stroke();

    // Centre circle
    ctx.beginPath();
    ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.fillStyle   = 'rgba(188,140,255,0.35)';
    ctx.strokeStyle = anchorColor;
    ctx.lineWidth   = 2;
    ctx.fill();
    ctx.stroke();

    // ⚓ emoji label inside
    ctx.shadowBlur = 0;
    ctx.fillStyle  = '#e6edf3';
    ctx.font       = 'bold 10px system-ui';
    ctx.textAlign  = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('⚓', x, y);

    // ID label below
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle    = anchorColor;
    ctx.font         = 'bold 10px system-ui';
    ctx.fillText(gnb.id, x, y + outerR + 14);

    // Connected-UE badge
    const cc = gnb.connected_ues || 0;
    if (cc > 0) {
      ctx.beginPath();
      ctx.arc(x + outerR * 0.7, y - outerR * 0.7, 9, 0, Math.PI * 2);
      ctx.fillStyle = '#bc8cff';
      ctx.fill();
      ctx.fillStyle = '#0d1117';
      ctx.font      = 'bold 9px system-ui';
      ctx.textBaseline = 'middle';
      ctx.textAlign    = 'center';
      ctx.fillText(cc, x + outerR * 0.7, y - outerR * 0.7);
    }

  } else {
    // ── Normal gNB: original tower icon ──────────────────────────
    if (hovered) { ctx.shadowColor = '#58a6ff'; ctx.shadowBlur = 15; }

    ctx.strokeStyle = hovered ? '#74b9ff' : '#58a6ff';
    ctx.lineWidth   = 2;
    ctx.beginPath();
    ctx.moveTo(x, y - size);
    ctx.lineTo(x, y + size * 0.3);
    ctx.moveTo(x - size * 0.6, y - size * 0.4);
    ctx.lineTo(x + size * 0.6, y - size * 0.4);
    ctx.moveTo(x - size * 0.4, y - size * 0.1);
    ctx.lineTo(x + size * 0.4, y - size * 0.1);
    ctx.moveTo(x - size * 0.4, y + size * 0.3);
    ctx.lineTo(x + size * 0.4, y + size * 0.3);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(x, y, 10, 0, Math.PI * 2);
    ctx.fillStyle   = hovered ? 'rgba(88,166,255,0.3)' : 'rgba(88,166,255,0.15)';
    ctx.fill();
    ctx.strokeStyle = '#58a6ff';
    ctx.lineWidth   = 1.5;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    ctx.fillStyle    = '#e6edf3';
    ctx.font         = 'bold 10px system-ui';
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(gnb.id, x, y + size + 14);

    const cc = gnb.connected_ues || 0;
    if (cc > 0) {
      ctx.beginPath();
      ctx.arc(x + 12, y - 12, 9, 0, Math.PI * 2);
      ctx.fillStyle = '#3fb950';
      ctx.fill();
      ctx.fillStyle    = '#0d1117';
      ctx.font         = 'bold 9px system-ui';
      ctx.textBaseline = 'middle';
      ctx.fillText(cc, x + 12, y - 12);
    }
  }

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
  function getCanvasXY(e) {
    const rect=canvasRef.current.getBoundingClientRect();
    return {x:(e.clientX-rect.left)*(canvasRef.current.width/rect.width),
            y:(e.clientY-rect.top)*(canvasRef.current.height/rect.height)};
  }
  function hitTest(x,y) {
    for(const ue of Object.values(ues)) if(Math.hypot(ue.x-x,ue.y-y)<15) return {id:ue.id,type:'ue',obj:ue};
    for(const gnb of Object.values(gnbs)) if(Math.hypot(gnb.x-x,gnb.y-y)<20) return {id:gnb.id,type:'gnb',obj:gnb};
    return null;
  }
  const handleMouseDown=useCallback((e)=>{
    if(e.button!==0) return;
    const {x,y}=getCanvasXY(e);
    if(placeMode==='gnb'){onPlaceGnb(x,y);return;}
    if(placeMode==='ue'){onPlaceUe(x,y);return;}
    if(onCursorMove) onCursorMove({x:Math.round(x),y:Math.round(y)});
    const hit=hitTest(x,y);
    if(hit){
      dragRef.current={id:hit.id,type:hit.type,offsetX:x-hit.obj.x,offsetY:y-hit.obj.y};
      setSelectedUe(hit.type==='ue'?hit.id:null);
      setTooltip({type:hit.type,data:hit.obj,x:e.clientX,y:e.clientY});
    } else { setTooltip(null); }
  },[ues,gnbs,placeMode]);
  const handleMouseMove=useCallback((e)=>{
    const {x,y}=getCanvasXY(e);
    if(onCursorMove) onCursorMove({x:Math.round(x),y:Math.round(y)});
    if(dragRef.current){
      const {id,type,offsetX,offsetY}=dragRef.current;
      fetch(`/api/move_${type}`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({[`${type}_id`]:id,x:x-offsetX,y:y-offsetY})});
      return;
    }
    const hit=hitTest(x,y);
    setHoveredId(hit?hit.id:null);
    if(hit) setTooltip({type:hit.type,data:hit.obj,x:e.clientX,y:e.clientY});
    else setTooltip(null);
  },[ues,gnbs]);
  const handleMouseUp=()=>{dragRef.current=null;};
  const handleContextMenu=useCallback((e)=>{
    e.preventDefault();
    const {x,y}=getCanvasXY(e);
    const hit=hitTest(x,y);
    if(!hit) return;
    if(window.confirm(`Remove ${hit.id}?`))
      fetch(`/api/remove_${hit.type}`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({[`${hit.type}_id`]:hit.id})});
  },[ues,gnbs]);

  return (
    <div className="canvas-container" style={{position:'relative'}}>
      <canvas ref={canvasRef} className="network-canvas" width={800} height={560}
        onMouseDown={handleMouseDown} onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp} onMouseLeave={()=>{dragRef.current=null;setHoveredId(null);setTooltip(null);}}
        onContextMenu={handleContextMenu}
        style={{cursor:placeMode?'crosshair':'grab',width:'100%',height:'100%'}}
      />
      <div className="legend" style={{position:'absolute',bottom:8,left:8,background:'rgba(13,17,23,0.85)',borderRadius:6,padding:'5px 10px'}}>
        <div className="legend-item"><div className="legend-dot" style={{background:'#58a6ff'}}></div>gNB</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#3fb950'}}></div>UE (Excellent &gt;20dB)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#58a6ff',border:'1px solid #fff'}}></div>UE (Good 10-20dB)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#d29922'}}></div>UE (Fair 0-10dB)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#f85149'}}></div>UE (Poor &lt;0dB)</div>
        <div className="legend-item">
        <div style={{width:12,height:12,background:'#bc8cff',clipPath:'polygon(50% 0%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%)',
       flexShrink:0}}></div>
     AnchorGNB (⚓)
   </div>
        {showHeatmap&&<div className="legend-item" style={{marginTop:3,paddingTop:3,borderTop:'1px solid #30363d',fontSize:9,color:'#8b949e'}}>🌡 Red=strong · Blue=weak</div>}
        {showTraces&&<div className="legend-item" style={{marginTop:3,paddingTop:3,borderTop:'1px solid #30363d'}}><div style={{width:16,height:2,background:'rgba(255,255,255,0.8)',marginRight:4,flexShrink:0}}></div><span style={{fontSize:9,color:'#8b949e'}}>Mobility trace</span></div>}
      </div>
      {tooltip&&(
        <div className="canvas-tooltip" style={{left:tooltip.x-canvasRef.current?.getBoundingClientRect().left+12,top:tooltip.y-canvasRef.current?.getBoundingClientRect().top-10,position:'absolute',zIndex:50}}>
          {tooltip.type==='ue'&&(<>
            <div className="tooltip-title">📱 {tooltip.data.id}</div>
            <div className="tooltip-row"><span className="tooltip-label">Serving:</span><span className="tooltip-value">{tooltip.data.serving_gnb||'None'}</span></div>
            <div className="tooltip-row"><span className="tooltip-label">RSRP:</span><span className="tooltip-value" style={{color:rsrpColor(tooltip.data.rsrp)}}>{tooltip.data.rsrp?.toFixed(1)} dBm</span></div>
            <div className="tooltip-row"><span className="tooltip-label">SINR:</span><span className="tooltip-value" style={{color:sinrColor(tooltip.data.sinr)}}>{tooltip.data.sinr?.toFixed(1)} dB</span></div>
            <div className="tooltip-row"><span className="tooltip-label">TP:</span><span className="tooltip-value good">{tooltip.data.throughput?.toFixed(1)} Mbps</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Mod:</span><span className="tooltip-value">{tooltip.data.modulation}</span></div>
          </>)}
          {tooltip.type==='gnb'&&(<>
            <div className="tooltip-title">📡 {tooltip.data.id}</div>
            <div className="tooltip-row"><span className="tooltip-label">UEs:</span><span className="tooltip-value">{tooltip.data.connected_ues}</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Throughput:</span><span className="tooltip-value good">{tooltip.data.total_throughput?.toFixed(1)} Mbps</span></div>
            <div className="tooltip-row"><span className="tooltip-label">TX Power:</span><span className="tooltip-value">{tooltip.data.tx_power_dbm} dBm</span></div>
          </>)}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Sidebar
// ─────────────────────────────────────────────
function Sidebar({state,onAddGnb,onAddUe,onStart,onStop,onReset,placeMode,setPlaceMode,
                  scenario,setScenario,simSpeed,setSimSpeed,params,setParams,
                  simDuration,setSimDuration,channelCfg,setChannelCfg}) {
  const isRunning=state?.running||false;
  const numGnbs=Object.keys(state?.gnbs||{}).length;
  const numUes=Object.keys(state?.ues||{}).length;
  const [ueConfig,  setUeConfig]  = useState({mobility:'none',speed:3});
  const [gnbConfig, setGnbConfig] = useState({tx_power:43,sectors:3});
  const [lastScenarioConfig, setLastScenarioConfig] = useState(null);

  const applyChannelCfg=(patch)=>{
    const next={...channelCfg,...patch};
    setChannelCfg(next);
    fetch('/api/set_channel_config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)});
  };

  const handleStart=()=>{
    let durationToUse=simDuration;
    if(durationToUse==null){
      const input=window.prompt('Enter simulation duration in seconds:','15');
      if(input===null) return;
      const parsed=parseFloat(input);
      if(Number.isNaN(parsed)||parsed<=0){alert('Invalid duration.');return;}
      durationToUse=parsed;
    }
    const config={scenario,speed:simSpeed,duration:durationToUse,
      pathloss_model:channelCfg.pathloss_model,log_dist_n:channelCfg.log_dist_n,
      log_dist_shadow:channelCfg.log_dist_shadow,fading_model:channelCfg.fading_model};
    setLastScenarioConfig(config);
    fetch('/api/start_simulation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});
    onStart(durationToUse);
  };
  const handleRestart=()=>{
    if(!lastScenarioConfig){alert('No previous scenario to restart.');return;}
    const config=lastScenarioConfig;
    fetch('/api/start_simulation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});
    onStart(config.duration);
  };
  const handleStop=()=>{fetch('/api/stop_simulation',{method:'POST'});onStop();};
  const handleReset=()=>{fetch('/api/reset',{method:'POST'});onReset();};

  return (
    <div className="sidebar">
      <div className="sidebar-section">
        <div className="sidebar-section-title">Simulation</div>
        <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:8}}>
          <div className={`sim-status-dot ${isRunning?'running':''}`}></div>
          <span style={{fontSize:11,color:isRunning?'#3fb950':'#6e7681'}}>{isRunning?`Running (t=${state?.sim_time?.toFixed(1)}s)`:'Stopped'}</span>
        </div>
        {!isRunning
          ?<button className="btn btn-success" onClick={handleStart}>▶ Start Simulation</button>
          :<button className="btn btn-danger" onClick={handleStop}>⏹ Stop</button>}
        <button className="btn btn-secondary" onClick={handleReset}>↺ Reset</button>
        {!isRunning&&lastScenarioConfig
          ?<button className="btn btn-info" onClick={handleRestart} style={{marginTop:6,background:'rgba(88,166,255,0.25)',border:'1px solid #58a6ff',color:'#58a6ff'}}>🔄 Restart Scenario</button>
          :null}
        <div className="form-group" style={{marginTop:8}}>
          <label className="form-label">Simulation Speed: {simSpeed}x</label>
          <input type="range" min="0.5" max="10" step="0.5" value={simSpeed}
            onChange={e=>{const v=parseFloat(e.target.value);setSimSpeed(v);fetch('/api/set_speed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speed:v})});}}
            style={{width:'100%'}}/>
        </div>
      </div>

      <div className="form-group" style={{marginTop:8,padding:'0 12px'}}>
        <label className="form-label">Sim Duration (seconds)</label>
        <div style={{display:'flex',gap:6}}>
          {[10,20,30,60].map(s=>(
            <button key={s} onClick={()=>setSimDuration(simDuration===s?null:s)}
              style={{flex:1,padding:'4px 0',fontSize:11,borderRadius:6,
                border:`1px solid ${simDuration===s?'#58a6ff':'#30363d'}`,
                background:simDuration===s?'rgba(88,166,255,0.15)':'#1c2128',
                color:simDuration===s?'#58a6ff':'#8b949e',cursor:'pointer'}}>{s}s</button>
          ))}
        </div>
        <div style={{fontSize:10,color:'#6e7681',marginTop:6,textAlign:'center'}}>
          {simDuration==null?'No preset — Start will prompt for duration.':`Selected: ${simDuration}s`}
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-title">Propagation Model</div>
        <div className="form-group">
          <label className="form-label">Pathloss Model</label>
          <select className="form-control" value={channelCfg.pathloss_model}
            onChange={e=>applyChannelCfg({pathloss_model:e.target.value})}>
            <option value="3GPP">3GPP TR 38.901</option>
            <option value="LogDistance">Log Distance</option>
          </select>
        </div>
        {channelCfg.pathloss_model==='3GPP'&&(<>
          <label className="form-label" style={{marginTop:6}}>Outdoor Scenario</label>
          <div className="scenario-buttons">
            {['UMa','UMi','RMa'].map(s=>(
              <button key={s} className={`scenario-btn ${scenario===s?'active':''}`}
                onClick={()=>{setScenario(s);applyChannelCfg({scenario:s});}}>
                {s==='UMa'?'🌆':s==='UMi'?'🏢':'🌄'}<br/>
                {s==='UMa'?'Urban Macro':s==='UMi'?'Urban Micro':'Rural Macro'}
              </button>
            ))}
          </div>
        </>)}
        {channelCfg.pathloss_model==='LogDistance'&&(<>
          <div className="form-group" style={{marginTop:8}}>
            <label className="form-label">Path Loss Exp η: {(channelCfg.log_dist_n??3.5).toFixed(1)}</label>
            <input type="range" min="1.6" max="6.0" step="0.1" value={channelCfg.log_dist_n??3.5}
              onChange={e=>applyChannelCfg({log_dist_n:parseFloat(e.target.value)})} style={{width:'100%'}}/>
          </div>
          <div className="form-group">
            <label className="form-label">Shadow Fading</label>
            <select className="form-control" value={channelCfg.log_dist_shadow??'lognormal'}
              onChange={e=>applyChannelCfg({log_dist_shadow:e.target.value})}>
              <option value="lognormal">Log-Normal (σ=8 dB)</option>
              <option value="none">None</option>
            </select>
          </div>
        </>)}
        <div className="form-group" style={{marginTop:8}}>
          <label className="form-label">Fading Model</label>
          <select className="form-control" value={channelCfg.fading_model??'Rayleigh'}
            onChange={e=>applyChannelCfg({fading_model:e.target.value})}>
            <option value="Rayleigh">Rayleigh</option>
            <option value="none">None</option>
          </select>
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-title">Deploy gNB ({numGnbs})</div>
        <div className="form-group">
          <label className="form-label">TX Power: {gnbConfig.tx_power} dBm</label>
          <input type="range" min="20" max="46" value={gnbConfig.tx_power}
            onChange={e=>setGnbConfig(p=>({...p,tx_power:parseInt(e.target.value)}))} style={{width:'100%'}}/>
        </div>
        <div className="form-group">
          <label className="form-label">Sectors</label>
          <select className="form-control" value={gnbConfig.sectors}
            onChange={e=>setGnbConfig(p=>({...p,sectors:parseInt(e.target.value)}))}>
            <option value={1}>1 (Omni)</option>
            <option value={3}>3 (Tri-sector)</option>
          </select>
        </div>
        <button className={`btn ${placeMode==='gnb'?'btn-primary':'btn-secondary'}`}
          onClick={()=>setPlaceMode(placeMode==='gnb'?null:'gnb')}>
          📡 {placeMode==='gnb'?'🟢 Placing… (Esc to stop)':'Place gNB'}
        </button>
        <AnchorStatusPanel state={state}/>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-title">Deploy UE ({numUes})</div>
        <div className="form-group">
          <label className="form-label">Initial Mobility Model</label>
          <select className="form-control" value={ueConfig.mobility}
            onChange={e=>setUeConfig(p=>({...p,mobility:e.target.value}))}>
            <option value="none">⛔ None (stationary)</option>
            <option value="random_walk">🎲 Random Walk</option>
            <option value="random_waypoint">🗺️ Random Waypoint</option>
            <option value="constant_velocity">➡️ Constant Velocity</option>
            <option value="pedestrian">🚶 Pedestrian</option>
            <option value="file_based">📂 File Based (CSV)</option>
          </select>
        </div>
        {ueConfig.mobility!=='none'&&ueConfig.mobility!=='pedestrian'&&(
          <div className="form-group">
            <label className="form-label">Initial Speed: {ueConfig.speed} m/s</label>
            <input type="range" min="1" max="30" value={ueConfig.speed}
              onChange={e=>setUeConfig(p=>({...p,speed:parseFloat(e.target.value)}))} style={{width:'100%'}}/>
          </div>
        )}
        <div style={{fontSize:9,color:'#6e7681',marginBottom:6,lineHeight:1.4}}>
          After placing, click <strong style={{color:'#58a6ff'}}>▼ config</strong> on any UE in the UEs tab to change its mobility live.
        </div>
        <button className={`btn ${placeMode==='ue'?'btn-primary':'btn-secondary'}`}
          onClick={()=>setPlaceMode(placeMode==='ue'?null:'ue')}>
          📱 {placeMode==='ue'?'🟢 Placing… (Esc to stop)':'Place UE'}
        </button>
        <button className="btn btn-ghost" onClick={()=>{
          for(let i=0;i<3;i++) setTimeout(()=>fetch('/api/add_ue',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({x:50+Math.random()*700,y:50+Math.random()*480,mobility:ueConfig.mobility,speed:ueConfig.speed})}),i*50);
        }}>⚡ Quick Deploy 3 UEs</button>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-title">Handover Params</div>
        <div className="form-group">
          <label className="form-label">Hysteresis: {params.hysteresis} dB</label>
          <input type="range" min="0" max="10" step="0.5" value={params.hysteresis}
            onChange={e=>{const v=parseFloat(e.target.value);setParams(p=>({...p,hysteresis:v}));
              fetch('/api/set_params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hysteresis:v})});}}
            style={{width:'100%'}}/>
        </div>
        <div className="form-group">
          <label className="form-label">TTT: {params.ttt*100} ms</label>
          <input type="range" min="1" max="10" value={params.ttt}
            onChange={e=>{const v=parseInt(e.target.value);setParams(p=>({...p,ttt:v}));
              fetch('/api/set_params',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ttt_steps:v})});}}
            style={{width:'100%'}}/>
        </div>
      </div>

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
          {!(state?.event_log?.length)&&<div style={{color:'#6e7681',fontSize:10}}>No events yet</div>}
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
  const [simSpeed,    setSimSpeed]    = useState(1.0);
  const [simDuration, setSimDuration] = useState(null);
  const [cursorPos,   setCursorPos]   = useState({x:0,y:0});
  const [darkMode,    setDarkMode]    = useState(true);
  const [params,      setParams]      = useState({hysteresis:3,ttt:3});
  const [channelCfg,  setChannelCfg]  = useState({pathloss_model:'3GPP',scenario:'UMa',log_dist_n:3.5,log_dist_shadow:'lognormal',fading_model:'Rayleigh'});
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [showTraces,  setShowTraces]  = useState(false);

  const simTimerRef=useRef(null);
  const justStoppedRef=useRef(false);

  useEffect(()=>{ document.documentElement.setAttribute('data-theme',darkMode?'dark':'light'); },[]);

  useEffect(()=>{
    const es=new EventSource('/api/stream');
    es.onmessage=e=>{ 
      try{
        const newState = JSON.parse(e.data);
        // If we just stopped, ignore SSE updates that still show running
        // to give the backend time to register the stop
        if(justStoppedRef.current && newState.running) {
          return;
        }
        justStoppedRef.current = false;
        setState(newState);
      }catch{} 
    };
    es.onerror=()=>{};
    return()=>es.close();
  },[]);

  const handleStart=useCallback((duration)=>{
    if(simTimerRef.current){clearTimeout(simTimerRef.current);simTimerRef.current=null;}
    if(duration){
      // Add 200ms buffer to ensure simulation actually reaches target duration
      const timerDelay = (duration * 1000) + 200;
      simTimerRef.current=setTimeout(()=>{
        justStoppedRef.current = true;
        fetch('/api/stop_simulation',{method:'POST'});
        // Immediately update UI to show stopped (don't wait for backend)
        setState(prev => prev ? {...prev, running: false} : null);
        simTimerRef.current=null;
      }, timerDelay);
    }
  },[]);
  const handleStop=useCallback(()=>{
    if(simTimerRef.current){clearTimeout(simTimerRef.current);simTimerRef.current=null;}
    justStoppedRef.current = true;
    fetch('/api/stop_simulation',{method:'POST'});
    // Immediately update UI to reflect stopped state
    setState(prev => prev ? {...prev, running: false} : null);
  },[]);
  const handlePlaceGnb=useCallback((x,y)=>{
    fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,tx_power:43,num_sectors:3})});
  },[]);
  const handlePlaceUe=useCallback((x,y)=>{
    fetch('/api/add_ue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,mobility:'none',speed:3.0})});
  },[]);

  useEffect(()=>{
    const onKey=(e)=>{if(e.key==='Escape')setPlaceMode(null);};
    window.addEventListener('keydown',onKey);
    return()=>window.removeEventListener('keydown',onKey);
  },[]);

  function tbBtn(active,color='#58a6ff') {
    return {fontSize:10,padding:'4px 10px',borderRadius:4,cursor:'pointer',fontWeight:600,
      background:active?color+'25':'transparent',border:`1px solid ${active?color:'#30363d'}`,
      color:active?color:'#8b949e',transition:'all 0.2s'};
  }

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
        channelCfg={channelCfg} setChannelCfg={setChannelCfg}/>
      <div className="main-area">
        <div className="canvas-toolbar">
          <span className="canvas-toolbar-title">Network Topology</span>
          <div style={{flex:1}}/>
          <button style={tbBtn(showHeatmap,'#f85149')} onClick={()=>setShowHeatmap(h=>!h)}>
            {showHeatmap?'🌡 Hide Heatmap':'🌡 Heatmap'}
          </button>
          <button style={tbBtn(showTraces,'#e6edf3')} onClick={()=>setShowTraces(t=>!t)}>
            {showTraces?'〰 Hide Traces':'〰 Mob. Traces'}
          </button>
          <button className="btn btn-ghost" style={{width:'auto',fontSize:10,padding:'4px 10px'}} onClick={()=>{
            fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:200,y:200})});
            setTimeout(()=>fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:600,y:200})}),50);
            setTimeout(()=>fetch('/api/add_gnb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x:400,y:440})}),100);
          }}>⚡ Default Topology</button>
          {placeMode&&(
            <div className="placement-indicator" style={{position:'static',transform:'none',fontSize:11,padding:'4px 12px'}}>
              Click to place {placeMode==='gnb'?'📡 gNB':'📱 UE'} — or press Esc to cancel
            </div>
          )}
        </div>
        <NetworkCanvas state={state} onPlaceGnb={handlePlaceGnb} onPlaceUe={handlePlaceUe}
          placeMode={placeMode} selectedUe={selectedUe} setSelectedUe={setSelectedUe}
          onCursorMove={setCursorPos} showHeatmap={showHeatmap} showTraces={showTraces}/>
        <div style={{flexShrink:0,padding:'4px 12px',background:'var(--bg-secondary)',borderTop:'1px solid var(--border)',display:'flex',alignItems:'center',gap:16,fontSize:11}}>
          <span style={{color:'var(--text-muted)'}}>Canvas Cursor:</span>
          <span style={{color:'#58a6ff',fontFamily:'monospace'}}>X: <strong>{cursorPos.x} px</strong> ({(cursorPos.x*5).toFixed(0)} m)</span>
          <span style={{color:'#58a6ff',fontFamily:'monospace'}}>Y: <strong>{cursorPos.y} px</strong> ({(cursorPos.y*5).toFixed(0)} m)</span>
          <span style={{color:'var(--text-muted)'}}>|</span>
          <span style={{color:'#3fb950',fontFamily:'monospace'}}>gNBs: {Object.keys(state?.gnbs||{}).length} &nbsp;|&nbsp; UEs: {Object.keys(state?.ues||{}).length}</span>
          {placeMode&&<span style={{color:'#d29922'}}>📍 Placing: {placeMode.toUpperCase()}</span>}
          <div style={{marginLeft:'auto'}}>
            <button onClick={()=>setDarkMode(d=>!d)}
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
      <RightPanel state={state} selectedUe={selectedUe} setSelectedUe={setSelectedUe} channelCfg={channelCfg}/>
    </div>
  );
}

ReactDOM.render(<App/>, document.getElementById('root'));