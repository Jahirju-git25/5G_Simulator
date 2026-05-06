#!/usr/bin/env python3
"""
pingpong_HO_detection_and_Anchor_assignment.py
===============================================
External script that:
  1. Connects to the 5G NR simulator on TCP port 5555
  2. Receives real-time handover (HO) JSON events
  3. Detects ping-pong handovers (Criterion A or B)
  4. On detection:
       a. Computes the HO-density centroid from recent ping-pong UE positions
       b. Calls REST /api/add_anchor_gnb  →  simulator adds a NEW special-power
          AnchorGNB (AnchorGNB-1, AnchorGNB-2, …) at that position
       c. Sends  ASSIGN_ANCHOR:<UE_ID>:<ANCHOR_GNB_ID>  so the new AnchorGNB
          becomes MeNB; the UE's existing gNB becomes SeNB
  5. Logs everything with ANSI colour

Anchor gNB characteristics (enforced in REST endpoint):
  - TX power   : 50 dBm  (vs 43 dBm for normal gNBs)
  - 6 sectors  (vs 3)
  - Tagged as  anchor=True  so GUI renders it distinctly

Usage
-----
    python pingpong_HO_detection_and_Anchor_assignment.py [--host HOST] [--port PORT]
    Default host = 127.0.0.1, TCP port = 5555, REST port = 8080
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
import threading
import urllib.request
import urllib.error
from collections import defaultdict, deque
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ─── ANSI colours ────────────────────────────────────────────────────────────
try:
    import colorama
    colorama.init(autoreset=True)
    C_RED    = colorama.Fore.RED    + colorama.Style.BRIGHT
    C_YELLOW = colorama.Fore.YELLOW + colorama.Style.BRIGHT
    C_GREEN  = colorama.Fore.GREEN  + colorama.Style.BRIGHT
    C_CYAN   = colorama.Fore.CYAN
    C_BLUE   = colorama.Fore.BLUE   + colorama.Style.BRIGHT
    C_MAGENTA= colorama.Fore.MAGENTA+ colorama.Style.BRIGHT
    C_RESET  = colorama.Style.RESET_ALL
except ImportError:
    C_RED=C_YELLOW=C_GREEN=C_CYAN=C_BLUE=C_MAGENTA=C_RESET=""


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def _log(level: str, msg: str):
    colours = {"INFO":C_CYAN,"WARN":C_YELLOW,"ALERT":C_RED,"OK":C_GREEN,"ANCHOR":C_MAGENTA}
    col = colours.get(level, "")
    print(f"{C_BLUE}[{_ts()}]{C_RESET} {col}[{level}]{C_RESET} {msg}", flush=True)


# ─── Ping-Pong Detector ───────────────────────────────────────────────────────

class PingPongDetector:
    """
    Per-UE HO history; fires callback on Criterion A or B.

    Criterion A : ≥3 HOs in any 5-s window, occurring ≥2 times
    Criterion B : ≥6 HOs in any 10-s window
    Cooldown    : 10 s per UE after each alert
    """
    WINDOW_A_SEC = 5.0;  THRESHOLD_A = 3;  REPEATS_A = 2
    WINDOW_B_SEC = 10.0; THRESHOLD_B = 6
    COOLDOWN_SEC = 10.0

    def __init__(self, on_pingpong_detected):
        self._callback    = on_pingpong_detected
        self._lock        = threading.Lock()
        self._ho_history:  Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._crit_a_fires:Dict[str, int]   = defaultdict(int)
        self._last_alert:  Dict[str, float] = {}

    def record_ho(self, event: dict):
        ue_id    = str(event.get("UE_ID", ""))
        sim_time = float(event.get("sim_time_s", 0.0))
        with self._lock:
            self._ho_history[ue_id].append(event)
            self._evaluate(ue_id, sim_time)

    def _in_cooldown(self, ue_id, t):
        return (t - self._last_alert.get(ue_id, -999.0)) < self.COOLDOWN_SEC

    def _evaluate(self, ue_id, sim_time):
        if self._in_cooldown(ue_id, sim_time):
            return
        history = list(self._ho_history[ue_id])

        # Criterion B
        wb = [h for h in history if sim_time - float(h.get("sim_time_s",0)) <= self.WINDOW_B_SEC]
        if len(wb) >= self.THRESHOLD_B:
            self._trigger(ue_id, wb, sim_time, "B"); return

        # Criterion A
        wa = [h for h in history if sim_time - float(h.get("sim_time_s",0)) <= self.WINDOW_A_SEC]
        if len(wa) >= self.THRESHOLD_A:
            self._crit_a_fires[ue_id] += 1
            if self._crit_a_fires[ue_id] >= self.REPEATS_A:
                self._trigger(ue_id, wa, sim_time, "A")
                self._crit_a_fires[ue_id] = 0

    def _trigger(self, ue_id, ho_list, sim_time, criterion):
        self._last_alert[ue_id] = sim_time
        threading.Thread(target=self._callback,
                         args=(ue_id, ho_list, criterion), daemon=True).start()


# ─── Main class ───────────────────────────────────────────────────────────────

class PingPongAnchorAssigner:
    """
    TCP client + REST caller.
    On ping-pong detection:
      1.  Compute HO-density centroid → REST POST /api/add_anchor_gnb
          → simulator creates AnchorGNB-N with TX=50 dBm, 6 sectors
      2.  TCP  ASSIGN_ANCHOR:<UE_ID>:<ANCHOR_GNB_ID>
          → new AnchorGNB becomes MeNB; existing gNB becomes SeNB
    """
    RECONNECT_DELAY = 3.0

    def __init__(self, host="127.0.0.1", tcp_port=5555, rest_port=8080):
        self.host      = host
        self.tcp_port  = tcp_port
        self.rest_port = rest_port

        self._sock: Optional[socket.socket] = None
        self._running  = False
        self._sock_lock = threading.Lock()

        # gNB canvas positions:  str key ("gNB-3") and int key (3) both stored
        self._gnb_positions: Dict = {}

        # Track placed anchor gNBs: ue_id → anchor_gnb_id string
        self._ue_anchor_map: Dict[str, str] = {}

        # anchor counter (for display)
        self._anchor_count = 0
        self._anchor_lock  = threading.Lock()

        self.detector = PingPongDetector(on_pingpong_detected=self._on_pingpong_detected)

        self._total_ho       = 0
        self._total_pp       = 0
        self._total_anchors  = 0

    # ── connection ────────────────────────────────────────────────────────

    def run(self):
        self._running = True
        _log("INFO", f"Connecting to {self.host}:{self.tcp_port} …")
        while self._running:
            try:
                self._connect_and_read()
            except KeyboardInterrupt:
                self._running = False; break
            except Exception as e:
                _log("WARN", f"Connection error: {e}")
            if self._running:
                _log("WARN", f"Reconnecting in {self.RECONNECT_DELAY}s …")
                time.sleep(self.RECONNECT_DELAY)

    def _connect_and_read(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((self.host, self.tcp_port))
        sock.settimeout(None)
        with self._sock_lock:
            self._sock = sock
        _log("OK", f"Connected to {self.host}:{self.tcp_port}")
        _log("INFO", "Listening for handover events …\n")
        buf = ""
        try:
            while self._running:
                chunk = sock.recv(4096).decode("utf-8", errors="replace")
                if not chunk:
                    raise ConnectionError("Server closed connection")
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._handle_message(line)
        finally:
            try: sock.close()
            except OSError: pass
            with self._sock_lock:
                self._sock = None

    def _send(self, msg: str):
        with self._sock_lock:
            if self._sock is None:
                _log("WARN", f"Cannot send (disconnected): {msg}"); return
            try:
                self._sock.sendall((msg + "\n").encode("utf-8"))
            except OSError as e:
                _log("WARN", f"Send error: {e}")

    # ── message parsing ───────────────────────────────────────────────────

    def _handle_message(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            _log("WARN", f"Non-JSON: {raw[:80]}"); return

        if data.get("cmd") == "STATUS":
            self._process_status(data); return
        if data.get("cmd") in ("ACK", "ERR"):
            col = C_GREEN if data.get("ok") else C_RED
            _log("INFO", f"ACK: {col}{data.get('msg','')}{C_RESET}"); return
        if "UE_ID" in data and "serving_gnb" in data:
            self._process_ho_event(data); return

    def _process_status(self, data: dict):
        _log("INFO",
             f"Status — anchor_enabled={data.get('anchor_enabled')}  "
             f"anchor_gnb={data.get('anchor_gnb_id')}  "
             f"TCP_clients={data.get('connected_tcp_clients')}")

    def _process_ho_event(self, data: dict):
        self._total_ho += 1
        ue_id = data["UE_ID"]
        srv   = data.get("serving_gnb")
        tgt   = data.get("target_gnb")
        rsrp  = data.get("RSRP_dBm", 0.0)
        ue_x  = data.get("UE_x", 0.0)
        ue_y  = data.get("UE_y", 0.0)
        sim_t = data.get("sim_time_s", 0.0)
        _log("INFO",
             f"HO #{self._total_ho:04d} | "
             f"{C_GREEN}UE-{ue_id}{C_RESET} | "
             f"{C_YELLOW}gNB-{srv}{C_RESET}→{C_CYAN}gNB-{tgt}{C_RESET} | "
             f"RSRP={rsrp:.1f}dBm pos=({ue_x:.0f},{ue_y:.0f}) t={sim_t:.2f}s")
        self.detector.record_ho(data)

    # ── ping-pong callback ────────────────────────────────────────────────

    def _on_pingpong_detected(self, ue_id: str, ho_list: list, criterion: str):
        self._total_pp += 1
        last_ho = ho_list[-1]
        sim_t   = float(last_ho.get("sim_time_s", 0.0))

        # Collect UE positions from ping-pong window
        positions = [(float(h.get("UE_x", 0)), float(h.get("UE_y", 0))) for h in ho_list]
        centroid_x = sum(p[0] for p in positions) / len(positions)
        centroid_y = sum(p[1] for p in positions) / len(positions)

        # Spread / density radius
        spread = max(
            math.sqrt((p[0]-centroid_x)**2 + (p[1]-centroid_y)**2)
            for p in positions
        ) if len(positions) > 1 else 50.0
        density_radius = max(spread, 40.0)

        print()
        _log("ALERT",
             f"{'─'*62}\n"
             f"         ⚠  PING-PONG DETECTED  ⚠\n"
             f"         UE        : {C_GREEN}UE-{ue_id}{C_RESET}\n"
             f"         Criterion : {criterion}  |  HOs in window: {len(ho_list)}\n"
             f"         Sim time  : {sim_t:.2f}s\n"
             f"         HO-density centroid: ({centroid_x:.1f}, {centroid_y:.1f}) px\n"
             f"         Spread radius: {density_radius:.1f} px\n"
             f"{'─'*62}")

        # ── 1. Add new AnchorGNB via REST ──────────────────────────────────
        anchor_gnb_id = self._add_anchor_gnb(centroid_x, centroid_y, ue_id, ho_list)
        if anchor_gnb_id is None:
            _log("WARN", "Failed to create AnchorGNB — skipping assignment.")
            return

        # ── 2. ASSIGN_ANCHOR via TCP ───────────────────────────────────────
        cmd = f"ASSIGN_ANCHOR:{ue_id}:{anchor_gnb_id}"
        _log("ANCHOR", f"Sending: {C_GREEN}{cmd}{C_RESET}")
        self._send(cmd)
        self._total_anchors += 1

        with self._anchor_lock:
            self._ue_anchor_map[str(ue_id)] = anchor_gnb_id

        _log("INFO",
             f"Session stats — HOs: {self._total_ho}  |  "
             f"PP detected: {self._total_pp}  |  "
             f"Anchors placed: {self._total_anchors}\n")

    # ── REST: add new AnchorGNB ───────────────────────────────────────────

    def _add_anchor_gnb(self, x: float, y: float,
                        ue_id: str, ho_list: list) -> Optional[str]:
        """
        POST /api/add_anchor_gnb
        Payload:
          x, y           — canvas position (HO-density centroid)
          tx_power       — 50 dBm  (special-power anchor)
          num_sectors    — 6
          is_anchor      — True  (GUI renders differently)
          triggered_by   — ue_id
          ho_count       — number of HOs that triggered this

        Returns the new gNB id string, e.g. "AnchorGNB-1", or None on failure.
        """
        gnb_ids_before = set(self._fetch_gnb_positions().keys())

        payload = json.dumps({
            "x":           round(x, 1),
            "y":           round(y, 1),
            "tx_power":    50,
            "num_sectors": 6,
            "is_anchor":   True,
            "triggered_by": str(ue_id),
            "ho_count":    len(ho_list),
        }).encode("utf-8")

        url = f"http://{self.host}:{self.rest_port}/api/add_anchor_gnb"
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode())
                gnb_id = result.get("gnb_id") or result.get("anchor_gnb_id")
                if gnb_id:
                    # Register its position
                    self.register_gnb_position(gnb_id, x, y)
                    _log("ANCHOR",
                         f"New AnchorGNB created: {C_MAGENTA}{gnb_id}{C_RESET} "
                         f"@ ({x:.0f},{y:.0f})  TX=50dBm  sectors=6")
                    return gnb_id
                _log("WARN", f"add_anchor_gnb response missing gnb_id: {result}")
                return None
        except Exception as e:
            _log("WARN", f"REST add_anchor_gnb failed: {e}")
            # Fallback: use /api/add_gnb with same payload minus is_anchor
            try:
                payload2 = json.dumps({
                    "x": round(x,1), "y": round(y,1),
                    "tx_power": 50, "num_sectors": 6,
                }).encode("utf-8")
                url2 = f"http://{self.host}:{self.rest_port}/api/add_gnb"
                req2 = urllib.request.Request(
                    url2, data=payload2,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req2, timeout=5) as resp2:
                    result2 = json.loads(resp2.read().decode())
                    gnb_id2 = result2.get("gnb_id")
                    if gnb_id2:
                        self.register_gnb_position(gnb_id2, x, y)
                        _log("ANCHOR",
                             f"Fallback gNB created: {C_MAGENTA}{gnb_id2}{C_RESET} "
                             f"@ ({x:.0f},{y:.0f})")
                        return gnb_id2
            except Exception as e2:
                _log("WARN", f"Fallback add_gnb also failed: {e2}")
            return None

    # ── REST: gNB position fetch ──────────────────────────────────────────

    def _fetch_gnb_positions(self) -> Dict[str, Tuple[float, float]]:
        url = f"http://{self.host}:{self.rest_port}/api/get_state"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                state = json.loads(resp.read().decode())
                gnbs  = state.get("gnbs", {})
                return {gid: (g["x"], g["y"]) for gid, g in gnbs.items()}
        except Exception as e:
            _log("WARN", f"Fetch gNB positions failed: {e}")
            return {}

    def register_gnb_position(self, gnb_id: str, x: float, y: float):
        self._gnb_positions[gnb_id] = (x, y)
        try:
            int_key = int(str(gnb_id).split("-")[-1])
            self._gnb_positions[int_key] = (x, y)
        except (ValueError, AttributeError):
            pass
        _log("INFO", f"Registered gNB position: {gnb_id} @ ({x:.1f},{y:.1f})")

    # ── background refresh ────────────────────────────────────────────────

    def _refresh_loop(self):
        while self._running:
            time.sleep(8)
            pos = self._fetch_gnb_positions()
            for gid, (x, y) in pos.items():
                self._gnb_positions[gid] = (x, y)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Ping-Pong HO Detection & Dynamic AnchorGNB Placement — 5G NR Simulator")
    parser.add_argument("--host",      default="127.0.0.1")
    parser.add_argument("--port",      type=int, default=5555)
    parser.add_argument("--rest-port", type=int, default=8080)
    args = parser.parse_args()

    print()
    print("=" * 64)
    print("   Ping-Pong HO Detection & Dynamic AnchorGNB Placement")
    print("   5G NR Network Simulator — External Controller")
    print("=" * 64)
    print(f"   TCP target  : {args.host}:{args.port}")
    print(f"   REST target : {args.host}:{args.rest_port}")
    print(f"   Criteria    : A=3HOs/5s×2  |  B=6HOs/10s  |  Cooldown=10s")
    print(f"   AnchorGNB   : TX=50dBm, 6 sectors, placed at HO-density centroid")
    print("=" * 64)
    print()

    assigner = PingPongAnchorAssigner(
        host=args.host, tcp_port=args.port, rest_port=args.rest_port)

    # Pre-load gNB positions
    pos = assigner._fetch_gnb_positions()
    for gid, (x, y) in pos.items():
        assigner.register_gnb_position(gid, x, y)
    if pos:
        _log("OK", f"Pre-loaded {len(pos)} gNB positions from REST API.")
    else:
        _log("WARN", "No gNB positions pre-loaded — will fetch on demand.")

    # Background refresh
    threading.Thread(target=assigner._refresh_loop, daemon=True).start()

    try:
        assigner.run()
    except KeyboardInterrupt:
        pass
    finally:
        print()
        _log("INFO",
             f"Shutdown — HOs received: {assigner._total_ho}  |  "
             f"PP detected: {assigner._total_pp}  |  "
             f"AnchorGNBs placed: {assigner._total_anchors}")


if __name__ == "__main__":
    main()
