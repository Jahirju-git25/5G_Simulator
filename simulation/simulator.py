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

    # Pixel to meter scaling (1 pixel = 5 meters for 800x600 canvas)
    PIXEL_TO_METER = 5.0
    CANVAS_WIDTH = 800
    CANVAS_HEIGHT = 600

    def __init__(self):
        self.gnbs = {}        # {id: gNB}
        self.ues = {}         # {id: UE}
        self.scenario = 'UMa'
        self.channel_model = ChannelModel(self.scenario)
        self.scheduler = Scheduler()
        
        # Simulation state
        self.running = False
        self.step = 0
        self.sim_time = 0.0  # seconds
        self.step_duration = 0.1  # 100ms steps
        self.speed_factor = 1.0
        
        # Events log
        self.handover_events = []
        self.event_log = []
        
        # Global metrics
        self.metrics_history = []
        self.total_handovers = 0
        self.packet_loss_rate = 0
        
        # Thread
        self.sim_thread = None
        self.lock = threading.Lock()
        
        # Hysteresis and TTT for handover
        self.hysteresis_db = 3.0   # dB
        self.ttt_steps = 3          # 300ms

    def set_scenario(self, scenario):
        """Change propagation scenario"""
        with self.lock:
            self.scenario = scenario
            self.channel_model = ChannelModel(scenario)
            self._log_event(f"Scenario changed to {scenario}")

    def add_gnb(self, x, y, tx_power=43, num_sectors=3):
        """Add a gNB to the network"""
        with self.lock:
            gnb = gNB(x, y, tx_power_dbm=tx_power, num_sectors=num_sectors)
            
            # Set height based on scenario
            if self.scenario == 'UMa':
                gnb.height = 25
            elif self.scenario == 'UMi':
                gnb.height = 10
            elif self.scenario == 'RMa':
                gnb.height = 35
            
            # Auto-connect Xn interfaces
            for existing_gnb in self.gnbs.values():
                gnb.add_neighbor(existing_gnb)
                existing_gnb.add_neighbor(gnb)
            
            self.gnbs[gnb.id] = gnb
            self._log_event(f"Added {gnb.id} at ({x:.0f}, {y:.0f})")
            return gnb.id

    def add_ue(self, x, y, mobility='random_waypoint', speed=3.0):
        """Add a UE to the network"""
        with self.lock:
            ue = UE(x, y, 
                    mobility_model=mobility, 
                    speed=speed,
                    bounds=(10, 10, self.CANVAS_WIDTH-10, self.CANVAS_HEIGHT-10))
            self.ues[ue.id] = ue
            
            # Initial attachment to best gNB
            self._attach_ue(ue)
            self._log_event(f"Added {ue.id} at ({x:.0f}, {y:.0f}) - attached to {ue.serving_gnb_id}")
            return ue.id

    def remove_gnb(self, gnb_id):
        with self.lock:
            if gnb_id in self.gnbs:
                del self.gnbs[gnb_id]
                # Reattach UEs
                for ue in self.ues.values():
                    if ue.serving_gnb_id == gnb_id:
                        self._attach_ue(ue)

    def remove_ue(self, ue_id):
        with self.lock:
            if ue_id in self.ues:
                del self.ues[ue_id]

    def _attach_ue(self, ue):
        """Attach UE to best gNB"""
        if not self.gnbs:
            ue.serving_gnb_id = None
            return
        
        best_gnb = None
        best_rsrp = -200

        for gnb in self.gnbs.values():
            dist_px = math.sqrt((ue.x - gnb.x)**2 + (ue.y - gnb.y)**2)
            dist_m = dist_px * self.PIXEL_TO_METER
            
            pl, _ = self.channel_model.calculate_pathloss(dist_m, gnb.height)
            sector_gain = gnb.get_sector_gain(ue.x, ue.y)
            rsrp = gnb.tx_power_dbm + sector_gain - pl
            
            if rsrp > best_rsrp:
                best_rsrp = rsrp
                best_gnb = gnb
        
        if best_gnb:
            ue.serving_gnb_id = best_gnb.id
            if ue.id not in best_gnb.connected_ues:
                best_gnb.connected_ues.append(ue.id)

    def start(self):
        """Start simulation"""
        if not self.running:
            self.running = True
            self.sim_thread = threading.Thread(target=self._simulation_loop, daemon=True)
            self.sim_thread.start()
            self._log_event("Simulation started")

    def stop(self):
        """Stop simulation"""
        self.running = False
        self._log_event("Simulation stopped")

    def simulate_step(self):
        """Execute one simulation step"""
        with self.lock:
            self._execute_step()

    def _simulation_loop(self):
        """Main simulation loop"""
        while self.running:
            step_start = time.time()
            
            with self.lock:
                self._execute_step()
            
            # Sleep to maintain real-time pace
            elapsed = time.time() - step_start
            sleep_time = (self.step_duration / self.speed_factor) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _execute_step(self):
        """Execute one simulation step (100ms)"""
        self.step += 1
        self.sim_time = round(self.step * self.step_duration, 2)

        # Update UE positions
        for ue in self.ues.values():
            ue.update_position(self.step_duration)

        # Calculate radio metrics for all UEs
        for ue in self.ues.values():
            self._calculate_ue_metrics(ue)

        # Check handover conditions
        for ue in self.ues.values():
            self._check_handover(ue)

        # Update gNB metrics
        for gnb in self.gnbs.values():
            gnb.total_throughput = sum(
                self.ues[uid].throughput 
                for uid in gnb.connected_ues 
                if uid in self.ues
            )

        # Collect global metrics
        self._collect_global_metrics()

    def _calculate_ue_metrics(self, ue):
        """Calculate RSRP, SINR, throughput for a UE"""
        if not ue.serving_gnb_id or ue.serving_gnb_id not in self.gnbs:
            return
        
        serving_gnb = self.gnbs[ue.serving_gnb_id]
        
        # Distance in meters
        dist_px = math.sqrt((ue.x - serving_gnb.x)**2 + (ue.y - serving_gnb.y)**2)
        dist_m = dist_px * self.PIXEL_TO_METER
        ue.distance = dist_m
        
        # Pathloss
        pl, is_los = self.channel_model.calculate_pathloss(dist_m, serving_gnb.height)
        ue.pathloss = pl
        
        # Sector gain
        sector_gain = serving_gnb.get_sector_gain(ue.x, ue.y)
        
        # RSRP
        rsrp = serving_gnb.tx_power_dbm + sector_gain - pl
        
        # Interference from neighbor gNBs
        interference_list = []
        for gnb in self.gnbs.values():
            if gnb.id != ue.serving_gnb_id:
                d_px = math.sqrt((ue.x - gnb.x)**2 + (ue.y - gnb.y)**2)
                d_m = d_px * self.PIXEL_TO_METER
                interf_pl, _ = self.channel_model.calculate_pathloss(d_m, gnb.height)
                interf_gain = gnb.get_sector_gain(ue.x, ue.y)
                interf_rsrp = gnb.tx_power_dbm + interf_gain - interf_pl
                interference_list.append(interf_rsrp)
        
        # SINR
        sinr = self.channel_model.calculate_sinr(rsrp, interference_list)
        
        # Throughput
        throughput, mcs, modulation = self.channel_model.calculate_throughput(sinr)
        
        # Doppler effect on throughput
        velocity = ue.get_velocity() * self.PIXEL_TO_METER  # m/s
        if velocity > 30:  # High speed: reduce throughput
            doppler_penalty = min(0.3, velocity / 300)
            throughput *= (1 - doppler_penalty)
        
        ue.modulation = modulation
        ue.update_measurements(rsrp, sinr, throughput, pl, dist_m)

    def _check_handover(self, ue):
        """A3 event handover: target RSRP > serving RSRP + hysteresis"""
        if not ue.serving_gnb_id or len(self.gnbs) < 2:
            return
        
        serving_gnb = self.gnbs.get(ue.serving_gnb_id)
        if not serving_gnb:
            return
        
        # Calculate RSRP from all cells
        cell_rsrps = {}
        for gnb in self.gnbs.values():
            dist_px = math.sqrt((ue.x - gnb.x)**2 + (ue.y - gnb.y)**2)
            dist_m = dist_px * self.PIXEL_TO_METER
            pl, _ = self.channel_model.calculate_pathloss(dist_m, gnb.height)
            sector_gain = gnb.get_sector_gain(ue.x, ue.y)
            rsrp = gnb.tx_power_dbm + sector_gain - pl
            cell_rsrps[gnb.id] = rsrp
        
        serving_rsrp = cell_rsrps.get(ue.serving_gnb_id, -200)
        
        # Find best cell
        best_gnb_id = max(cell_rsrps, key=cell_rsrps.get)
        best_rsrp = cell_rsrps[best_gnb_id]
        
        # A3 event condition
        if best_gnb_id != ue.serving_gnb_id and best_rsrp > serving_rsrp + self.hysteresis_db:
            # TTT mechanism
            if ue.ttt_target == best_gnb_id:
                ue.ttt_timer += 1
                if ue.ttt_timer >= self.ttt_steps:
                    # Execute handover
                    self._execute_handover(ue, best_gnb_id)
                    ue.ttt_timer = 0
                    ue.ttt_target = None
            else:
                ue.ttt_target = best_gnb_id
                ue.ttt_timer = 1
        else:
            ue.ttt_timer = 0
            ue.ttt_target = None

    def _execute_handover(self, ue, target_gnb_id):
        """Execute handover from current to target gNB"""
        old_gnb_id = ue.serving_gnb_id
        
        # Remove from old gNB
        if old_gnb_id and old_gnb_id in self.gnbs:
            old_gnb = self.gnbs[old_gnb_id]
            if ue.id in old_gnb.connected_ues:
                old_gnb.connected_ues.remove(ue.id)
        
        # Attach to new gNB
        target_gnb = self.gnbs[target_gnb_id]
        ue.serving_gnb_id = target_gnb_id
        if ue.id not in target_gnb.connected_ues:
            target_gnb.connected_ues.append(ue.id)
        
        # Record handover event
        event = ue.trigger_handover(target_gnb_id, old_gnb_id)
        event['time'] = self.sim_time
        event['step'] = self.step
        
        self.handover_events.append(event)
        self.total_handovers += 1
        
        # Keep last 100 events
        if len(self.handover_events) > 100:
            self.handover_events.pop(0)
        
        self._log_event(f"Handover: {ue.id} {old_gnb_id} → {target_gnb_id} (RSRP: {ue.rsrp:.1f} dBm)")

    def _collect_global_metrics(self):
        """Collect network-wide metrics"""
        if not self.ues:
            return
        
        total_tp = sum(ue.throughput for ue in self.ues.values())
        avg_sinr = sum(ue.sinr for ue in self.ues.values()) / len(self.ues)
        avg_rsrp = sum(ue.rsrp for ue in self.ues.values()) / len(self.ues)
        
        # Estimate packet loss (UEs with SINR < -5 dB)
        poor_ues = sum(1 for ue in self.ues.values() if ue.sinr < -5)
        self.packet_loss_rate = round(poor_ues / max(len(self.ues), 1) * 100, 1)
        
        metric = {
            'time': self.sim_time,
            'step': self.step,
            'total_throughput': round(total_tp, 2),
            'avg_sinr': round(avg_sinr, 2),
            'avg_rsrp': round(avg_rsrp, 2),
            'packet_loss': self.packet_loss_rate,
            'spectral_efficiency': round(total_tp / (len(self.ues) * 100), 3),
            'handovers': self.total_handovers,
            'active_ues': len(self.ues),
            'active_gnbs': len(self.gnbs)
        }
        
        self.metrics_history.append(metric)
        if len(self.metrics_history) > 500:
            self.metrics_history.pop(0)

    def _log_event(self, message):
        """Log simulation event"""
        self.event_log.append({
            'time': round(self.sim_time, 2),
            'step': self.step,
            'message': message
        })
        if len(self.event_log) > 200:
            self.event_log.pop(0)

    def get_state(self):
        """Get complete simulation state"""
        with self.lock:
            return {
                'running': self.running,
                'step': self.step,
                'sim_time': self.sim_time,
                'scenario': self.scenario,
                'gnbs': {gid: g.to_dict() for gid, g in self.gnbs.items()},
                'ues': {uid: u.to_dict() for uid, u in self.ues.items()},
                'metrics': self.metrics_history[-100:] if self.metrics_history else [],
                'handover_events': self.handover_events[-50:],
                'event_log': self.event_log[-30:],
                'global': {
                    'total_throughput': sum(u.throughput for u in self.ues.values()),
                    'avg_sinr': sum(u.sinr for u in self.ues.values()) / max(len(self.ues), 1),
                    'packet_loss': self.packet_loss_rate,
                    'total_handovers': self.total_handovers,
                    'num_gnbs': len(self.gnbs),
                    'num_ues': len(self.ues)
                }
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
        """Reset simulation"""
        self.stop()
        with self.lock:
            # Reset counters
            gNB.gnb_counter = 0
            UE.ue_counter = 0
            
            self.gnbs.clear()
            self.ues.clear()
            self.step = 0
            self.sim_time = 0.0
            self.handover_events.clear()
            self.event_log.clear()
            self.metrics_history.clear()
            self.total_handovers = 0
            self.packet_loss_rate = 0
        self._log_event("Simulation reset")
