"""
5G NR Network Simulator Engine
================================
Key design fixes vs previous version:
  • sim.lock is a threading.RLock (allows re-entry from REST while step runs)
  • anchor.step_update() called OUTSIDE sim.lock → no lock inversion
  • _cached_state updated each step; get_state() returns the cache
    → SSE stream never competes with the sim loop for sim.lock
  • Zero debug print statements in the hot path
  • add_anchor_gnb() creates special-power AnchorGNB-N nodes (TX=50 dBm,
    6 sectors, is_anchor=True) for the external ping-pong detector script
"""
import math
import time
import threading
import copy
from .gnb import gNB
from .ue import UE
from .channel import ChannelModel
from .scheduler import Scheduler
from .anchor import AnchorManager


class NetworkSimulator:

    PIXEL_TO_METER = 5.0
    CANVAS_WIDTH   = 800
    CANVAS_HEIGHT  = 600

    def __init__(self):
        self.gnbs = {}
        self.ues  = {}

        self.scenario      = 'UMa'
        self.channel_model = ChannelModel(scenario='UMa')
        self.scheduler     = Scheduler()

        self.running       = False
        self.step          = 0
        self.sim_time      = 0.0
        self.step_duration = 0.1
        self.speed_factor  = 1.0

        self.handover_events = []
        self.event_log       = []
        self.metrics_history = []

        self.total_handovers        = 0
        self.packet_loss_rate       = 0
        self.cumulative_throughput  = 0.0
        self.avg_throughput_overall = 0.0

        self.hysteresis_db = 3.0
        self.ttt_steps     = 3

        self.lock = threading.RLock()

        self._state_cache      = {}
        self._state_cache_lock = threading.Lock()

        self.sim_thread = None

        self.anchor_manager = AnchorManager(self)
        self.anchor_manager.start()

    # ── channel config ───────────────────────────────────────────────────

    def set_scenario(self, scenario):
        with self.lock:
            self.scenario = scenario
            self.channel_model = ChannelModel(
                scenario        = scenario,
                pathloss_model  = self.channel_model.pathloss_model,
                log_dist_n      = self.channel_model.log_dist_n,
                log_dist_shadow = self.channel_model.log_dist_shadow,
                fading_model    = self.channel_model.fading_model,
            )
            for gnb in self.gnbs.values():
                gnb.height = {'UMa':25,'UMi':10,'RMa':35}.get(scenario, 25)
            self._log_event(f"Scenario changed to {scenario}")

    def set_channel_config(self, pathloss_model=None, scenario=None,
                           log_dist_n=None, log_dist_shadow=None,
                           fading_model=None):
        with self.lock:
            pm  = pathloss_model  if pathloss_model  is not None else self.channel_model.pathloss_model
            sc  = scenario        if scenario         is not None else self.channel_model.scenario
            ldn = log_dist_n      if log_dist_n       is not None else self.channel_model.log_dist_n
            lds = log_dist_shadow if log_dist_shadow  is not None else self.channel_model.log_dist_shadow
            fm  = fading_model    if fading_model     is not None else self.channel_model.fading_model
            self.scenario      = sc
            self.channel_model = ChannelModel(scenario=sc, pathloss_model=pm,
                                              log_dist_n=ldn, log_dist_shadow=lds,
                                              fading_model=fm)
            label = f"3GPP·{sc}" if pm=='3GPP' else f"LogDist·n={ldn:.1f}"
            self._log_event(f"Channel: {label} fading={fm}")

    # ── node management ──────────────────────────────────────────────────

    def add_gnb(self, x, y, tx_power=43, num_sectors=3):
        with self.lock:
            gnb = gNB(x, y, tx_power_dbm=tx_power, num_sectors=num_sectors)
            gnb.height = {'UMa':25,'UMi':10,'RMa':35}.get(self.scenario, 25)
            gnb.is_anchor = False
            for existing in self.gnbs.values():
                gnb.add_neighbor(existing)
                existing.add_neighbor(gnb)
            self.gnbs[gnb.id] = gnb
            self._log_event(f"Added {gnb.id} at ({x:.0f},{y:.0f})")
            return gnb.id

    def add_anchor_gnb(self, x, y, tx_power=50, num_sectors=6, is_anchor=True):
        """
        Add a special-power AnchorGNB node placed by the external ping-pong
        detector. Uses a dedicated counter and naming: AnchorGNB-1, AnchorGNB-2 …
        TX power defaults to 50 dBm, 6 sectors for maximum coverage.
        """
        with self.lock:
            gnb = gNB(x, y, tx_power_dbm=tx_power, num_sectors=num_sectors)
            # Override auto-assigned id with AnchorGNB naming
            anchor_count = sum(1 for g in self.gnbs.values()
                               if getattr(g, 'is_anchor', False)) + 1
            gnb.id       = f"AnchorGNB-{anchor_count}"
            gnb.height   = {'UMa':30,'UMi':15,'RMa':40}.get(self.scenario, 30)
            gnb.is_anchor = True   # flag for GUI rendering

            # Wider beam: reduce height penalty to give further reach
            gnb.antenna_gain_db = 18   # vs 15 for normal gNBs

            for existing in self.gnbs.values():
                gnb.add_neighbor(existing)
                existing.add_neighbor(gnb)
            self.gnbs[gnb.id] = gnb

            # Track in anchor manager
            with self.anchor_manager._lock:
                self.anchor_manager.anchor_gnb_ids.add(gnb.id)

            self._log_event(
                f"[AnchorGNB] {gnb.id} placed @ ({x:.0f},{y:.0f}) "
                f"TX={tx_power}dBm gain={gnb.antenna_gain_db}dBi sctrs={num_sectors}")
            return gnb.id

    def add_ue(self, x, y, mobility='none', speed=3.0):
        with self.lock:
            ue = UE(x, y, mobility_model=mobility, speed=speed,
                    bounds=(10,10,self.CANVAS_WIDTH-10,self.CANVAS_HEIGHT-10))
            self.ues[ue.id] = ue
            if self.gnbs:
                self._attach_ue(ue)
            self.anchor_manager.assign_dc_for_new_ue(ue.id)
            self._log_event(f"Added {ue.id} at ({x:.0f},{y:.0f}) [{mobility}]")
            return ue.id

    def remove_gnb(self, gnb_id):
        with self.lock:
            if gnb_id in self.gnbs:
                del self.gnbs[gnb_id]
                for ue in self.ues.values():
                    if ue.serving_gnb_id == gnb_id:
                        self._attach_ue(ue)

    def remove_ue(self, ue_id):
        with self.lock:
            if ue_id in self.ues:
                del self.ues[ue_id]
                with self.anchor_manager._lock:
                    self.anchor_manager.ue_dc_state.pop(ue_id, None)

    def _attach_ue(self, ue):
        if not self.gnbs:
            ue.serving_gnb_id = None; return
        best_gnb, best_rsrp = None, -200.0
        for gnb in self.gnbs.values():
            dist_m = math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)*self.PIXEL_TO_METER
            try:
                pl, _ = self.channel_model.calculate_pathloss(dist_m, gnb.height)
            except Exception:
                continue
            rsrp = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl
            if rsrp > best_rsrp:
                best_rsrp = rsrp; best_gnb = gnb
        if best_gnb:
            ue.serving_gnb_id = best_gnb.id
            if ue.id not in best_gnb.connected_ues:
                best_gnb.connected_ues.append(ue.id)

    # ── simulation loop ───────────────────────────────────────────────────

    def start(self):
        if not self.running:
            self.running               = True
            self.step                  = 0
            self.sim_time              = 0.0
            self.cumulative_throughput = 0.0
            self.avg_throughput_overall= 0.0
            self.sim_thread = threading.Thread(
                target=self._simulation_loop, daemon=True, name="SimLoop")
            self.sim_thread.start()
            self._log_event("Simulation started")

    def stop(self):
        self.running = False
        self._log_event("Simulation stopped")
        # Force immediate state cache update so get_state() reflects the stop
        state = self._build_state_dict()
        with self._state_cache_lock:
            self._state_cache = state

    def simulate_step(self):
        with self.lock:
            self._execute_step()
        self._after_step()

    def _simulation_loop(self):
        while self.running:
            t0 = time.perf_counter()
            with self.lock:
                self._execute_step()
            self._after_step()
            elapsed = time.perf_counter() - t0
            wait = (self.step_duration / max(self.speed_factor, 0.1)) - elapsed
            if wait > 0:
                time.sleep(wait)

    def _execute_step(self):
        self.step    += 1
        self.sim_time = round(self.step * self.step_duration, 2)
        if not self.ues or not self.gnbs:
            self._collect_metrics(); return
        for ue in self.ues.values():
            ue.update_position(self.step_duration)
        for ue in self.ues.values():
            if not ue.serving_gnb_id or ue.serving_gnb_id not in self.gnbs:
                self._attach_ue(ue)
            self._calc_ue_metrics(ue)
        for ue in self.ues.values():
            self._check_handover(ue)
        for gnb in self.gnbs.values():
            gnb.total_throughput = sum(
                self.ues[uid].throughput
                for uid in gnb.connected_ues if uid in self.ues
            )
        self._collect_metrics()

    def _after_step(self):
        with self.lock:
            sim_time  = self.sim_time
            ues_snap  = dict(self.ues)
            gnbs_snap = dict(self.gnbs)
        state = self._build_state_dict()
        with self._state_cache_lock:
            self._state_cache = state
        self.anchor_manager.step_update(sim_time, ues_snap, gnbs_snap)

    # ── per-UE metrics ────────────────────────────────────────────────────

    def _calc_ue_metrics(self, ue):
        if not ue.serving_gnb_id or ue.serving_gnb_id not in self.gnbs:
            return
        gnb    = self.gnbs[ue.serving_gnb_id]
        dist_m = math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)*self.PIXEL_TO_METER
        ue.distance = dist_m
        try:
            pl, _ = self.channel_model.calculate_pathloss(dist_m, gnb.height)
        except Exception:
            return
        ue.pathloss = pl
        rsrp = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl
        interf = []
        for o in self.gnbs.values():
            if o.id == ue.serving_gnb_id: continue
            d_m = math.sqrt((ue.x-o.x)**2+(ue.y-o.y)**2)*self.PIXEL_TO_METER
            try:
                ipl, _ = self.channel_model.calculate_pathloss(d_m, o.height)
            except Exception:
                continue
            interf.append(o.tx_power_dbm + o.get_sector_gain(ue.x, ue.y) - ipl)
        sinr           = self.channel_model.calculate_sinr(rsrp, interf)
        tp, _, mod     = self.channel_model.calculate_throughput(sinr)
        ue.modulation  = mod
        vel = ue.get_velocity() * self.PIXEL_TO_METER
        if vel > 30:
            tp *= max(0.7, 1.0 - vel/300)
        if ue.dc_enabled and self.anchor_manager.enabled:
            dc_tp = self.anchor_manager.get_dc_throughput(ue.id)
            ue.dc_throughput = round(dc_tp, 2)
            tp = min(dc_tp, 1000.0)
        else:
            ue.dc_throughput = 0.0
        ue.update_measurements(rsrp, sinr, tp, pl, dist_m)

    # ── handover logic ────────────────────────────────────────────────────

    def _check_handover(self, ue):
        if not ue.serving_gnb_id or len(self.gnbs) < 2:
            return
        if not self.gnbs.get(ue.serving_gnb_id):
            return
        cell_rsrp = {}
        for gnb in self.gnbs.values():
            dist_m = math.sqrt((ue.x-gnb.x)**2+(ue.y-gnb.y)**2)*self.PIXEL_TO_METER
            try:
                pl, _ = self.channel_model.calculate_pathloss(dist_m, gnb.height)
            except Exception:
                continue
            cell_rsrp[gnb.id] = gnb.tx_power_dbm + gnb.get_sector_gain(ue.x, ue.y) - pl

        if ue.dc_enabled and self.anchor_manager.enabled:
            anc   = ue.anchor_gnb_id
            cands = {g:r for g,r in cell_rsrp.items() if g != anc}
            if not cands: return
            best_id   = max(cands, key=cands.get)
            best_rsrp = cands[best_id]
            cur_senb  = ue.secondary_gnb_id or ue.serving_gnb_id
            cur_rsrp  = cell_rsrp.get(cur_senb, -200.0)
            if best_id != cur_senb and best_rsrp > cur_rsrp + self.hysteresis_db:
                if ue.ttt_target == best_id:
                    ue.ttt_timer += 1
                    if ue.ttt_timer >= self.ttt_steps:
                        self._do_handover(ue, best_id, dc_senb_only=True)
                        ue.ttt_timer = 0; ue.ttt_target = None
                else:
                    ue.ttt_target = best_id; ue.ttt_timer = 1
            else:
                ue.ttt_timer = 0; ue.ttt_target = None
            return

        best_id   = max(cell_rsrp, key=cell_rsrp.get)
        best_rsrp = cell_rsrp[best_id]
        srv_rsrp  = cell_rsrp.get(ue.serving_gnb_id, -200.0)
        if best_id != ue.serving_gnb_id and best_rsrp > srv_rsrp + self.hysteresis_db:
            if ue.ttt_target == best_id:
                ue.ttt_timer += 1
                if ue.ttt_timer >= self.ttt_steps:
                    self._do_handover(ue, best_id)
                    ue.ttt_timer = 0; ue.ttt_target = None
            else:
                ue.ttt_target = best_id; ue.ttt_timer = 1
        else:
            ue.ttt_timer = 0; ue.ttt_target = None

    def _do_handover(self, ue, target_id: str, dc_senb_only=False):
        old_id = ue.serving_gnb_id
        if dc_senb_only:
            old_id = ue.secondary_gnb_id or old_id
            ue.secondary_gnb_id = target_id
            with self.anchor_manager._lock:
                if ue.id in self.anchor_manager.ue_dc_state:
                    self.anchor_manager.ue_dc_state[ue.id]["senb"] = target_id
        else:
            if old_id and old_id in self.gnbs:
                try: self.gnbs[old_id].connected_ues.remove(ue.id)
                except ValueError: pass
            ue.serving_gnb_id = target_id
            tgt = self.gnbs.get(target_id)
            if tgt and ue.id not in tgt.connected_ues:
                tgt.connected_ues.append(ue.id)
        ev = ue.trigger_handover(target_id, old_id)
        ev.update({'time':self.sim_time,'step':self.step,
                   'ue_id':ue.id,'serving':old_id,'dc_mode':dc_senb_only})
        self.handover_events.append(ev)
        self.total_handovers += 1
        if len(self.handover_events) > 1000:
            self.handover_events.pop(0)
        tag = "(DC SeNB)" if dc_senb_only else ""
        self._log_event(f"HO{tag}: {ue.id} {old_id}→{target_id} "
                        f"RSRP={ue.rsrp:.1f}dBm")
        self.anchor_manager.broadcast_ho_event(
            ue.id, old_id, target_id, ue.rsrp, ue.x, ue.y, self.sim_time)
        self.anchor_manager.queue_ho_chart(
            ue.id, old_id, target_id, self.sim_time)

    # ── metrics ───────────────────────────────────────────────────────────

    def _collect_metrics(self):
        total_tp = sum(
            ue.throughput for ue in self.ues.values()
            if ue.serving_gnb_id and ue.serving_gnb_id in self.gnbs
        ) if self.ues and self.gnbs else 0.0
        avg_sinr = (sum(u.sinr for u in self.ues.values()) / len(self.ues)
                    ) if self.ues else 0.0
        self.cumulative_throughput += max(total_tp, 0) * self.step_duration
        self.avg_throughput_overall = (
            round(self.cumulative_throughput / self.sim_time, 2)
            if self.sim_time > 0 else round(total_tp, 2))
        poor = sum(1 for u in self.ues.values() if u.sinr < -5)
        self.packet_loss_rate = round(poor / max(len(self.ues),1)*100, 1)
        m = {
            'time':                   self.sim_time,
            'step':                   self.step,
            'total_throughput':       round(total_tp, 2),
            'cumulative_mb':          round(self.cumulative_throughput, 2),
            'avg_throughput_overall': self.avg_throughput_overall,
            'avg_sinr':               round(avg_sinr, 2),
            'avg_rsrp':               round(sum(u.rsrp for u in self.ues.values())
                                            / max(len(self.ues),1), 2),
            'packet_loss':            self.packet_loss_rate,
            'handovers':              self.total_handovers,
            'active_ues':             len(self.ues),
            'active_gnbs':            len(self.gnbs),
            'ue_throughputs':         {u.id: round(u.throughput,2) for u in self.ues.values()},
            'ue_sinrs':               {u.id: round(u.sinr,2)       for u in self.ues.values()},
        }
        self.metrics_history.append(m)
        if len(self.metrics_history) > 500:
            self.metrics_history.pop(0)

    def _log_event(self, message: str):
        self.event_log.append({'time':round(self.sim_time,2),
                               'step':self.step,'message':message})
        if len(self.event_log) > 200:
            self.event_log.pop(0)

    # ── state for GUI / SSE ───────────────────────────────────────────────

    def _build_state_dict(self) -> dict:
        with self.lock:
            am = self.anchor_manager
            return {
                'running':        self.running,
                'step':           self.step,
                'sim_time':       self.sim_time,
                'scenario':       self.scenario,
                'pathloss_model': self.channel_model.pathloss_model,
                'gnbs': {gid: g.to_dict() for gid, g in self.gnbs.items()},
                'ues':  {uid: u.to_dict() for uid, u in self.ues.items()},
                'metrics':         self.metrics_history[-100:],
                'handover_events': self.handover_events[-500:],
                'event_log':       self.event_log[-30:],
                'anchor': {
                    'enabled':       am.enabled,
                    'anchor_gnb':    am.anchor_gnb_id,
                    'anchor_gnb_ids': list(am.anchor_gnb_ids),
                    'tcp_port':      TCP_PORT,
                    'tcp_clients':   len(am._clients),
                },
                'global': {
                    'total_throughput':       round(sum(u.throughput for u in self.ues.values()), 2),
                    'cumulative_mb':          round(self.cumulative_throughput, 2),
                    'avg_throughput_overall': self.avg_throughput_overall,
                    'avg_sinr':               round(sum(u.sinr for u in self.ues.values())
                                                    / max(len(self.ues),1), 2),
                    'packet_loss':            self.packet_loss_rate,
                    'total_handovers':        self.total_handovers,
                    'num_gnbs':               len(self.gnbs),
                    'num_ues':                len(self.ues),
                },
            }

    def get_state(self) -> dict:
        with self._state_cache_lock:
            cached = self._state_cache
        if cached:
            return cached
        return self._build_state_dict()

    def get_metrics(self):
        with self.lock:
            return self.metrics_history[-100:]

    def get_handover_details(self):
        with self.lock:
            return list(self.handover_events)

    def get_throughput(self):
        with self.lock:
            return {uid: u.throughput for uid, u in self.ues.items()}

    def reset(self):
        self.stop()
        time.sleep(0.15)
        with self.lock:
            gNB.gnb_counter = 0
            UE.ue_counter   = 0
            self.gnbs.clear()
            self.ues.clear()
            self.step                   = 0
            self.sim_time               = 0.0
            self.handover_events.clear()
            self.event_log.clear()
            self.metrics_history.clear()
            self.total_handovers        = 0
            self.packet_loss_rate       = 0
            self.cumulative_throughput  = 0.0
            self.avg_throughput_overall = 0.0
            am = self.anchor_manager
            with am._lock:
                am.enabled       = False
                am.anchor_gnb_id = None
                am.anchor_gnb_ids.clear()
                am.ue_dc_state.clear()
                am.rsrp_history.clear()
                am._chart_queue.clear()
        with self._state_cache_lock:
            self._state_cache = {}
        self._log_event("Simulation reset")


from .anchor import TCP_PORT
