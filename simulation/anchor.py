"""
simulation/anchor.py
====================
Local Anchor-based Dual Connectivity (DC) Module — deadlock-free design.

New in this version
-------------------
  • AnchorManager supports EXTERNALLY-PLACED AnchorGNBs (added by the
    ping-pong detector script via REST /api/add_anchor_gnb).
  • Anchor gNBs are tracked in self.anchor_gnb_ids (set).
  • assign_dc_with_anchor(ue_id, anchor_gnb_id, senb_id) lets the external
    script specify both MeNB (the new AnchorGNB) and SeNB (the existing gNB
    the UE was ping-ponging with).
  • get_status_dict() now returns anchor_gnb_ids list for GUI rendering.

Locking rules (unchanged)
-------------------------
  sim.lock      : RLock; held during each sim step
  anchor._lock  : RLock; brief anchor-state mutations only
  GOLDEN RULE: always acquire sim.lock BEFORE anchor._lock.
  step_update() is called OUTSIDE sim.lock.
"""

from __future__ import annotations

import json
import math
import os
import socket
import threading
from collections import defaultdict, deque
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _MATPLOTLIB_OK = True
    _MATPLOTLIB_LOCK = threading.Lock()  # Protect matplotlib operations across threads
except ImportError:
    _MATPLOTLIB_OK = False
    _MATPLOTLIB_LOCK = None

if TYPE_CHECKING:
    from .simulator import NetworkSimulator

TCP_PORT            = 5555
CHART_DIR           = "handover_charts"
MAX_RSRP_HISTORY    = 300
RSRP_HISTORY_WINDOW = 120

ANCHOR_SCORE_WEIGHTS = {
    "tx_power":   0.30,
    "centrality": 0.30,
    "stability":  0.20,
    "load_cap":   0.20,
}


def _id_to_int(node_id: str) -> int:
    try:
        digits = "".join(ch for ch in str(node_id).split("-")[-1] if ch.isdigit())
        return int(digits) if digits else 0
    except (ValueError, AttributeError):
        return 0


class AnchorManager:

    def __init__(self, simulator: "NetworkSimulator"):
        self.sim   = simulator
        self._lock = threading.RLock()

        self.enabled: bool = False
        self.anchor_gnb_id: Optional[str] = None

        # ALL anchor gNBs ever placed (including externally-added AnchorGNB-N)
        self.anchor_gnb_ids: Set[str] = set()

        self.ue_dc_state: Dict[str, Dict[str, Optional[str]]] = {}

        self.rsrp_history: Dict[str, Dict[str, deque]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=MAX_RSRP_HISTORY))
        )
        self._chart_queue: List[dict] = []

        self._clients: List[socket.socket] = []
        self._server_sock: Optional[socket.socket] = None
        self._tcp_running = False

        self._int_to_ue_id:  Dict[int, str] = {}
        self._int_to_gnb_id: Dict[int, str] = {}

        self._anchor_scores: Dict[str, float] = {}

        os.makedirs(CHART_DIR, exist_ok=True)

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self):
        self._tcp_running = True
        threading.Thread(target=self._tcp_server_thread,
                         daemon=True, name="AnchorTCPServer").start()

    def stop(self):
        self._tcp_running = False
        if self._server_sock:
            try: self._server_sock.close()
            except OSError: pass
        with self._lock:
            for c in list(self._clients):
                try: c.close()
                except OSError: pass
            self._clients.clear()

    # ── enable / disable ────────────────────────────────────────────────

    def enable(self):
        with self.sim.lock:
            gnb_ids = list(self.sim.gnbs.keys())
            ue_ids  = list(self.sim.ues.keys())
        if not gnb_ids:
            return False, "No gNBs available"
        with self._lock:
            self.enabled = True
            self._elect_anchor(gnb_ids)
            for uid in ue_ids:
                self._assign_dc(uid)
        self.sim._log_event(f"[ANCHOR] ENABLED – anchor={self.anchor_gnb_id}")
        self._push_status_async()
        return True, f"Anchor enabled – anchor={self.anchor_gnb_id}"

    def disable(self):
        with self._lock:
            self.enabled = False
            self.anchor_gnb_id = None
            self.ue_dc_state.clear()
        with self.sim.lock:
            for ue in self.sim.ues.values():
                ue.dc_enabled = False
                ue.anchor_gnb_id = None
                ue.secondary_gnb_id = None
                ue.dc_throughput = 0.0
        self.sim._log_event("[ANCHOR] DISABLED")
        self._push_status_async()
        return True, "Anchor disabled"

    # ── anchor election (from existing gNBs) ────────────────────────────

    def _elect_anchor(self, gnb_ids: List[str]):
        """Must hold self._lock. Reads sim.gnbs (safe)."""
        gnbs = [self.sim.gnbs[g] for g in gnb_ids if g in self.sim.gnbs]
        if not gnbs:
            return
        tx_powers = [g.tx_power_dbm for g in gnbs]
        cx = sum(g.x for g in gnbs) / len(gnbs)
        cy = sum(g.y for g in gnbs) / len(gnbs)
        distances = [math.sqrt((g.x-cx)**2 + (g.y-cy)**2) for g in gnbs]
        loads     = [len(g.connected_ues) for g in gnbs]

        def _norm(vals, invert=False):
            lo, hi = min(vals), max(vals)
            if hi == lo: return [1.0]*len(vals)
            n = [(v-lo)/(hi-lo) for v in vals]
            return [1-x for x in n] if invert else n

        w = ANCHOR_SCORE_WEIGHTS
        scores = {}
        for i, gnb in enumerate(gnbs):
            scores[gnb.id] = (
                w["tx_power"]   * _norm(tx_powers)[i] +
                w["centrality"] * _norm(distances, invert=True)[i] +
                w["stability"]  * 1.0 +
                w["load_cap"]   * _norm(loads, invert=True)[i]
            )
        self._anchor_scores   = scores
        self.anchor_gnb_id    = max(scores, key=scores.get)
        self.anchor_gnb_ids.add(self.anchor_gnb_id)

    # ── DC assignment helpers ────────────────────────────────────────────

    def _assign_dc(self, ue_id: str):
        """Hold self._lock before calling."""
        ue = self.sim.ues.get(ue_id)
        if ue is None or self.anchor_gnb_id is None:
            return
        menb = self.anchor_gnb_id
        senb = self._pick_senb(ue, menb)
        self.ue_dc_state[ue_id] = {"menb": menb, "senb": senb}
        ue.dc_enabled       = True
        ue.anchor_gnb_id    = menb
        ue.secondary_gnb_id = senb

    def _pick_senb(self, ue, exclude: str) -> Optional[str]:
        best_id, best_rsrp = None, -999.0
        for gnb in self.sim.gnbs.values():
            if gnb.id == exclude:
                continue
            dist_m = math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)*self.sim.PIXEL_TO_METER
            try:
                pl, _ = self.sim.channel_model.calculate_pathloss(dist_m, gnb.height)
            except Exception:
                continue
            rsrp = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl
            if rsrp > best_rsrp:
                best_rsrp = rsrp; best_id = gnb.id
        return best_id

    def assign_dc_for_new_ue(self, ue_id: str):
        if not self.enabled:
            return
        with self._lock:
            self._assign_dc(ue_id)

    # ── NEW: assign DC using an externally-placed AnchorGNB ─────────────

    def assign_dc_with_external_anchor(
            self, ue_id: str, anchor_gnb_id: str,
            preferred_senb_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Called after the external script places a new AnchorGNB and sends
        ASSIGN_ANCHOR:<ue_id>:<anchor_gnb_id>.

        anchor_gnb_id   — the new AnchorGNB-N id (MeNB)
        preferred_senb_id — the gNB the UE was ping-ponging with (SeNB);
                            if None, best RSRP non-anchor is picked
        Lock order: sim.lock → anchor._lock.
        """
        with self.sim.lock:
            if anchor_gnb_id not in self.sim.gnbs:
                return False, f"AnchorGNB {anchor_gnb_id} not found in sim"
            if ue_id not in self.sim.ues:
                return False, f"UE {ue_id} not found"

            with self._lock:
                self.enabled       = True
                self.anchor_gnb_id = anchor_gnb_id
                self.anchor_gnb_ids.add(anchor_gnb_id)

                ue = self.sim.ues[ue_id]
                senb = preferred_senb_id if (
                    preferred_senb_id and preferred_senb_id in self.sim.gnbs
                ) else self._pick_senb(ue, anchor_gnb_id)

                self.ue_dc_state[ue_id] = {"menb": anchor_gnb_id, "senb": senb}
                ue.dc_enabled       = True
                ue.anchor_gnb_id    = anchor_gnb_id
                ue.secondary_gnb_id = senb
                ue.serving_gnb_id   = anchor_gnb_id  # primary link → anchor

                # Ensure UE is in anchor's connected_ues list
                anchor_gnb = self.sim.gnbs[anchor_gnb_id]
                if ue_id not in anchor_gnb.connected_ues:
                    anchor_gnb.connected_ues.append(ue_id)

        msg = (f"[ANCHOR] DC assigned: {ue_id} MeNB={anchor_gnb_id} SeNB={senb}")
        self.sim._log_event(msg)
        self._push_status_async()
        return True, msg

    def force_assign_anchor(self, ue_id: str, anchor_gnb_id: str) -> Tuple[bool, str]:
        """
        TCP command: ASSIGN_ANCHOR:<ue_id>:<anchor_gnb_id>
        Delegates to assign_dc_with_external_anchor if anchor_gnb_id is an
        AnchorGNB-N, otherwise falls back to legacy force-assign.
        Lock order: sim.lock → anchor._lock.
        """
        return self.assign_dc_with_external_anchor(ue_id, anchor_gnb_id)

    # ── per-step update (OUTSIDE sim.lock) ──────────────────────────────

    def step_update(self, sim_time: float, ues_snap: dict, gnbs_snap: dict):
        with self._lock:
            if not self.enabled:
                pending = list(self._chart_queue)
                self._chart_queue.clear()
            else:
                pending = list(self._chart_queue)
                self._chart_queue.clear()

        for ue_id, ue in ues_snap.items():
            for gnb_id, gnb in gnbs_snap.items():
                dist_m = (math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)
                          * self.sim.PIXEL_TO_METER)
                try:
                    pl, _ = self.sim.channel_model.calculate_pathloss(dist_m, gnb.height)
                except Exception:
                    continue
                rsrp = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl
                self.rsrp_history[ue_id][gnb_id].append((sim_time, rsrp))

            with self._lock:
                dc = dict(self.ue_dc_state.get(ue_id, {}))

            if self.enabled:
                if dc:
                    new_senb = self._pick_senb_snap(ue, dc.get("menb",""), gnbs_snap)
                    if new_senb and new_senb != dc.get("senb"):
                        with self._lock:
                            if ue_id in self.ue_dc_state:
                                self.ue_dc_state[ue_id]["senb"] = new_senb
                        ue.secondary_gnb_id = new_senb
                else:
                    with self._lock:
                        self._assign_dc(ue_id)

        for req in pending:
            threading.Thread(target=self._generate_ho_chart,
                             kwargs=req, daemon=True).start()

    def _pick_senb_snap(self, ue, exclude: str, gnbs_snap: dict) -> Optional[str]:
        best_id, best_rsrp = None, -999.0
        for gnb in gnbs_snap.values():
            if gnb.id == exclude:
                continue
            dist_m = math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)*self.sim.PIXEL_TO_METER
            try:
                pl, _ = self.sim.channel_model.calculate_pathloss(dist_m, gnb.height)
            except Exception:
                continue
            rsrp = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl
            if rsrp > best_rsrp:
                best_rsrp = rsrp; best_id = gnb.id
        return best_id

    def queue_ho_chart(self, ue_id, serving_gnb_id, target_gnb_id, ho_time):
        with self._lock:
            self._chart_queue.append({
                "ue_id": ue_id, "serving_gnb_id": serving_gnb_id,
                "target_gnb_id": target_gnb_id, "ho_time": ho_time,
                "queued_at": datetime.now(),
            })

    # ── RSRP chart ───────────────────────────────────────────────────────

    def _generate_ho_chart(self, ue_id, serving_gnb_id, target_gnb_id,
                           ho_time, queued_at):
        """Generate HO RSRP vs Time chart (threadsafe)."""
        if not _MATPLOTLIB_OK:
            return
        
        try:
            with self._lock:
                if ue_id not in self.rsrp_history:
                    return
                serving_gnb_id = str(serving_gnb_id); target_gnb_id = str(target_gnb_id)
                srv_h = list(self.rsrp_history[ue_id].get(serving_gnb_id, []))
                tgt_h = list(self.rsrp_history[ue_id].get(target_gnb_id, []))
            
            if not srv_h or not tgt_h:
                return
            
            srv_h = srv_h[-RSRP_HISTORY_WINDOW:]; tgt_h = tgt_h[-RSRP_HISTORY_WINDOW:]
            st=[p[0] for p in srv_h]; sr=[p[1] for p in srv_h]
            tt=[p[0] for p in tgt_h]; tr=[p[1] for p in tgt_h]

            def _at(times, rsrps, t):
                return rsrps[min(range(len(times)), key=lambda i: abs(times[i]-t))]

            srv_at = _at(st, sr, ho_time)
            
            # Use global matplotlib lock to prevent race conditions
            with _MATPLOTLIB_LOCK:
                # Clean up excessive open figures before creating new one
                import gc
                if len(plt.get_fignums()) > 20:
                    plt.close('all')
                    gc.collect()
                
                fig, ax = plt.subplots(figsize=(10,5))
                fig.patch.set_facecolor("#0d1117"); ax.set_facecolor("#161b22")
                ax.plot(st, sr, color="#58a6ff", linewidth=1.8,
                        label=f"Serving ({serving_gnb_id})", zorder=2)
                ax.plot(tt, tr, color="#f0883e", linewidth=1.8,
                        label=f"Target  ({target_gnb_id})", zorder=2)
                ax.axvline(x=ho_time, color="#f85149", linestyle="--",
                           linewidth=1.4, alpha=0.85, zorder=3)
                ax.plot(ho_time, srv_at, "o", markersize=18,
                        markerfacecolor="none", markeredgecolor="#f85149",
                        markeredgewidth=2.5, zorder=4)
                ax.annotate(" HO", xy=(ho_time, srv_at+2), fontsize=11,
                            color="#f85149", fontweight="bold",
                            bbox=dict(boxstyle="round,pad=0.3", facecolor="#21262d",
                                      edgecolor="#f85149", linewidth=1))
                ax.set_xlabel("Simulation Time (s)", color="#8b949e", fontsize=10)
                ax.set_ylabel("RSRP (dBm)",          color="#8b949e", fontsize=10)
                ax.set_title(f"RSRP vs Time — {ue_id}  |  HO @ t={ho_time:.2f}s\n"
                             f"{serving_gnb_id} → {target_gnb_id}",
                             color="#e6edf3", fontsize=11, fontweight="bold")
                ax.tick_params(colors="#6e7681"); ax.spines[:].set_color("#30363d")
                ax.grid(color="#30363d", linestyle="--", linewidth=0.5, alpha=0.6)
                ax.legend(facecolor="#1c2128", edgecolor="#30363d",
                          labelcolor="#e6edf3", fontsize=9)
                for lvl, lbl, col in [(-80,"−80 dBm (good)","#3fb950"),
                                       (-95,"−95 dBm (fair)","#d29922"),
                                       (-110,"−110 dBm (poor)","#f85149")]:
                    ax.axhline(y=lvl, color=col, linestyle=":", linewidth=0.8, alpha=0.5)
                    if st:
                        ax.text(min(st), lvl+0.5, lbl, color=col, fontsize=7, alpha=0.7)
                plt.tight_layout()
                
                ts_str = queued_at.strftime("%Y%m%d_%H%M%S_%f")[:21]
                fname  = os.path.join(CHART_DIR,
                                      f"{ue_id.replace('-','')}_HO_{ts_str}.png")
                try:
                    fig.savefig(fname, dpi=120, facecolor=fig.get_facecolor())
                except Exception:
                    pass
                finally:
                    plt.close(fig)
                    gc.collect()
        except Exception as e:
            # Silently ignore chart generation errors
            pass

    # ── TCP server ───────────────────────────────────────────────────────

    def _tcp_server_thread(self):
        try:
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind(("0.0.0.0", TCP_PORT))
            self._server_sock.listen(10)
            self._server_sock.settimeout(1.0)
            print(f"[AnchorManager] TCP listening on port {TCP_PORT}")
        except OSError as e:
            print(f"[AnchorManager] Cannot bind port {TCP_PORT}: {e}"); return

        while self._tcp_running:
            try:
                conn, addr = self._server_sock.accept()
                with self._lock:
                    self._clients.append(conn)
                threading.Thread(target=self._client_handler,
                                 args=(conn, addr), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _client_handler(self, conn, addr):
        print(f"[AnchorManager] Client connected: {addr}")
        buf = ""
        try:
            conn.settimeout(5.0)
            while self._tcp_running:
                try:
                    chunk = conn.recv(1024).decode("utf-8", errors="replace")
                    if not chunk: break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._handle_command(line.strip(), conn)
                except socket.timeout:
                    continue
                except (ConnectionResetError, BrokenPipeError):
                    break
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            try: conn.close()
            except OSError: pass
            print(f"[AnchorManager] Client disconnected: {addr}")

    def _handle_command(self, cmd: str, conn: socket.socket):
        if not cmd:
            return
        if cmd == "ENABLE_ANCHOR":
            ok, msg = self.enable()
            self._send_to(conn, {"cmd":"ACK","ok":ok,"msg":msg})
        elif cmd == "DISABLE_ANCHOR":
            ok, msg = self.disable()
            self._send_to(conn, {"cmd":"ACK","ok":ok,"msg":msg})
        elif cmd.startswith("ASSIGN_ANCHOR:"):
            parts = cmd.split(":")
            if len(parts) == 3:
                _, raw_ue, raw_gnb = parts
                uid = self._resolve_ue_id(raw_ue.strip())
                gid = self._resolve_gnb_id(raw_gnb.strip())
                ok, msg = self.force_assign_anchor(uid, gid)
                self._send_to(conn, {"cmd":"ACK","ok":ok,"msg":msg,
                                     "ue_id":uid,"anchor_gnb":gid})
            else:
                self._send_to(conn, {"cmd":"ERR",
                                     "msg":"Format: ASSIGN_ANCHOR:UE_ID:GNB_ID"})
        elif cmd == "GET_STATUS":
            self._send_to(conn, self.get_status_dict())
        else:
            self._send_to(conn, {"cmd":"ERR","msg":f"Unknown: {cmd}"})

    # ── broadcast helpers ────────────────────────────────────────────────

    def broadcast_ho_event(self, ue_id, serving_gnb, target_gnb,
                           rsrp_dbm, ue_x, ue_y, sim_time):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        ui = _id_to_int(ue_id)
        si = _id_to_int(serving_gnb)
        ti = _id_to_int(target_gnb)
        self._int_to_ue_id[ui]  = ue_id
        self._int_to_gnb_id[si] = serving_gnb
        self._int_to_gnb_id[ti] = target_gnb
        payload = {
            "timestamp":   ts,
            "UE_ID":       ui,
            "serving_gnb": si,
            "target_gnb":  ti,
            "RSRP_dBm":    round(rsrp_dbm, 2),
            "UE_x":        round(ue_x, 2),
            "UE_y":        round(ue_y, 2),
            "sim_time_s":  round(sim_time, 3),
        }
        raw = (json.dumps(payload)+"\n").encode("utf-8")
        threading.Thread(target=self._broadcast_raw, args=(raw,), daemon=True).start()

    def _broadcast_raw(self, raw: bytes):
        with self._lock:
            dead = []
            for c in self._clients:
                try: c.sendall(raw)
                except OSError: dead.append(c)
            for c in dead:
                self._clients.remove(c)
                try: c.close()
                except OSError: pass

    def _push_status_async(self):
        sb = (json.dumps(self.get_status_dict())+"\n").encode("utf-8")
        threading.Thread(target=self._broadcast_raw, args=(sb,), daemon=True).start()

    def _send_to(self, conn, obj):
        try: conn.sendall((json.dumps(obj)+"\n").encode("utf-8"))
        except OSError: pass

    # ── ID resolvers ─────────────────────────────────────────────────────

    def _resolve_ue_id(self, raw: str) -> str:
        if raw.lstrip("-").isdigit():
            n = int(raw)
            if n in self._int_to_ue_id:
                return self._int_to_ue_id[n]
            c = f"UE-{n}"; return c if c in self.sim.ues else raw
        return raw

    def _resolve_gnb_id(self, raw: str) -> str:
        if raw.lstrip("-").isdigit():
            n = int(raw)
            if n in self._int_to_gnb_id:
                return self._int_to_gnb_id[n]
            c = f"gNB-{n}"; return c if c in self.sim.gnbs else raw
        # Could be "AnchorGNB-1" style — return as-is if present
        if raw in self.sim.gnbs:
            return raw
        return raw

    # ── DC throughput ────────────────────────────────────────────────────

    def get_dc_throughput(self, ue_id: str) -> float:
        with self._lock:
            dc = dict(self.ue_dc_state.get(ue_id, {}))
        if not dc:
            return 0.0
        ue = self.sim.ues.get(ue_id)
        if ue is None:
            return 0.0
        total = 0.0
        for gnb_id in [dc.get("menb"), dc.get("senb")]:
            if not gnb_id or gnb_id not in self.sim.gnbs:
                continue
            gnb  = self.sim.gnbs[gnb_id]
            dist = math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)*self.sim.PIXEL_TO_METER
            try:
                pl, _ = self.sim.channel_model.calculate_pathloss(dist, gnb.height)
            except Exception:
                continue
            rsrp = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl
            interf = []
            for o in self.sim.gnbs.values():
                if o.id == gnb_id: continue
                d2 = math.sqrt((ue.x-o.x)**2+(ue.y-o.y)**2)*self.sim.PIXEL_TO_METER
                try:
                    ipl, _ = self.sim.channel_model.calculate_pathloss(d2, o.height)
                except Exception:
                    continue
                interf.append(o.tx_power_dbm + o.get_sector_gain(ue.x, ue.y) - ipl)
            sinr = self.sim.channel_model.calculate_sinr(rsrp, interf)
            tp, _, _ = self.sim.channel_model.calculate_throughput(sinr)
            total += tp
        return total

    # ── status dict ──────────────────────────────────────────────────────

    def get_status_dict(self) -> dict:
        with self._lock:
            return {
                "cmd":             "STATUS",
                "anchor_enabled":  self.enabled,
                "anchor_gnb_id":   self.anchor_gnb_id,
                "anchor_gnb_ids":  list(self.anchor_gnb_ids),
                "ue_dc_state":     dict(self.ue_dc_state),
                "anchor_scores":   {k: round(v,4) for k,v in self._anchor_scores.items()},
                "connected_tcp_clients": len(self._clients),
            }
