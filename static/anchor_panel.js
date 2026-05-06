// ─────────────────────────────────────────────
//  AnchorStatusPanel  — live Anchor / DC panel
//  Anchor mode activates via TCP socket (port 5555)
//  OR automatically when the external ping-pong
//  detector places a new AnchorGNB via REST.
// ─────────────────────────────────────────────
function AnchorStatusPanel({state}) {
  const anchor     = state?.anchor     || {};
  const gnbs       = state?.gnbs       || {};
  const ues        = state?.ues        || {};

  const isEnabled   = !!anchor.enabled;
  const anchorGnb   = anchor.anchor_gnb   || null;
  const anchorGnbIds= anchor.anchor_gnb_ids || [];
  const tcpPort     = anchor.tcp_port     || 5555;
  const tcpClients  = anchor.tcp_clients  || 0;

  // Filter AnchorGNB nodes (is_anchor flag from server)
  const anchorGnbList = Object.values(gnbs).filter(g => g.is_anchor);
  const dcUes         = Object.values(ues).filter(u => u.dc_enabled);

  const panelBorder = anchorGnbList.length > 0
    ? '1px solid #bc8cff'
    : isEnabled
      ? '1px solid #3fb950'
      : '1px solid #30363d';
  const panelBg = anchorGnbList.length > 0
    ? 'rgba(188,140,255,0.06)'
    : isEnabled
      ? 'rgba(63,185,80,0.06)'
      : 'transparent';

  return (
    <div style={{
      border: panelBorder,
      borderRadius: 6,
      padding: '8px 10px',
      background: panelBg,
      marginBottom: 6,
      marginTop: 6,
      transition: 'all 0.3s',
    }}>
      {/* Header */}
      <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:6}}>
        <div style={{
          width: 8, height: 8, borderRadius: '50%',
          background: anchorGnbList.length > 0
            ? '#bc8cff'
            : isEnabled ? '#3fb950' : '#6e7681',
          boxShadow: anchorGnbList.length > 0
            ? '0 0 8px #bc8cff'
            : isEnabled ? '0 0 6px #3fb950' : 'none',
          flexShrink: 0,
        }}/>
        <span style={{fontSize:11, fontWeight:700, color:
          anchorGnbList.length > 0 ? '#bc8cff'
          : isEnabled ? '#3fb950' : '#6e7681'}}>
          ANCHOR / DC {anchorGnbList.length > 0
            ? `ACTIVE (${anchorGnbList.length} AnchorGNB)`
            : isEnabled ? 'ACTIVE' : 'INACTIVE'}
        </span>
      </div>

      {/* Mode selector — read-only */}
      <div style={{marginBottom:6}}>
        <label style={{fontSize:9, color:'#6e7681', display:'block', marginBottom:3}}>
          Anchor Mode
        </label>
        <select
          disabled
          value={anchorGnbList.length > 0 ? 'anchor_gnb' : isEnabled ? 'enabled' : 'disabled'}
          style={{
            width:'100%', fontSize:10, padding:'3px 6px', borderRadius:4,
            background:'var(--bg-primary)',
            border:'1px solid var(--border)',
            color: anchorGnbList.length > 0 ? '#bc8cff'
                   : isEnabled ? '#3fb950' : '#6e7681',
            opacity: 0.85,
            cursor: 'not-allowed',
          }}
        >
          <option value="disabled">⚫ Disabled (default)</option>
          <option value="enabled">🟢 Enabled (via socket)</option>
          <option value="anchor_gnb">🟣 AnchorGNB active (auto-placed)</option>
        </select>
        <div style={{fontSize:9, color:'#6e7681', marginTop:3, lineHeight:1.5}}>
          Auto-activated when external script detects ping-pong HOs.<br/>
          TCP port <strong style={{color:'#58a6ff'}}>{tcpPort}</strong> · REST <code style={{color:'#bc8cff',fontSize:9}}>/api/add_anchor_gnb</code>
        </div>
      </div>

      {/* AnchorGNB nodes */}
      {anchorGnbList.length > 0 && (
        <div style={{marginBottom:6}}>
          <div style={{fontSize:9, color:'#bc8cff', fontWeight:700, marginBottom:4}}>
            🟣 AnchorGNB Nodes ({anchorGnbList.length})
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:3}}>
            {anchorGnbList.map(g => (
              <div key={g.id} style={{
                display:'flex', justifyContent:'space-between',
                fontSize:9, padding:'3px 8px', borderRadius:5,
                background:'rgba(188,140,255,0.10)',
                border:'1px solid rgba(188,140,255,0.3)',
              }}>
                <span style={{color:'#bc8cff', fontWeight:700}}>{g.id}</span>
                <span style={{color:'#6e7681'}}>
                  TX:{g.tx_power_dbm}dBm · {g.num_sectors}sec · {g.connected_ues}UEs
                </span>
                <span style={{
                  color: g.total_throughput > 0 ? '#3fb950' : '#6e7681',
                  fontWeight:600,
                }}>{g.total_throughput?.toFixed(0)} Mbps</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Primary anchor gNB (MeNB from election) */}
      {!anchorGnbList.length && (
        <div style={{display:'flex', justifyContent:'space-between', fontSize:10, marginBottom:4}}>
          <span style={{color:'#6e7681'}}>Anchor gNB (MeNB)</span>
          <span style={{
            color: anchorGnb ? '#58a6ff' : '#6e7681',
            fontWeight: anchorGnb ? 700 : 400,
          }}>{anchorGnb || '—'}</span>
        </div>
      )}

      {/* TCP clients */}
      <div style={{display:'flex', justifyContent:'space-between', fontSize:10, marginBottom:4}}>
        <span style={{color:'#6e7681'}}>TCP clients (port {tcpPort})</span>
        <span style={{
          color: tcpClients > 0 ? '#3fb950' : '#6e7681',
          fontWeight:600,
        }}>{tcpClients}</span>
      </div>

      {/* DC UEs */}
      {(isEnabled || anchorGnbList.length > 0) && (
        <div style={{marginTop:4}}>
          <div style={{fontSize:9, color:'#6e7681', marginBottom:4}}>
            Dual-Connectivity UEs ({dcUes.length})
          </div>
          <div style={{display:'flex', flexWrap:'wrap', gap:3}}>
            {dcUes.map(u => (
              <div key={u.id} style={{
                fontSize:9, padding:'2px 7px', borderRadius:10,
                background: u.anchor_gnb_id && u.anchor_gnb_id.startsWith('AnchorGNB')
                  ? 'rgba(188,140,255,0.15)' : 'rgba(63,185,80,0.12)',
                border: u.anchor_gnb_id && u.anchor_gnb_id.startsWith('AnchorGNB')
                  ? '1px solid rgba(188,140,255,0.4)' : '1px solid rgba(63,185,80,0.3)',
                color: u.anchor_gnb_id && u.anchor_gnb_id.startsWith('AnchorGNB')
                  ? '#bc8cff' : '#3fb950',
              }}>
                <span style={{fontWeight:700}}>{u.id}</span>
                <span style={{color:'#6e7681', marginLeft:4}}>
                  M:{u.anchor_gnb_id||'?'} S:{u.secondary_gnb_id||'?'}
                </span>
                {u.dc_throughput > 0 && (
                  <span style={{color:'#58a6ff', marginLeft:4}}>
                    {u.dc_throughput.toFixed(0)}Mbps
                  </span>
                )}
              </div>
            ))}
            {dcUes.length === 0 && (
              <span style={{fontSize:9, color:'#6e7681'}}>No UEs in DC yet</span>
            )}
          </div>
        </div>
      )}

      {/* Handover reduction hint */}
      {anchorGnbList.length > 0 && dcUes.length > 0 && (
        <div style={{
          marginTop:6, fontSize:9, color:'#3fb950',
          padding:'3px 7px', borderRadius:4,
          background:'rgba(63,185,80,0.08)',
          border:'1px solid rgba(63,185,80,0.2)',
        }}>
          ✅ DC active — ping-pong HOs suppressed for {dcUes.length} UE{dcUes.length!==1?'s':''}
        </div>
      )}
    </div>
  );
}
