// ============================================================
//   5G NR Network Simulator - React Frontend
// ============================================================

const { useState, useEffect, useRef, useCallback } = React;

// ── Color helpers ──
function sinrColor(sinr) {
  if (sinr > 20) return '#3fb950';
  if (sinr > 10) return '#58a6ff';
  if (sinr > 0)  return '#d29922';
  return '#f85149';
}

function rsrpColor(rsrp) {
  if (rsrp > -80) return '#3fb950';
  if (rsrp > -95) return '#58a6ff';
  if (rsrp > -110) return '#d29922';
  return '#f85149';
}

function sinrClass(sinr) {
  if (sinr > 20) return 'sig-excellent';
  if (sinr > 10) return 'sig-good';
  if (sinr > 0)  return 'sig-fair';
  return 'sig-poor';
}

// Format throughput values (assumes input in Mbps). Produces human-friendly string.
function formatThroughput(mbps) {
  if (mbps == null || isNaN(mbps)) return '0 Mbps';
  const v = Number(mbps);
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)} Gbps`;
  if (Math.abs(v) >= 1) return `${v.toFixed(1)} Mbps`;
  return `${(v * 1000).toFixed(1)} Kbps`;
}

// Utility: download a canvas with a title/header added on top
function downloadCanvasWithTitle(sourceCanvas, title, filename) {
  if (!sourceCanvas) return;
  const titleHeight = 28;
  const padding = 12;
  const outW = sourceCanvas.width;
  const outH = sourceCanvas.height + titleHeight + padding;

  const out = document.createElement('canvas');
  out.width = outW;
  out.height = outH;
  const ctx = out.getContext('2d');

  // white background for paper-friendly images
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, outW, outH);

  // Title
  ctx.fillStyle = '#0d1117';
  ctx.font = 'bold 16px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillText(title, outW / 2, 8);

  // Draw the chart image below the title
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, titleHeight + padding / 2, sourceCanvas.width, sourceCanvas.height);
    const link = document.createElement('a');
    link.download = filename || 'chart.png';
    link.href = out.toDataURL('image/png');
    link.click();
  };
  img.src = sourceCanvas.toDataURL('image/png');
}

// ─────────────────────────────────────────────
//  Network Canvas (SVG + Canvas hybrid)
// ─────────────────────────────────────────────
function NetworkCanvas({ state, onPlaceGnb, onPlaceUe, placeMode, selectedUe, setSelectedUe, onCursorMove }) {
  const canvasRef = useRef(null);
  const [tooltip, setTooltip] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const dragRef = useRef(null); // { id, type, offsetX, offsetY }

  const gnbs = state?.gnbs || {};
  const ues  = state?.ues  || {};

  // ── draw ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    drawGrid(ctx, W, H);
    const gnbList = Object.values(gnbs);
    for (let i = 0; i < gnbList.length; i++)
      for (let j = i+1; j < gnbList.length; j++)
        drawBackhaulLink(ctx, gnbList[i], gnbList[j]);
    Object.values(ues).forEach(ue => {
      if (ue.serving_gnb && gnbs[ue.serving_gnb])
        drawWirelessLink(ctx, ue, gnbs[ue.serving_gnb], ue.sinr);
    });
    gnbList.forEach(gnb => { drawGnB(ctx, gnb, hoveredId === gnb.id); drawSectors(ctx, gnb); });
    Object.values(ues).forEach(ue => { drawUeTrail(ctx, ue); drawUE(ctx, ue, selectedUe === ue.id, hoveredId === ue.id); });
  }, [gnbs, ues, hoveredId, selectedUe]);

  function getCanvasXY(e) {
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvasRef.current.width / rect.width),
      y: (e.clientY - rect.top)  * (canvasRef.current.height / rect.height)
    };
  }

  function hitTest(x, y) {
    for (const ue of Object.values(ues)) {
      if (Math.hypot(ue.x - x, ue.y - y) < 15) return { id: ue.id, type: 'ue', obj: ue };
    }
    for (const gnb of Object.values(gnbs)) {
      if (Math.hypot(gnb.x - x, gnb.y - y) < 20) return { id: gnb.id, type: 'gnb', obj: gnb };
    }
    return null;
  }

  // Mouse down — start drag or place
  const handleMouseDown = useCallback((e) => {
    if (e.button !== 0) return; // left only
    const { x, y } = getCanvasXY(e);
    if (placeMode === 'gnb') { onPlaceGnb(x, y); return; }
    if (placeMode === 'ue')  { onPlaceUe(x, y);  return; }
    // Report cursor position (pixels, scaled to meters: 1px = 5m)
    if (onCursorMove) onCursorMove({ x: Math.round(x), y: Math.round(y) });
    const hit = hitTest(x, y);
    if (hit) {
      dragRef.current = { id: hit.id, type: hit.type, offsetX: x - hit.obj.x, offsetY: y - hit.obj.y };
      setSelectedUe(hit.type === 'ue' ? hit.id : null);
    } else {
      setSelectedUe(null);
    }
  }, [placeMode, ues, gnbs, onPlaceGnb, onPlaceUe]);

  // Mouse move — drag
  const handleMouseMove = useCallback((e) => {
    const { x, y } = getCanvasXY(e);

    // Drag
    if (dragRef.current && e.buttons === 1) {
      const nx = x - dragRef.current.offsetX;
      const ny = y - dragRef.current.offsetY;
      const clamped = { x: Math.max(15, Math.min(785, nx)), y: Math.max(15, Math.min(545, ny)) };
      fetch(`/api/move_${dragRef.current.type}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [`${dragRef.current.type}_id`]: dragRef.current.id, ...clamped })
      });
      return;
    }

    // Hover
    const hit = hitTest(x, y);
    setHoveredId(hit ? hit.id : null);
    if (hit) {
      setTooltip({ type: hit.type, data: hit.obj, x: e.clientX, y: e.clientY });
    } else {
      setTooltip(null);
    }
  }, [ues, gnbs]);

  const handleMouseUp = () => { dragRef.current = null; };

  // Right-click — remove
  const handleContextMenu = useCallback((e) => {
    e.preventDefault();
    const { x, y } = getCanvasXY(e);
    const hit = hitTest(x, y);
    if (!hit) return;
    if (window.confirm(`Remove ${hit.id}?`)) {
      fetch(`/api/remove_${hit.type}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [`${hit.type}_id`]: hit.id })
      });
    }
  }, [ues, gnbs]);

  // ── draw helpers (same as before) ──
  function drawGrid(ctx, W, H) {
    ctx.strokeStyle = 'rgba(48,54,61,0.4)'; ctx.lineWidth = 1;
    for (let x = 0; x <= W; x += 40) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke(); }
    for (let y = 0; y <= H; y += 40) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); }
  }
  function drawBackhaulLink(ctx, g1, g2) {
    ctx.save(); ctx.strokeStyle='rgba(88,166,255,0.2)'; ctx.lineWidth=1.5; ctx.setLineDash([6,6]);
    ctx.beginPath(); ctx.moveTo(g1.x,g1.y); ctx.lineTo(g2.x,g2.y); ctx.stroke(); ctx.setLineDash([]); ctx.restore();
  }
  function drawWirelessLink(ctx, ue, gnb, sinr) {
    const color = sinrColor(sinr);
    const r=parseInt(color.slice(1,3),16), g=parseInt(color.slice(3,5),16), b=parseInt(color.slice(5,7),16);
    ctx.save(); ctx.strokeStyle=`rgba(${r},${g},${b},0.5)`; ctx.lineWidth=1.5; ctx.setLineDash([4,8]);
    const cpx=(ue.x+gnb.x)/2+(ue.y-gnb.y)*0.15, cpy=(ue.y+gnb.y)/2-(ue.x-gnb.x)*0.15;
    ctx.beginPath(); ctx.moveTo(ue.x,ue.y); ctx.quadraticCurveTo(cpx,cpy,gnb.x,gnb.y); ctx.stroke(); ctx.setLineDash([]); ctx.restore();
  }
  function drawSectors(ctx, gnb) {
    if (!gnb.sectors) return;
    gnb.sectors.forEach(sector => {
      ctx.save();
      const az=(sector.azimuth*Math.PI/180)-Math.PI/2, spread=65*Math.PI/180;
      ctx.strokeStyle='rgba(88,166,255,0.15)'; ctx.fillStyle='rgba(88,166,255,0.04)'; ctx.lineWidth=1;
      ctx.beginPath(); ctx.moveTo(gnb.x,gnb.y); ctx.arc(gnb.x,gnb.y,80,az-spread/2,az+spread/2); ctx.closePath(); ctx.fill(); ctx.stroke(); ctx.restore();
    });
  }
  function drawGnB(ctx, gnb, hovered) {
    const x=gnb.x, y=gnb.y, size=hovered?22:18;
    ctx.save();
    if (hovered) { ctx.shadowColor='#58a6ff'; ctx.shadowBlur=15; }
    ctx.strokeStyle=hovered?'#74b9ff':'#58a6ff'; ctx.lineWidth=2;
    ctx.beginPath(); ctx.moveTo(x,y-size); ctx.lineTo(x,y+size*0.3);
    ctx.moveTo(x-size*0.6,y-size*0.4); ctx.lineTo(x+size*0.6,y-size*0.4);
    ctx.moveTo(x-size*0.4,y-size*0.1); ctx.lineTo(x+size*0.4,y-size*0.1);
    ctx.moveTo(x-size*0.4,y+size*0.3); ctx.lineTo(x+size*0.4,y+size*0.3); ctx.stroke();
    ctx.beginPath(); ctx.arc(x,y,10,0,Math.PI*2);
    ctx.fillStyle=hovered?'rgba(88,166,255,0.3)':'rgba(88,166,255,0.15)'; ctx.fill();
    ctx.strokeStyle='#58a6ff'; ctx.lineWidth=1.5; ctx.stroke();
    ctx.shadowBlur=0;
    ctx.fillStyle='#e6edf3'; ctx.font='bold 10px system-ui'; ctx.textAlign='center'; ctx.fillText(gnb.id,x,y+size+14);
    const connectedCount=gnb.connected_ues||0;
    if (connectedCount>0) {
      ctx.beginPath(); ctx.arc(x+12,y-12,9,0,Math.PI*2); ctx.fillStyle='#3fb950'; ctx.fill();
      ctx.fillStyle='#0d1117'; ctx.font='bold 9px system-ui'; ctx.fillText(connectedCount,x+12,y-9);
    }
    ctx.restore();
  }
  function drawUE(ctx, ue, selected, hovered) {
    const x=ue.x, y=ue.y, size=selected?10:8, color=sinrColor(ue.sinr);
    const r=parseInt(color.slice(1,3),16), g=parseInt(color.slice(3,5),16), b=parseInt(color.slice(5,7),16);
    ctx.save();
    if (selected||hovered) { ctx.shadowColor=color; ctx.shadowBlur=12; }
    ctx.beginPath(); ctx.arc(x,y,size,0,Math.PI*2);
    ctx.fillStyle=selected?color:`rgba(${r},${g},${b},0.85)`; ctx.fill();
    ctx.strokeStyle=selected?'#fff':'#1c2128'; ctx.lineWidth=selected?2:1.5; ctx.stroke();
    ctx.shadowBlur=0;
    ctx.fillStyle='#8b949e'; ctx.font='9px system-ui'; ctx.textBaseline='alphabetic'; ctx.textAlign='center';
    ctx.fillText(ue.id,x,y+size+10);
    if (ue.throughput>0) {
      ctx.fillStyle=color; ctx.font='bold 8px system-ui';
      ctx.fillText(`${ue.throughput.toFixed(0)}Mbps`,x,y-size-4);
    }
    ctx.restore();
  }
  function drawUeTrail(ctx, ue) {
    if (!ue.position_history||ue.position_history.length<2) return;
    const trail=ue.position_history.slice(-20), color=sinrColor(ue.sinr);
    const r=parseInt(color.slice(1,3),16), g=parseInt(color.slice(3,5),16), b=parseInt(color.slice(5,7),16);
    ctx.save();
    for (let i=1;i<trail.length;i++) {
      ctx.strokeStyle=`rgba(${r},${g},${b},${(i/trail.length)*0.3})`; ctx.lineWidth=1;
      ctx.beginPath(); ctx.moveTo(trail[i-1].x,trail[i-1].y); ctx.lineTo(trail[i].x,trail[i].y); ctx.stroke();
    }
    ctx.restore();
  }

  return (
    <div className="canvas-container" style={{ position: 'relative' }}>
      <canvas
        ref={canvasRef}
        className="network-canvas"
        width={800} height={560}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => { dragRef.current=null; setHoveredId(null); setTooltip(null); }}
        onContextMenu={handleContextMenu}
        style={{ cursor: placeMode ? 'crosshair' : dragRef.current ? 'grabbing' : 'grab', width:'100%', height:'100%' }}
      />
      <div className="legend" style={{ position:'absolute', bottom:8, left:8, background:'rgba(13,17,23,0.8)', borderRadius:6, padding:'4px 8px' }}>
        <div className="legend-item"><div className="legend-dot" style={{background:'#58a6ff'}}></div>gNB</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#3fb950'}}></div>UE (Good)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#d29922'}}></div>UE (Fair)</div>
        <div className="legend-item"><div className="legend-dot" style={{background:'#f85149'}}></div>UE (Poor)</div>
        <div className="legend-item" style={{marginLeft:8, color:'#6e7681'}}>Drag to move • Right-click to remove</div>
      </div>
      {tooltip && (
        <div className="canvas-tooltip" style={{ left: tooltip.x - canvasRef.current?.getBoundingClientRect().left + 12, top: tooltip.y - canvasRef.current?.getBoundingClientRect().top - 10, position:'absolute', zIndex:50 }}>
          {tooltip.type==='ue' && (<>
            <div className="tooltip-title">📱 {tooltip.data.id}</div>
            <div className="tooltip-row"><span className="tooltip-label">Serving:</span><span className="tooltip-value">{tooltip.data.serving_gnb||'None'}</span></div>
            <div className="tooltip-row"><span className="tooltip-label">RSRP:</span><span className="tooltip-value">{tooltip.data.rsrp?.toFixed(1)} dBm</span></div>
            <div className="tooltip-row"><span className={`tooltip-value ${sinrClass(tooltip.data.sinr)}`} style={{gridColumn:'1/-1', display:'flex', justifyContent:'space-between'}}><span className="tooltip-label">SINR:</span>{tooltip.data.sinr?.toFixed(1)} dB</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Throughput:</span><span className="tooltip-value good">{tooltip.data.throughput?.toFixed(1)} Mbps</span></div>
            <div className="tooltip-row"><span className="tooltip-label">Modulation:</span><span className="tooltip-value">{tooltip.data.modulation}</span></div>
            <div style={{borderTop:'1px solid #30363d', marginTop:4, paddingTop:4}}>
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
            <div style={{borderTop:'1px solid #30363d', marginTop:4, paddingTop:4}}>
              <div className="tooltip-row"><span className="tooltip-label">Canvas X:</span><span className="tooltip-value" style={{color:'#58a6ff'}}>{Math.round(tooltip.data.x)} px</span></div>
              <div className="tooltip-row"><span className="tooltip-label">Canvas Y:</span><span className="tooltip-value" style={{color:'#58a6ff'}}>{Math.round(tooltip.data.y)} px</span></div>
              <div className="tooltip-row"><span className="tooltip-label">Position:</span><span className="tooltip-value" style={{color:'#8b949e'}}>{(tooltip.data.x*5).toFixed(0)}m, {(tooltip.data.y*5).toFixed(0)}m</span></div>
            </div>
          </>)}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
//  Line Chart Component
// ─────────────────────────────────────────────
function LineChart({ data, label, color, unit, height = 110, xLabel = 'Time (steps)', yLabel = '' }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  const downloadChart = () => {
    if (!canvasRef.current) return;
    const filename = `${label.replace(/\s+/g,'_')}_chart.png`;
    downloadCanvasWithTitle(canvasRef.current, label, filename);
  };

  useEffect(() => {
    if (!canvasRef.current) return;
    if (chartRef.current) chartRef.current.destroy();
    const labels = data.map((_, i) => i);
    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label,
          data,
          borderColor: color,
          backgroundColor: color + '22',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (ctx) => `${ctx.parsed.y?.toFixed(1)} ${unit}` }
          }
        },
        scales: {
          x: {
            display: true,
            title: { display: true, text: xLabel, color: '#6e7681', font: { size: 9 } },
            ticks: { color: '#6e7681', font: { size: 8 }, maxTicksLimit: 6 },
            grid: { color: 'rgba(48,54,61,0.4)' }
          },
          y: {
            grid: { color: 'rgba(48,54,61,0.5)', lineWidth: 1 },
            ticks: { color: '#6e7681', font: { size: 9 }, maxTicksLimit: 4 },
            border: { display: false },
            title: { display: true, text: yLabel || `${label} (${unit})`, color: '#6e7681', font: { size: 9 } }
          }
        }
      }
    });
    return () => { if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; } };
  }, [data, color, label, unit, xLabel, yLabel]);

  return (
    <div style={{ position: 'relative' }}>
      <button onClick={downloadChart} title="Download chart" style={{
        position: 'absolute', top: 0, right: 0, zIndex: 10,
        background: 'rgba(88,166,255,0.15)', border: '1px solid #30363d',
        borderRadius: 4, color: '#58a6ff', fontSize: 10, padding: '2px 6px', cursor: 'pointer'
      }}>⬇ PNG</button>
      <div style={{ height }}><canvas ref={canvasRef} /></div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Multi-line Chart (for global metrics)
// ─────────────────────────────────────────────
function MultiLineChart({ datasets, height = 130 }) {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current || !datasets.length) return;
    if (chartRef.current) chartRef.current.destroy();

    const maxLen = Math.max(...datasets.map(d => d.data.length));
    const labels = Array.from({ length: maxLen }, (_, i) => i);

    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels,
        datasets: datasets.map(ds => ({
          label: ds.label,
          data: ds.data,
          borderColor: ds.color,
          backgroundColor: ds.color + '15',
          borderWidth: 1.5,
          pointRadius: 0,
          fill: false,
          tension: 0.4,
          yAxisID: ds.yAxis || 'y',
        }))
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {
            display: true,
            labels: { color: '#8b949e', font: { size: 9 }, boxWidth: 10 }
          },
          tooltip: { mode: 'index', intersect: false }
        },
        scales: {
          x: { display: false },
          y: {
            grid: { color: 'rgba(48,54,61,0.5)' },
            ticks: { color: '#6e7681', font: { size: 9 }, maxTicksLimit: 4 },
            border: { display: false },
          }
        }
      }
    });

    return () => { if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; } };
  }, [datasets]);

  return <div style={{ height }}><canvas ref={canvasRef} /></div>;
}

// Add download button wrapper for MultiLineChart usage in UI
function MultiLineChartWithDownload(props) {
  const ref = useRef(null);
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => {
        const c = ref.current?.querySelector('canvas');
        if (c) downloadCanvasWithTitle(c, 'Multi-line Chart', 'multiline_chart.png');
      }} title="Download chart" style={{
        position: 'absolute', top: 4, right: 4, zIndex: 10,
        background: 'rgba(88,166,255,0.15)', border: '1px solid #30363d',
        borderRadius: 4, color: '#58a6ff', fontSize: 10, padding: '2px 6px', cursor: 'pointer'
      }}>⬇ PNG</button>
      <div ref={ref}><MultiLineChart {...props} /></div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Pathloss vs Distance Chart
// ─────────────────────────────────────────────
function PathlossChart() {
  const canvasRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return;
    if (chartRef.current) chartRef.current.destroy();

    // Generate theoretical pathloss curves
    const distances = Array.from({ length: 50 }, (_, i) => (i + 1) * 20); // 20m to 1000m
    
    const umaLos = distances.map(d => 28 + 22 * Math.log10(Math.sqrt(d**2 + (25-1.5)**2)) + 20 * Math.log10(3.5));
    const umaNlos = distances.map(d => 13.54 + 39.08 * Math.log10(Math.sqrt(d**2 + (25-1.5)**2)) + 20 * Math.log10(3.5));
    const umiLos = distances.map(d => 32.4 + 21 * Math.log10(Math.sqrt(d**2 + (10-1.5)**2)) + 20 * Math.log10(3.5));
    const rmaLos = distances.map(d => 20 * Math.log10(40 * Math.PI * d * 3.5 / 3) + 2 * d / 1000);

    chartRef.current = new Chart(canvasRef.current, {
      type: 'line',
      data: {
        labels: distances,
        datasets: [
          { label: 'UMa LOS', data: umaLos, borderColor: '#58a6ff', borderWidth: 1.5, pointRadius: 0, fill: false },
          { label: 'UMa NLOS', data: umaNlos, borderColor: '#58a6ff', borderWidth: 1.5, borderDash: [4,4], pointRadius: 0, fill: false },
          { label: 'UMi LOS', data: umiLos, borderColor: '#3fb950', borderWidth: 1.5, pointRadius: 0, fill: false },
          { label: 'RMa LOS', data: rmaLos, borderColor: '#d29922', borderWidth: 1.5, pointRadius: 0, fill: false },
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { labels: { color: '#8b949e', font: { size: 9 }, boxWidth: 10 } },
          tooltip: {
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)} dB`,
              title: (items) => `Distance: ${items[0].label} m`
            }
          }
        },
        scales: {
          x: {
            ticks: { color: '#6e7681', font: { size: 9 }, maxTicksLimit: 6 },
            grid: { color: 'rgba(48,54,61,0.5)' },
            title: { display: true, text: 'Distance (m)', color: '#6e7681', font: { size: 9 } }
          },
          y: {
            ticks: { color: '#6e7681', font: { size: 9 } },
            grid: { color: 'rgba(48,54,61,0.5)' },
            title: { display: true, text: 'Pathloss (dB)', color: '#6e7681', font: { size: 9 } }
          }
        }
      }
    });

    return () => { if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null; } };
  }, []);

  return <div style={{ height: 150 }}><canvas ref={canvasRef} /></div>;
}

// Wrapper to add download button to PathlossChart
function PathlossChartWithDownload() {
  const ref = useRef(null);
  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => {
        const c = ref.current?.querySelector('canvas');
        if (c) downloadCanvasWithTitle(c, 'Pathloss vs Distance (3GPP TR 38.901)', 'pathloss_vs_distance.png');
      }} title="Download chart" style={{
        position: 'absolute', top: 4, right: 4, zIndex: 10,
        background: 'rgba(88,166,255,0.15)', border: '1px solid #30363d',
        borderRadius: 4, color: '#58a6ff', fontSize: 10, padding: '2px 6px', cursor: 'pointer'
      }}>⬇ PNG</button>
      <div ref={ref}><PathlossChart /></div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Sidebar Component
// ─────────────────────────────────────────────
function Sidebar({ state, onAddGnb, onAddUe, onStart, onStop, onReset, 
                   placeMode, setPlaceMode, scenario, setScenario, 
                   simSpeed, setSimSpeed, params, setParams, simDuration, setSimDuration }) {
  const isRunning = state?.running || false;
  const numGnbs = Object.keys(state?.gnbs || {}).length;
  const numUes  = Object.keys(state?.ues  || {}).length;

  const [ueConfig, setUeConfig] = useState({ mobility: 'random_waypoint', speed: 3 });
  const [gnbConfig, setGnbConfig] = useState({ tx_power: 43, sectors: 3 });

  const handleStart = () => {
    let durationToUse = simDuration;
    if (durationToUse == null) {
      const input = window.prompt('Enter simulation duration in seconds:', '15');
      if (input === null) return; // user cancelled
      const parsed = parseFloat(input);
      if (Number.isNaN(parsed) || parsed <= 0) {
        alert('Invalid duration. Please enter a positive number.');
        return;
      }
      durationToUse = parsed;
    }

    fetch('/api/start_simulation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario, speed: simSpeed, duration: durationToUse })
    });
    console.log(`[5G Simulator] Simulation STARTED | Scenario: ${scenario} | Duration: ${durationToUse}s | Speed: ${simSpeed}x`);
    onStart(durationToUse);
  };

  const handleStop = () => {
    fetch('/api/stop_simulation', { method: 'POST' });
    onStop();
  };

  const handleReset = () => {
    fetch('/api/reset', { method: 'POST' });
    onReset();
  };

  return (
    <div className="sidebar">
      {/* Simulation Control */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Simulation</div>
        
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <div className={`sim-status-dot ${isRunning ? 'running' : ''}`}></div>
          <span style={{ fontSize: 11, color: isRunning ? '#3fb950' : '#6e7681' }}>
            {isRunning ? `Running  (t=${state?.sim_time?.toFixed(1)}s)` : 'Stopped'}
          </span>
        </div>
        
        {!isRunning ? (
          <button className="btn btn-success" onClick={handleStart}>▶ Start Simulation</button>
        ) : (
          <button className="btn btn-danger" onClick={handleStop}>⏹ Stop</button>
        )}
        <button className="btn btn-secondary" onClick={handleReset}>↺ Reset</button>
        
        {/* Speed control */}
        <div className="form-group" style={{ marginTop: 8 }}>
          <label className="form-label">Simulation Speed: {simSpeed}x</label>
          <input
            type="range" min="0.5" max="10" step="0.5"
            value={simSpeed}
            onChange={e => {
              const v = parseFloat(e.target.value);
              setSimSpeed(v);
              fetch('/api/set_speed', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ speed: v })
              });
            }}
            style={{ width: '100%' }}
          />
        </div>
      </div>
       <div className="form-group" style={{ marginTop: 8 }}>
          <label className="form-label">Sim Duration (seconds)</label>
          <div style={{ display: 'flex', gap: 6 }}>
            {[10, 20, 30, 60].map(s => (
              <button key={s}
                onClick={() => setSimDuration(simDuration === s ? null : s)}
                style={{
                  flex: 1, padding: '4px 0', fontSize: 11, borderRadius: 6,
                  border: `1px solid ${simDuration === s ? '#58a6ff' : '#30363d'}`,
                  background: simDuration === s ? 'rgba(88,166,255,0.15)' : '#1c2128',
                  color: simDuration === s ? '#58a6ff' : '#8b949e',
                  cursor: 'pointer'
                }}
              >{s}s</button>
            ))}
          </div>
          <div style={{ fontSize: 10, color: '#6e7681', marginTop: 6, textAlign: 'center' }}>
            {simDuration == null ? 'No preset selected — Start will prompt for duration.' : `Selected: ${simDuration}s`}
          </div>
        </div>
      {/* Scenario */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Scenario</div>
        <div className="scenario-buttons">
          {['UMa', 'UMi', 'RMa'].map(s => (
            <button
              key={s}
              className={`scenario-btn ${scenario === s ? 'active' : ''}`}
              onClick={() => {
                setScenario(s);
                fetch('/api/set_scenario', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ scenario: s })
                });
              }}
            >
              {s === 'UMa' ? '🌆' : s === 'UMi' ? '🏢' : '🌄'}<br/>
              {s === 'UMa' ? 'Urban Macro' : s === 'UMi' ? 'Urban Micro' : 'Rural Macro'}
            </button>
          ))}
        </div>
        <div style={{ fontSize: 10, color: '#6e7681', marginTop: 6, textAlign: 'center' }}>
          {scenario === 'UMa' && 'f=3.5GHz, hBS=25m, 3GPP TR 38.901'}
          {scenario === 'UMi' && 'f=3.5GHz, hBS=10m, Street Canyon'}
          {scenario === 'RMa' && 'f=3.5GHz, hBS=35m, Large Cell'}
        </div>
      </div>

      {/* Add gNB */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Deploy gNB ({numGnbs})</div>
        
        <div className="form-group">
          <label className="form-label">TX Power (dBm)</label>
          <input type="range" min="20" max="50" value={gnbConfig.tx_power}
            onChange={e => setGnbConfig(p => ({...p, tx_power: parseInt(e.target.value)}))}
            style={{ width: '100%' }} />
          <div style={{ textAlign: 'right', fontSize: 10, color: '#6e7681' }}>{gnbConfig.tx_power} dBm</div>
        </div>
        
        <div className="form-group">
          <label className="form-label">Sectors</label>
          <select className="form-control" value={gnbConfig.sectors}
            onChange={e => setGnbConfig(p => ({...p, sectors: parseInt(e.target.value)}))}>
            <option value={1}>1 Sector (Omni)</option>
            <option value={3}>3 Sectors</option>
          </select>
        </div>
        
        <button
          className={`btn ${placeMode === 'gnb' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setPlaceMode(placeMode === 'gnb' ? null : 'gnb')}
        >
          📡 {placeMode === 'gnb' ? 'Click canvas to place...' : 'Place gNB'}
        </button>
      </div>

      {/* Add UE */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Deploy UE ({numUes})</div>
        
        <div className="form-group">
          <label className="form-label">Mobility Model</label>
          <select className="form-control" value={ueConfig.mobility}
            onChange={e => setUeConfig(p => ({...p, mobility: e.target.value}))}>
            <option value="random_waypoint">Random Waypoint</option>
            <option value="constant_velocity">Constant Velocity</option>
            <option value="path_based">Path Based</option>
          </select>
        </div>
        
        <div className="form-group">
          <label className="form-label">Speed: {ueConfig.speed} m/s</label>
          <input type="range" min="1" max="30" value={ueConfig.speed}
            onChange={e => setUeConfig(p => ({...p, speed: parseFloat(e.target.value)}))}
            style={{ width: '100%' }} />
        </div>
        
        <button
          className={`btn ${placeMode === 'ue' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setPlaceMode(placeMode === 'ue' ? null : 'ue')}
        >
          📱 {placeMode === 'ue' ? 'Click canvas to place...' : 'Place UE'}
        </button>
        
        {/* Quick deploy */}
        <button className="btn btn-ghost" onClick={() => {
          // Deploy 3 UEs at random positions
          for (let i = 0; i < 3; i++) {
            setTimeout(() => {
              fetch('/api/add_ue', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  x: 50 + Math.random() * 700,
                  y: 50 + Math.random() * 480,
                  mobility: ueConfig.mobility,
                  speed: ueConfig.speed
                })
              });
            }, i * 50);
          }
        }}>⚡ Quick Deploy 3 UEs</button>
      </div>

      {/* Handover params */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Handover Params</div>
        
        <div className="form-group">
          <label className="form-label">Hysteresis: {params.hysteresis} dB</label>
          <input type="range" min="0" max="10" step="0.5" value={params.hysteresis}
            onChange={e => {
              const v = parseFloat(e.target.value);
              setParams(p => ({...p, hysteresis: v}));
              fetch('/api/set_params', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hysteresis: v })
              });
            }} style={{ width: '100%' }} />
        </div>
        
        <div className="form-group">
          <label className="form-label">TTT: {params.ttt * 100} ms</label>
          <input type="range" min="1" max="10" value={params.ttt}
            onChange={e => {
              const v = parseInt(e.target.value);
              setParams(p => ({...p, ttt: v}));
              fetch('/api/set_params', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ttt_steps: v })
              });
            }} style={{ width: '100%' }} />
        </div>
      </div>

      {/* Event Log */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">Event Log</div>
        <div className="event-log">
          {(state?.event_log || []).slice().reverse().map((ev, i) => (
            <div key={i} className={`event-item ${ev.message?.includes('Handover') ? 'event-handover' : ev.message?.includes('started') ? 'event-start' : ''}`}>
              <span className="event-time">{ev.time?.toFixed(1)}s</span>
              <span className="event-msg">{ev.message}</span>
            </div>
          ))}
          {(!state?.event_log?.length) && (
            <div style={{ color: '#6e7681', fontSize: 10 }}>No events yet...</div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Right Panel Component
// ─────────────────────────────────────────────
function RightPanel({ state, selectedUe }) {
  const [activeTab, setActiveTab] = useState('metrics');
  
  const ues = state?.ues || {};
  const metrics = state?.metrics || [];
  const globalStats = state?.global || {};
  const handovers = state?.handover_events || [];
  const totalFromUes = Object.values(ues).reduce((acc, u) => acc + (Number(u.throughput) || 0), 0);
  const numUesFromState = Object.keys(ues).length;
  const latestMetric = metrics.length ? metrics[metrics.length - 1] : null;
  const latestTotal = totalFromUes > 0 ? totalFromUes : (latestMetric?.total_throughput ?? globalStats.total_throughput ?? 0);
  const latestNumUes = numUesFromState > 0 ? numUesFromState : (latestMetric?.num_ues ?? globalStats.num_ues ?? 0);
  const latestAvgPerUe = latestNumUes > 0 ? (latestTotal / latestNumUes) : 0;
  
  // Extract time series from metrics
  const tpHistory = metrics.map(m => m.total_throughput);
  const sinrHistory = metrics.map(m => m.avg_sinr);

  // Selected UE data
  const selectedUeData = selectedUe ? ues[selectedUe] : null;

  return (
    <div className="right-panel">
      <div className="panel-tabs">
        {['metrics', 'ues', 'charts', 'handovers'].map(tab => (
          <div key={tab} className={`panel-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}>
            {tab === 'metrics' ? '📊' : tab === 'ues' ? '📱' : tab === 'charts' ? '📈' : '🔄'}
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </div>
        ))}
      </div>

      <div className="panel-content">
        {/* ── Metrics Tab ── */}
        {activeTab === 'metrics' && (
          <>
            <div className="stat-grid">
              <div className="stat-card">
                <div className="stat-card-value" style={{ color: '#3fb950' }} title={String(globalStats.total_throughput || 0)}>
                  {formatThroughput(latestTotal)}
                </div>
                <div className="stat-card-label">Total Throughput</div>
              </div>
              <div className="stat-card">
                <div className="stat-card-value" style={{ color: '#58a6ff' }} title={String(latestAvgPerUe || 0)}>
                  {formatThroughput(latestAvgPerUe)}
                </div>
                <div className="stat-card-label">Avg TP/UE</div>
              </div>
              <div className="stat-card">
                <div className={`stat-card-value ${sinrClass(globalStats.avg_sinr || 0)}`}>
                  {globalStats.avg_sinr?.toFixed(1) || 0}<span style={{fontSize:10}}> dB</span>
                </div>
                <div className="stat-card-label">Avg SINR</div>
              </div>
              <div className="stat-card">
                <div className="stat-card-value" style={{ color: '#f85149' }}>
                  {globalStats.packet_loss || 0}<span style={{fontSize:10}}> %</span>
                </div>
                <div className="stat-card-label">Packet Loss</div>
              </div>
              <div className="stat-card">
                <div className="stat-card-value" style={{ color: '#d29922' }}>
                  {globalStats.total_handovers || 0}
                </div>
                <div className="stat-card-label">Handovers</div>
              </div>
            </div>

            <div className="stat-grid">
              <div className="stat-card">
                <div className="stat-card-value" style={{ color: '#58a6ff' }}>
                  {globalStats.num_gnbs || 0}
                </div>
                <div className="stat-card-label">gNBs</div>
              </div>
              <div className="stat-card">
                <div className="stat-card-value" style={{ color: '#3fb950' }}>
                  {globalStats.num_ues || 0}
                </div>
                <div className="stat-card-label">UEs</div>
              </div>
            </div>

            {/* Per-gNB stats */}
            {Object.values(state?.gnbs || {}).map(gnb => (
              <div key={gnb.id} className="chart-card" style={{ marginBottom: 6 }}>
                <div className="chart-card-title">
                  📡 {gnb.id}
                  <span className="badge badge-blue">{gnb.connected_ues} UEs</span>
                </div>
                <div style={{ fontSize: 10, color: '#8b949e' }}>
                  <div className="tooltip-row">
                    <span>TX Power:</span><span>{gnb.tx_power_dbm} dBm</span>
                  </div>
                  <div className="tooltip-row">
                    <span>Throughput:</span>
                    <span style={{ color: '#3fb950' }}>{gnb.total_throughput?.toFixed(1)} Mbps</span>
                  </div>
                  <div style={{borderTop:'1px solid #30363d', marginTop:4, paddingTop:4}}>
                    <div className="tooltip-row">
                      <span>X / Y (px):</span>
                      <span style={{color:'#58a6ff'}}>{Math.round(gnb.x)}, {Math.round(gnb.y)}</span>
                    </div>
                    <div className="tooltip-row">
                      <span>X / Y (m):</span>
                      <span style={{color:'#6e7681'}}>{(gnb.x*5).toFixed(0)}m, {(gnb.y*5).toFixed(0)}m</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}

            {/* Selected UE details */}
            {selectedUeData && (
              <div className="chart-card" style={{ borderColor: '#3fb950' }}>
                <div className="chart-card-title" style={{ color: '#3fb950' }}>
                  📱 {selectedUeData.id} (Selected)
                </div>
                {[
                  ['RSRP', `${selectedUeData.rsrp?.toFixed(1)} dBm`, rsrpColor(selectedUeData.rsrp)],
                  ['RSRQ', `${selectedUeData.rsrq?.toFixed(1)} dB`, '#58a6ff'],
                  ['SINR', `${selectedUeData.sinr?.toFixed(1)} dB`, sinrColor(selectedUeData.sinr)],
                  ['Throughput', `${selectedUeData.throughput?.toFixed(1)} Mbps`, '#3fb950'],
                  ['Distance', `${selectedUeData.distance?.toFixed(0)} m`, '#8b949e'],
                  ['Modulation', selectedUeData.modulation, '#bc8cff'],
                  ['Velocity', `${selectedUeData.velocity?.toFixed(1)} m/s`, '#8b949e'],
                  ['Handovers', selectedUeData.handover_count, '#d29922'],
                  ['Ping-Pong', selectedUeData.ping_pong_count, '#f85149'],
                  ['X (px/m)', `${Math.round(selectedUeData.x)} / ${(selectedUeData.x*5).toFixed(0)}m`, '#58a6ff'],
                  ['Y (px/m)', `${Math.round(selectedUeData.y)} / ${(selectedUeData.y*5).toFixed(0)}m`, '#58a6ff'],
                ].map(([label, val, color]) => (
                  <div key={label} className="tooltip-row" style={{ fontSize: 11 }}>
                    <span className="tooltip-label">{label}:</span>
                    <span style={{ color, fontWeight: 600 }}>{val}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ── UE List Tab ── */}
        {activeTab === 'ues' && (
          <>
            {Object.values(ues).length === 0 && (
              <div className="loading">No UEs deployed yet</div>
            )}
            {Object.values(ues).map(ue => (
              <div key={ue.id} className={`ue-list-item ${selectedUe === ue.id ? 'selected' : ''}`}>
                <div className="ue-list-header">
                  <span className="ue-id">{ue.id}</span>
                  <span className="ue-serving">{ue.serving_gnb || 'Disconnected'}</span>
                </div>
                <div className="ue-metrics-grid">
                  <div className="ue-metric">
                    <span className="ue-metric-label">RSRP</span>
                    <span className="ue-metric-value" style={{ color: rsrpColor(ue.rsrp) }}>
                      {ue.rsrp?.toFixed(0)} dBm
                    </span>
                  </div>
                  <div className="ue-metric">
                    <span className="ue-metric-label">SINR</span>
                    <span className="ue-metric-value" style={{ color: sinrColor(ue.sinr) }}>
                      {ue.sinr?.toFixed(1)} dB
                    </span>
                  </div>
                  <div className="ue-metric">
                    <span className="ue-metric-label">Throughput</span>
                    <span className="ue-metric-value" style={{ color: '#3fb950' }}>
                      {ue.throughput?.toFixed(0)} Mbps
                    </span>
                  </div>
                  <div className="ue-metric">
                    <span className="ue-metric-label">Modulation</span>
                    <span className="ue-metric-value" style={{ color: '#bc8cff' }}>
                      {ue.modulation}
                    </span>
                  </div>
                  <div className="ue-metric">
                    <span className="ue-metric-label">Handovers</span>
                    <span className="ue-metric-value" style={{ color: '#d29922' }}>
                      {ue.handover_count}
                    </span>
                  </div>
                  <div className="ue-metric">
                    <span className="ue-metric-label">Speed</span>
                    <span className="ue-metric-value">{ue.velocity?.toFixed(1)} m/s</span>
                  </div>
                </div>
                <div style={{
                  marginTop: 5, paddingTop: 5,
                  borderTop: '1px solid #30363d',
                  display: 'flex', justifyContent: 'space-between',
                  fontSize: 10
                }}>
                  <span style={{ color: '#6e7681' }}>📍 Position:</span>
                  <span style={{ color: '#58a6ff', fontFamily: 'monospace' }}>
                    X: {Math.round(ue.x)}px ({(ue.x * 5).toFixed(0)}m)
                  </span>
                  <span style={{ color: '#58a6ff', fontFamily: 'monospace' }}>
                    Y: {Math.round(ue.y)}px ({(ue.y * 5).toFixed(0)}m)
                  </span>
                </div>
              </div>
            ))}
          </>
        )}

        {/* ── Charts Tab ── */}
        {activeTab === 'charts' && (
          <>
            <div className="chart-card">
              <div className="chart-card-title">📈 Total Throughput vs Time</div>
              <LineChart data={tpHistory} label="Total Throughput" color="#3fb950" unit="Mbps"
                xLabel="Time (steps × 100ms)" yLabel="Throughput (Mbps)" />
            </div>
            
            <div className="chart-card">
              <div className="chart-card-title">📡 Avg SINR vs Time</div>
              <LineChart data={sinrHistory} label="Avg SINR" color="#58a6ff" unit="dB"
                xLabel="Time (steps × 100ms)" yLabel="SINR (dB)" />
            </div>
            
            {selectedUe && ues[selectedUe] && (
              <>
                <div className="chart-card">
                  <div className="chart-card-title">📱 {selectedUe} - RSRP</div>
                  <LineChart data={ues[selectedUe].rsrp_history || []} label="RSRP"
                    color="#d29922" unit="dBm" height={100}
                    xLabel="Time (steps)" yLabel="RSRP (dBm)" />
                </div>
                <div className="chart-card">
                  <div className="chart-card-title">📱 {selectedUe} - Throughput</div>
                  <LineChart data={ues[selectedUe].throughput_history || []} label="Throughput"
                    color="#3fb950" unit="Mbps" height={100}
                    xLabel="Time (steps)" yLabel="Throughput (Mbps)" />
                </div>
              </>
            )}
            
            <div className="chart-card">
              <div className="chart-card-title">📉 Pathloss vs Distance (3GPP TR 38.901)</div>
              <PathlossChartWithDownload />
            </div>
          </>
        )}

        {/* ── Handovers Tab ── */}
        {activeTab === 'handovers' && (
          <>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 8 }}>
              Total: <strong style={{ color: '#d29922' }}>{globalStats.total_handovers || 0}</strong> handovers
            </div>
            
            {handovers.length === 0 && (
              <div className="loading">No handovers yet</div>
            )}
            
            {handovers.slice().reverse().map((ho, i) => (
              <div key={i} className="ho-item">
                <div className="ho-header">
                  <span className="ho-ue">{ho.from?.includes('UE') ? '' : '📱 '}{ho.from?.split('-')[0]}</span>
                  <span className="ho-time">{ho.time?.toFixed(1)}s</span>
                </div>
                <div className="ho-route">
                  {ho.from} → {ho.target}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
                  <span style={{ fontSize: 9, color: '#6e7681' }}>
                    RSRP: {ho.rsrp?.toFixed(1)} dBm | SINR: {ho.sinr?.toFixed(1)} dB
                  </span>
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
//  Top Navigation
// ─────────────────────────────────────────────
function TopNav({ state, scenario }) {
  const globalStats = state?.global || {};
  const isRunning = state?.running || false;
  const metrics = state?.metrics || [];

  // Prefer summing current UE throughputs from state (accurate real-time total)
  const uesObj = state?.ues || {};
  const totalFromUes = Object.values(uesObj).reduce((acc, u) => acc + (Number(u.throughput) || 0), 0);
  const numUesFromState = Object.keys(uesObj).length;

  // Use latest metric entry if available as fallback
  const latestMetric = metrics.length ? metrics[metrics.length - 1] : null;
  const latestTotal = totalFromUes > 0 ? totalFromUes : (latestMetric?.total_throughput ?? globalStats.total_throughput ?? 0);
  const latestNumUes = numUesFromState > 0 ? numUesFromState : (latestMetric?.num_ues ?? globalStats.num_ues ?? 0);
  const latestAvgPerUe = latestNumUes > 0 ? (latestTotal / latestNumUes) : 0;

  // Small sparklines refs
  const tpCanvasRef = useRef(null);
  const avgCanvasRef = useRef(null);

  useEffect(() => {
    const drawSpark = (canvas, data, color) => {
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const W = canvas.width;
      const H = canvas.height;
      ctx.clearRect(0,0,W,H);
      if (!data || data.length === 0) return;
      const maxV = Math.max(...data, 1);
      const minV = Math.min(...data, 0);
      const len = data.length;
      ctx.lineWidth = 2;
      ctx.strokeStyle = color;
      ctx.beginPath();
      for (let i = 0; i < len; i++) {
        const x = (i / (len - 1 || 1)) * (W - 4) + 2;
        const v = data[i];
        const y = H - 2 - ((v - minV) / (maxV - minV || 1)) * (H - 4);
        if (i === 0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
      }
      ctx.stroke();
    };

    const tpHistory = metrics.map(m => m.total_throughput || 0);
    const avgHistory = metrics.map(m => {
      const n = (m.num_ues ?? state?.global?.num_ues ?? 0);
      return n > 0 ? ((m.total_throughput || 0) / n) : 0;
    });

    drawSpark(tpCanvasRef.current, tpHistory, '#3fb950');
    drawSpark(avgCanvasRef.current, avgHistory, '#58a6ff');
  }, [state?.metrics, state?.global]);

  return (
    <nav className="top-nav">
      <div className="nav-logo">
        <div className="nav-logo-icon">5G</div>
        NR Network Simulator
      </div>
      <span className="nav-badge">3GPP TR 38.901</span>
      <span className="nav-badge" style={{ borderColor: 'rgba(63,185,80,0.3)', color: '#3fb950', background: 'rgba(63,185,80,0.1)' }}>
        {scenario}
      </span>

      <div className="nav-spacer" />

      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <div className={`sim-status-dot ${isRunning ? 'running' : ''}`}></div>
        <span style={{ fontSize: 11, color: isRunning ? '#3fb950' : '#6e7681' }}>
          {isRunning ? 'LIVE' : 'IDLE'}
        </span>
      </div>

      {[
        ['Total TP', formatThroughput(latestTotal), latestTotal > 100 ? 'good' : 'warn'],
        ['Avg TP/UE', formatThroughput(latestAvgPerUe), ''],
        ['Avg SINR', `${(globalStats.avg_sinr || 0).toFixed(1)} dB`, globalStats.avg_sinr > 10 ? 'good' : globalStats.avg_sinr > 0 ? 'warn' : 'bad'],
        ['Pkt Loss', `${globalStats.packet_loss || 0}%`, globalStats.packet_loss < 5 ? 'good' : globalStats.packet_loss < 20 ? 'warn' : 'bad'],
        ['Handovers', globalStats.total_handovers || 0, ''],
        ['gNBs', globalStats.num_gnbs || 0, ''],
        ['UEs', globalStats.num_ues || 0, ''],
        ['Step', state?.step || 0, ''],
      ].map(([label, value, cls]) => (
        <div key={label} className="nav-stat">
          <div className="nav-stat-label">{label}</div>
          <div className={`nav-stat-value ${cls}`}>{value}</div>
        </div>
      ))}

      {/* Compact sparkline container to keep nav layout clean */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginLeft: 12 }}>
        <div style={{ textAlign: 'center', color: '#8b949e', fontSize: 11 }}>
          <div style={{ fontSize: 10 }}>Total TP</div>
          <canvas ref={tpCanvasRef} width={120} height={28} style={{ width: 120, height: 28 }} />
        </div>
        <div style={{ textAlign: 'center', color: '#8b949e', fontSize: 11 }}>
          <div style={{ fontSize: 10 }}>Avg TP/UE</div>
          <canvas ref={avgCanvasRef} width={120} height={28} style={{ width: 120, height: 28 }} />
        </div>
      </div>
    </nav>
  );
}

// ─────────────────────────────────────────────
//  Main App
// ─────────────────────────────────────────────
function App() {
  const [state, setState] = useState(null);
  const [placeMode, setPlaceMode] = useState(null);
  const [scenario, setScenario] = useState('UMa');
  const [simSpeed, setSimSpeed] = useState(1.0);
  const [selectedUe, setSelectedUe] = useState(null);
  const [params, setParams] = useState({ hysteresis: 3.0, ttt: 3 });
  const [cursorPos, setCursorPos] = useState({ x: 0, y: 0 });
  const [simDuration, setSimDuration] = useState(10);
  const simTimerRef = useRef(null);

  // SSE real-time connection
  useEffect(() => {
    // Initial state fetch
    fetch('/api/get_state')
      .then(r => r.json())
      .then(s => setState(s));

    // Server-Sent Events for real-time updates
    const evtSource = new EventSource('/api/stream');
    evtSource.onmessage = (e) => {
      try {
        const newState = JSON.parse(e.data);
        if (!newState.error) setState(newState);
      } catch {}
    };
    evtSource.onerror = () => {
      console.warn('SSE connection lost, retrying...');
    };

    return () => evtSource.close();
  }, []);
  // Handle Start
  const handleStart = useCallback((duration) => {
    if (simTimerRef.current) {
      clearTimeout(simTimerRef.current);
      simTimerRef.current = null;
    }

    const startTs = Date.now();
    const endTs = startTs + duration * 1000;
    console.log(`[5G Simulator] Simulation STARTED for ${duration}s — will end at ${new Date(endTs).toISOString()}`);

    // Schedule a single stop request exactly after `duration` seconds.
    simTimerRef.current = setTimeout(() => {
      fetch('/api/stop_simulation', { method: 'POST' });
      console.log(`[5G Simulator] Simulation STOPPED after ${duration}s (requested at ${new Date().toISOString()})`);
      simTimerRef.current = null;
    }, duration * 1000);
  }, []);
  
  const handleStop = useCallback(() => {
    if (simTimerRef.current) {
      clearTimeout(simTimerRef.current);
      simTimerRef.current = null;
      console.log('[5G Simulator] Simulation timer cleared by user stop.');
    }
    fetch('/api/stop_simulation', { method: 'POST' });
  }, []);
  // Place gNB on canvas click
  const handlePlaceGnb = useCallback((x, y) => {
    fetch('/api/add_gnb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y, tx_power: 43, num_sectors: 3 })
    });
    setPlaceMode(null);
  }, []);

  // Place UE on canvas click
  const handlePlaceUe = useCallback((x, y) => {
    fetch('/api/add_ue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y, mobility: 'random_waypoint', speed: 3.0 })
    });
    setPlaceMode(null);
  }, []);

  return (
    <div className="app-container">
      <TopNav state={state} scenario={scenario} />

      <Sidebar
        state={state}
        onAddGnb={handlePlaceGnb}
        onAddUe={handlePlaceUe}
        onStart={handleStart}
        onStop={handleStop}
        onReset={() => setState(null)}
        placeMode={placeMode}
        setPlaceMode={setPlaceMode}
        scenario={scenario}
        setScenario={setScenario}
        simSpeed={simSpeed}
        setSimSpeed={setSimSpeed}
        params={params}
        setParams={setParams}
        simDuration={simDuration}
        setSimDuration={setSimDuration}
      />

      <div className="main-area">
        <div className="canvas-toolbar">
          <span className="canvas-toolbar-title">Network Topology</span>
          <div style={{ flex: 1 }} />
          {placeMode && (
            <div className="placement-indicator" style={{ position: 'static', transform: 'none', fontSize: 11, padding: '4px 12px' }}>
              Click to place {placeMode === 'gnb' ? '📡 gNB' : '📱 UE'} — or press Esc to cancel
            </div>
          )}
          <button className="btn btn-ghost" style={{ width: 'auto', fontSize: 10, padding: '4px 10px' }}
            onClick={() => {
              // Add default scenario
              fetch('/api/add_gnb', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({x:200,y:200}) });
              setTimeout(() => fetch('/api/add_gnb', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({x:600,y:200}) }), 50);
              setTimeout(() => fetch('/api/add_gnb', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({x:400,y:440}) }), 100);
            }}>
            ⚡ Default Topology
          </button>
        </div>
        
        <NetworkCanvas
          state={state}
          onPlaceGnb={handlePlaceGnb}
          onPlaceUe={handlePlaceUe}
          placeMode={placeMode}
          selectedUe={selectedUe}
          setSelectedUe={setSelectedUe}
          onCursorMove={setCursorPos}
        />
        {/* Cursor coordinate bar */}
      <div style={{
        flexShrink: 0, padding: '4px 12px',
        background: '#161b22', borderTop: '1px solid #30363d',
        display: 'flex', alignItems: 'center', gap: 16, fontSize: 11
      }}>
        <span style={{ color: '#6e7681' }}>Canvas Cursor:</span>
        <span style={{ color: '#58a6ff', fontFamily: 'monospace' }}>
          X: <strong>{cursorPos.x} px</strong> ({(cursorPos.x * 5).toFixed(0)} m)
        </span>
        <span style={{ color: '#58a6ff', fontFamily: 'monospace' }}>
          Y: <strong>{cursorPos.y} px</strong> ({(cursorPos.y * 5).toFixed(0)} m)
        </span>
        <span style={{ color: '#6e7681' }}>|</span>
        <span style={{ color: '#3fb950', fontFamily: 'monospace' }}>
          gNBs: {Object.keys(state?.gnbs||{}).length} &nbsp;|&nbsp; UEs: {Object.keys(state?.ues||{}).length}
        </span>
        {placeMode && <span style={{ color: '#d29922' }}>📍 Placing: {placeMode.toUpperCase()}</span>}
      </div>
      </div>

      <RightPanel state={state} selectedUe={selectedUe} />
    </div>
  );
}

// ── Keyboard shortcut
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // Handled by placeMode state
  }
});

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
