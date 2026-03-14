"""
5G NR Network Simulator Engine
Time-stepped simulation with event-driven handover
"""
import math
import time
import threading
import random
from .gnb import gNB
from .ue import UE
from .channel import ChannelModel
from .scheduler import Scheduler


class NetworkSimulator:
    """Main 5G NR Network Simulator"""

    PIXEL_TO_METER = 5.0
    CANVAS_WIDTH   = 800
    CANVAS_HEIGHT  = 600

    def __init__(self):
        self.gnbs = {}
        self.ues  = {}
        self.scenario = 'UMa'
        self.channel_model = ChannelModel(scenario='UMa')
        self.scheduler = Scheduler()

        self.running       = False
        self.step          = 0
        self.sim_time      = 0.0
        self.step_duration = 0.1
        self.speed_factor  = 1.0

        self.handover_events = []
        self.event_log       = []

        self.metrics_history       = []
        self.total_handovers       = 0
        self.packet_loss_rate      = 0
        self.cumulative_throughput = 0.0
        self.avg_throughput_overall = 0.0
        self.step_time             = 0.0

        self.sim_thread = None
        self.lock = threading.Lock()

        self.hysteresis_db = 3.0
        self.ttt_steps     = 3

    # ─────────────────────────────────────────
    #  Channel configuration
    # ─────────────────────────────────────────

    def set_scenario(self, scenario):
        """Change 3GPP outdoor scenario (preserves other channel settings)"""
        with self.lock:
            self.scenario = scenario
            self.channel_model = ChannelModel(
                scenario        = scenario,
                pathloss_model  = self.channel_model.pathloss_model,
                log_dist_n      = self.channel_model.log_dist_n,
                log_dist_shadow = self.channel_model.log_dist_shadow,
                fading_model    = self.channel_model.fading_model,
            )
            # Update gNB heights to match scenario
            for gnb in self.gnbs.values():
                gnb.height = {'UMa': 25, 'UMi': 10, 'RMa': 35}.get(scenario, 25)
            self._log_event(f"Scenario changed to {scenario}")

    def set_channel_config(self, pathloss_model=None, scenario=None,
                           log_dist_n=None, log_dist_shadow=None,
                           fading_model=None):
        """
        Update channel model — only non-None fields are changed.
        pathloss_model  : '3GPP' | 'LogDistance'
        scenario        : 'UMa' | 'UMi' | 'RMa'  (3GPP only)
        log_dist_n      : float 1.6–6.0            (LogDistance only)
        log_dist_shadow : 'lognormal' | 'none'     (LogDistance only)
        fading_model    : 'Rayleigh'
        """
        with self.lock:
            pm  = pathloss_model  if pathloss_model  is not None else self.channel_model.pathloss_model
            sc  = scenario        if scenario         is not None else self.channel_model.scenario
            ldn = log_dist_n      if log_dist_n       is not None else self.channel_model.log_dist_n
            lds = log_dist_shadow if log_dist_shadow  is not None else self.channel_model.log_dist_shadow
            fm  = fading_model    if fading_model     is not None else self.channel_model.fading_model

            self.scenario = sc
            self.channel_model = ChannelModel(
                scenario        = sc,
                pathloss_model  = pm,
                log_dist_n      = ldn,
                log_dist_shadow = lds,
                fading_model    = fm,
            )
            label = (f"3GPP·{sc}" if pm == '3GPP'
                     else f"LogDist·n={ldn:.1f}·shadow={lds}")
            self._log_event(f"Channel: {label} · fading={fm}")

    # ─────────────────────────────────────────
    #  Node management
    # ─────────────────────────────────────────

    def add_gnb(self, x, y, tx_power=43, num_sectors=3):
        with self.lock:
            gnb = gNB(x, y, tx_power_dbm=tx_power, num_sectors=num_sectors)
            gnb.height = {'UMa': 25, 'UMi': 10, 'RMa': 35}.get(self.scenario, 25)
            for existing in self.gnbs.values():
                gnb.add_neighbor(existing)
                existing.add_neighbor(gnb)
            self.gnbs[gnb.id] = gnb
            self._log_event(f"Added {gnb.id} at ({x:.0f}, {y:.0f})")
            return gnb.id

    def add_ue(self, x, y, mobility='random_waypoint', speed=3.0):
        with self.lock:
            ue = UE(x, y,
                    mobility_model=mobility,
                    speed=speed,
                    bounds=(10, 10, self.CANVAS_WIDTH-10, self.CANVAS_HEIGHT-10))
            self.ues[ue.id] = ue
            if self.gnbs:
                self._attach_ue(ue)
            self._log_event(f"Added {ue.id} at ({x:.0f}, {y:.0f}) - attached to {ue.serving_gnb_id}")
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

    def _attach_ue(self, ue):
        if not self.gnbs:
            ue.serving_gnb_id = None
            return
        best_gnb  = None
        best_rsrp = -200
        for gnb in self.gnbs.values():
            dist_px = math.sqrt((ue.x - gnb.x)**2 + (ue.y - gnb.y)**2)
            dist_m  = dist_px * self.PIXEL_TO_METER
            pl, _   = self.channel_model.calculate_pathloss(dist_m, gnb.height)
            sector_gain = gnb.get_sector_gain(ue.x, ue.y)
            rsrp = gnb.tx_power_dbm + sector_gain - pl
            if rsrp > best_rsrp:
                best_rsrp = rsrp
                best_gnb  = gnb
        if best_gnb:
            ue.serving_gnb_id = best_gnb.id
            if ue.id not in best_gnb.connected_ues:
                best_gnb.connected_ues.append(ue.id)

    # ─────────────────────────────────────────
    #  Simulation loop
    # ─────────────────────────────────────────

    def start(self):
        if not self.running:
            self.running = True
            self.step    = 0
            self.sim_time = 0.0
            self.cumulative_throughput  = 0.0
            self.avg_throughput_overall = 0.0
            self.sim_thread = threading.Thread(target=self._simulation_loop, daemon=True)
            self.sim_thread.start()
            print(f"Thread started: {self.sim_thread.is_alive()}", flush=True)
            self._log_event("Simulation started")

    def stop(self):
        self.running = False
        self._log_event("Simulation stopped")

    def simulate_step(self):
        with self.lock:
            self._execute_step()

    def _simulation_loop(self):
        print("SIMULATION LOOP STARTED", flush=True)
        while self.running:
            step_start = time.time()
            try:
                with self.lock:
                    self._execute_step()
            except Exception as e:
                import traceback
                print("STEP ERROR:", e, flush=True)
                traceback.print_exc()
            elapsed    = time.time() - step_start
            sleep_time = (self.step_duration / self.speed_factor) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        print("SIMULATION LOOP ENDED", flush=True)

    def _execute_step(self):
        self.step     += 1
        self.sim_time  = round(self.step * self.step_duration, 2)

        if not self.ues or not self.gnbs:
            self._collect_global_metrics()
            return

        for ue in self.ues.values():
            ue.update_position(self.step_duration)

        for ue in self.ues.values():
            if not ue.serving_gnb_id or ue.serving_gnb_id not in self.gnbs:
                self._attach_ue(ue)
            self._calculate_ue_metrics(ue)

        for ue in self.ues.values():
            self._check_handover(ue)

        for gnb in self.gnbs.values():
            gnb.total_throughput = sum(
                self.ues[uid].throughput
                for uid in gnb.connected_ues if uid in self.ues
            )

        self._collect_global_metrics()

    def _calculate_ue_metrics(self, ue):
        print(f"CALC: {ue.id} serving={ue.serving_gnb_id} gnbs={list(self.gnbs.keys())}")
        if not ue.serving_gnb_id or ue.serving_gnb_id not in self.gnbs:
            print(f"  -> SKIPPED (no serving gnb)")
            return

        serving_gnb = self.gnbs[ue.serving_gnb_id]
        dist_px = math.sqrt((ue.x - serving_gnb.x)**2 + (ue.y - serving_gnb.y)**2)
        dist_m  = dist_px * self.PIXEL_TO_METER
        ue.distance = dist_m

        pl, is_los = self.channel_model.calculate_pathloss(dist_m, serving_gnb.height)
        ue.pathloss = pl

        sector_gain = serving_gnb.get_sector_gain(ue.x, ue.y)
        rsrp = serving_gnb.tx_power_dbm + sector_gain - pl

        interference_list = []
        for gnb in self.gnbs.values():
            if gnb.id != ue.serving_gnb_id:
                d_px = math.sqrt((ue.x - gnb.x)**2 + (ue.y - gnb.y)**2)
                d_m  = d_px * self.PIXEL_TO_METER
                interf_pl, _ = self.channel_model.calculate_pathloss(d_m, gnb.height)
                interf_gain  = gnb.get_sector_gain(ue.x, ue.y)
                interf_rsrp  = gnb.tx_power_dbm + interf_gain - interf_pl
                interference_list.append(interf_rsrp)

        sinr       = self.channel_model.calculate_sinr(rsrp, interference_list)
        throughput, mcs, modulation = self.channel_model.calculate_throughput(sinr)

        velocity = ue.get_velocity() * self.PIXEL_TO_METER
        if velocity > 30:
            doppler_penalty = min(0.3, velocity / 300)
            throughput *= (1 - doppler_penalty)

        ue.modulation = modulation
        ue.update_measurements(rsrp, sinr, throughput, pl, dist_m)

    def _check_handover(self, ue):
        if not ue.serving_gnb_id or len(self.gnbs) < 2:
            return
        serving_gnb = self.gnbs.get(ue.serving_gnb_id)
        if not serving_gnb:
            return

        cell_rsrps = {}
        for gnb in self.gnbs.values():
            dist_px = math.sqrt((ue.x - gnb.x)**2 + (ue.y - gnb.y)**2)
            dist_m  = dist_px * self.PIXEL_TO_METER
            pl, _   = self.channel_model.calculate_pathloss(dist_m, gnb.height)
            sector_gain = gnb.get_sector_gain(ue.x, ue.y)
            rsrp = gnb.tx_power_dbm + sector_gain - pl
            cell_rsrps[gnb.id] = rsrp

        serving_rsrp = cell_rsrps.get(ue.serving_gnb_id, -200)
        best_gnb_id  = max(cell_rsrps, key=cell_rsrps.get)
        best_rsrp    = cell_rsrps[best_gnb_id]

        if best_gnb_id != ue.serving_gnb_id and best_rsrp > serving_rsrp + self.hysteresis_db:
            if ue.ttt_target == best_gnb_id:
                ue.ttt_timer += 1
                if ue.ttt_timer >= self.ttt_steps:
                    self._execute_handover(ue, best_gnb_id)
                    ue.ttt_timer  = 0
                    ue.ttt_target = None
            else:
                ue.ttt_target = best_gnb_id
                ue.ttt_timer  = 1
        else:
            ue.ttt_timer  = 0
            ue.ttt_target = None

    def _execute_handover(self, ue, target_gnb_id):
        old_gnb_id = ue.serving_gnb_id
        if old_gnb_id and old_gnb_id in self.gnbs:
            old_gnb = self.gnbs[old_gnb_id]
            if ue.id in old_gnb.connected_ues:
                old_gnb.connected_ues.remove(ue.id)

        target_gnb = self.gnbs[target_gnb_id]
        ue.serving_gnb_id = target_gnb_id
        if ue.id not in target_gnb.connected_ues:
            target_gnb.connected_ues.append(ue.id)

        event = ue.trigger_handover(target_gnb_id, old_gnb_id)
        event['time']    = self.sim_time
        event['step']    = self.step
        event['ue_id']   = ue.id
        event['serving'] = old_gnb_id

        self.handover_events.append(event)
        self.total_handovers += 1
        if len(self.handover_events) > 1000:
            self.handover_events.pop(0)

        self._log_event(f"Handover: {ue.id} {old_gnb_id} → {target_gnb_id} (RSRP: {ue.rsrp:.1f} dBm)")

    # ─────────────────────────────────────────
    #  Metrics
    # ─────────────────────────────────────────

    def _collect_global_metrics(self):
        total_tp = 0.0
        if self.ues and self.gnbs:
            for ue in self.ues.values():
                if ue.serving_gnb_id and ue.serving_gnb_id in self.gnbs:
                    total_tp += ue.throughput

        avg_sinr = (sum(ue.sinr for ue in self.ues.values()) / len(self.ues)) if self.ues else 0.0
        avg_rsrp = (sum(ue.rsrp for ue in self.ues.values()) / len(self.ues)) if self.ues else 0.0

        # cumulative_throughput: Mbps × seconds = Mb (total data transferred)
        self.cumulative_throughput += max(total_tp, 0) * self.step_duration

        # avg_throughput_overall: mean network throughput over elapsed time (Mbps)
        if self.sim_time > 0:
            self.avg_throughput_overall = round(self.cumulative_throughput / self.sim_time, 2)
        else:
            self.avg_throughput_overall = round(total_tp, 2)

        poor_ues = sum(1 for ue in self.ues.values() if ue.sinr < -5)
        self.packet_loss_rate = round(poor_ues / max(len(self.ues), 1) * 100, 1)

        metric = {
            'time':                     self.sim_time,
            'step':                     self.step,
            'total_throughput':         round(total_tp, 2),
            'cumulative_mb':            round(self.cumulative_throughput, 2),
            'avg_throughput_overall':   self.avg_throughput_overall,
            'avg_sinr':                 round(avg_sinr, 2),
            'avg_rsrp':                 round(avg_rsrp, 2),
            'packet_loss':              self.packet_loss_rate,
            'spectral_efficiency':      round(total_tp / (max(len(self.ues), 1) * 100), 3),
            'handovers':                self.total_handovers,
            'active_ues':               len(self.ues),
            'active_gnbs':              len(self.gnbs),
            'ue_throughputs':           {ue.id: round(ue.throughput, 2) for ue in self.ues.values()},
        }
        self.metrics_history.append(metric)
        if len(self.metrics_history) > 500:
            self.metrics_history.pop(0)

    def _log_event(self, message):
        self.event_log.append({
            'time':    round(self.sim_time, 2),
            'step':    self.step,
            'message': message,
        })
        if len(self.event_log) > 200:
            self.event_log.pop(0)

    # ─────────────────────────────────────────
    #  State / getters
    # ─────────────────────────────────────────

    def get_state(self):
        with self.lock:
            return {
                'running':          self.running,
                'step':             self.step,
                'sim_time':         self.sim_time,
                'scenario':         self.scenario,
                'pathloss_model':   self.channel_model.pathloss_model,
                'gnbs':             {gid: g.to_dict() for gid, g in self.gnbs.items()},
                'ues':              {uid: u.to_dict() for uid, u in self.ues.items()},
                'metrics':          self.metrics_history[-100:] if self.metrics_history else [],
                'handover_events':  self.handover_events[-500:],
                'event_log':        self.event_log[-30:],
                'global': {
                    'total_throughput':       sum(u.throughput for u in self.ues.values()),
                    'cumulative_mb':          round(self.cumulative_throughput, 2),
                    'avg_throughput_overall': self.avg_throughput_overall,
                    'avg_sinr':               sum(u.sinr for u in self.ues.values()) / max(len(self.ues), 1),
                    'packet_loss':            self.packet_loss_rate,
                    'total_handovers':        self.total_handovers,
                    'num_gnbs':               len(self.gnbs),
                    'num_ues':                len(self.ues),
                },
            }

    def get_metrics(self):
        with self.lock:
            return self.metrics_history[-100:]

    def get_handover_details(self):
        with self.lock:
            return self.handover_events

    def get_throughput(self):
        with self.lock:
            return {uid: u.throughput for uid, u in self.ues.items()}

    def reset(self):
        self.stop()
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
        self._log_event("Simulation reset")
