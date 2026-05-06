# 5G NR Network Simulator — Anchor / Dual-Connectivity Extension

## New Files Added

| File | Purpose |
|------|---------|
| `simulation/anchor.py` | Core AnchorManager: DC logic, TCP server (port 5555), RSRP chart generation |
| `simulation/simulator.py` | Modified: integrates AnchorManager at every HO and step |
| `simulation/ue.py` | Modified: adds `dc_enabled`, `anchor_gnb_id`, `secondary_gnb_id` fields |
| `app.py` | Modified: adds `/api/anchor/*` REST endpoints |
| `static/anchor_panel.js` | React component: read-only Anchor Mode panel (disabled dropdown) |
| `templates/index.html` | Modified: loads `anchor_panel.js` before `main.js` |
| `pingpong_HO_detection_and_Anchor_assignment.py` | **External script**: ping-pong detection + anchor assignment |
| `handover_charts/` | Auto-created folder for RSRP-vs-time PNG charts |
| `requirements.txt` | Python dependencies |

---

## Quick Start

```bash
# 1. Install dependencies
pip install flask matplotlib colorama numpy

# 2. Start the simulator
python app.py
# Web UI →  http://localhost:8080
# TCP HO →  port 5555 (automatic)

# 3. In a second terminal, run the ping-pong detector
python pingpong_HO_detection_and_Anchor_assignment.py
# Connects to port 5555 automatically
# Fetches gNB positions from REST API on startup
```

---

## Anchor Mode — How it Works

### Design Decision: Disabled by Default
The Anchor Mode is **DISABLED by default**. The GUI shows a **grayed-out "Anchor Mode"
dropdown** (inside the Simulation sidebar section) that cannot be clicked.  
Anchor mode can **only** be activated through the TCP socket on port **5555**.

### Activation via TCP Socket
```bash
# Using netcat
echo "ENABLE_ANCHOR" | nc 127.0.0.1 5555

# Using Python
import socket, json
s = socket.socket(); s.connect(('127.0.0.1', 5555))
s.sendall(b"ENABLE_ANCHOR\n")
print(json.loads(s.recv(1024)))   # {"cmd":"ACK","ok":true,"msg":"Anchor enabled – anchor=gNB-2"}

# Disable
s.sendall(b"DISABLE_ANCHOR\n")

# Get status
s.sendall(b"GET_STATUS\n")
```

### Anchor Selection Scoring
The best anchor gNB is chosen by a weighted score across four criteria:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| TX Power | 30% | Highest power = best capability / coverage |
| Centrality | 30% | Closest to canvas centroid = largest virtual cell |
| Stability | 20% | gNBs are always stable (fixed nodes) |
| Load Capacity | 20% | Fewer connected UEs = more available capacity |

### Dual Connectivity (DC) Invariants
- Every UE gets exactly **1 MeNB (anchor)** + **1 SeNB (normal gNB)**
- **Never** two anchors or two normal gNBs for one UE
- **SeNB** can change during the simulation (best RSRP non-anchor gNB)
- **MeNB** only changes on a ping-pong-triggered `ASSIGN_ANCHOR` command
- DC throughput = MeNB throughput + SeNB throughput (summed)

---

## TCP Socket Protocol (port 5555)

### Outgoing — HO Event JSON (one per line, per handover)
```json
{
  "timestamp":   "2026-04-07 15:12:34.567",
  "UE_ID":       "UE-5",
  "serving_gnb": "gNB-3",
  "target_gnb":  "gNB-7",
  "RSRP_dBm":    -82.4,
  "UE_x":        123.45,
  "UE_y":        67.89,
  "sim_time_s":  12.300
}
```

### Incoming — Commands
```
ENABLE_ANCHOR                    → turn anchor mode ON
DISABLE_ANCHOR                   → turn anchor mode OFF
ASSIGN_ANCHOR:<UE_ID>:<GNB_ID>  → force anchor assignment for a UE
GET_STATUS                       → request anchor status JSON
```

### Outgoing — ACK
```json
{"cmd": "ACK", "ok": true, "msg": "Anchor enabled – anchor=gNB-2"}
```

---

## Ping-Pong Detection Criteria

| Criterion | Rule |
|-----------|------|
| **A** | ≥ 3 handovers in any **5-second** window, occurring ≥ **2 times** |
| **B** | ≥ 6 handovers in any **10-second** window |

Cooldown: **10 seconds** per UE after each detection (suppresses repeated alerts).

### What Happens on Detection
1. Euclidean distance from UE's last known `(UE_x, UE_y)` to all candidate gNBs
2. Closest gNB is selected as new Anchor (MeNB)
3. Command sent: `ASSIGN_ANCHOR:UE-5:gNB-2`
4. Simulator switches UE to DC with new anchor

---

## RSRP vs Timestamp Charts

Auto-generated for **every UE that performs a handover**.  
Saved to `handover_charts/` as:  
`UE{UE_ID}_HO_{YYYYMMDD_HHMMSS_mmm}.png`

Chart contents:
- 🔵 Blue line — serving gNB RSRP history
- 🟠 Orange line — target gNB RSRP history
- 🔴 Vertical dashed red line at handover moment
- ⭕ Red dotted circle at serving RSRP value at HO point
- **"HO"** annotation badge

---

## REST API — New Anchor Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/anchor/status` | Current anchor/DC state |
| GET | `/api/anchor/scores` | Per-gNB scoring breakdown |
| GET | `/api/anchor/charts` | List of generated chart PNGs |

---

## Integration into main.js

Add `<AnchorStatusPanel state={state}/>` inside the Sidebar's
**Simulation** section, before the Start/Stop buttons.  
The component is loaded via `anchor_panel.js` (already in `index.html`).

See `static/INTEGRATION_GUIDE.txt` for exact placement instructions.
