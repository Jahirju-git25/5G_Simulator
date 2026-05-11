"""
5G NR UE (User Equipment)
Extended with Dual Connectivity (DC) state fields for Anchor module.
"""
import math
from .mobility import MobilityModel


class UE:
    """5G NR User Equipment"""

    ue_counter = 0

    def __init__(self, x, y, mobility_model='none', speed=3.0, bounds=(0,0,800,600)):
        UE.ue_counter += 1
        self.id = f"UE-{UE.ue_counter}"
        self.x = x
        self.y = y

        self.mobility = MobilityModel(
            x, y,
            model_type=mobility_model,
            speed=speed,
            bounds=bounds
        )

        self.tx_power_dbm    = 23
        self.rx_gain_db      = 0
        self.noise_figure_db = 7

        self.serving_gnb_id = None
        self.serving_sector = None

        self.rsrp       = -120
        self.rsrq       = -15
        self.sinr       = -10
        self.throughput = 0
        self.pathloss   = 150
        self.distance   = 0
        self.modulation = 'QPSK'

        self.handover_count   = 0
        self.handover_history = []
        self.ping_pong_count  = 0
        self.in_handover      = False

        self.ttt_timer     = 0
        self.ttt_target    = None
        self.ttt_threshold = 3

        self.rsrp_history       = []
        self.sinr_history       = []
        self.throughput_history = []
        # Increased to 500 so traces persist much longer
        self.position_history   = []

        # ── Dual Connectivity state (managed by AnchorManager) ─────────────
        self.dc_enabled         = False          # True when anchor mode is on
        self.anchor_gnb_id      = None           # MeNB (anchor gNB)
        self.secondary_gnb_id   = None           # SeNB (normal gNB)
        # Combined DC throughput (MeNB + SeNB)
        self.dc_throughput      = 0.0

        self.active = True

    def update_position(self, dt=0.1):
        """Update UE position via mobility model"""
        self.mobility.update(dt)
        self.x = self.mobility.x
        self.y = self.mobility.y

        self.position_history.append({'x': round(self.x, 1), 'y': round(self.y, 1)})
        # Keep 500 points (~50 s of movement at 0.1 s step)
        if len(self.position_history) > 500:
            self.position_history.pop(0)

    def update_measurements(self, rsrp, sinr, throughput, pathloss, distance):
        """Update radio measurements"""
        self.rsrp       = round(rsrp, 2)
        self.sinr       = round(sinr, 2)
        self.throughput = round(throughput, 2)
        self.pathloss   = round(pathloss, 2)
        self.distance   = round(distance, 2)
        self.rsrq       = round(self.rsrp - (self.sinr / 2), 2)

        self.rsrp_history.append(self.rsrp)
        self.sinr_history.append(self.sinr)
        self.throughput_history.append(self.throughput)
        for lst in [self.rsrp_history, self.sinr_history, self.throughput_history]:
            if len(lst) > 200:
                lst.pop(0)

    def get_velocity(self):
        return self.mobility.get_velocity()

    def trigger_handover(self, new_gnb_id, old_gnb_id, reason='A3'):
        """Record handover event"""
        self.in_handover = True

        if len(self.handover_history) >= 2:
            last = self.handover_history[-1]
            if last['target'] == old_gnb_id and (self.handover_count - last['count']) < 5:
                self.ping_pong_count += 1

        event = {
            'count':  self.handover_count,
            'from':   old_gnb_id,
            'target': new_gnb_id,
            'reason': reason,
            'rsrp':   self.rsrp,
            'sinr':   self.sinr,
        }
        self.handover_history.append(event)
        self.handover_count += 1

        if len(self.handover_history) > 50:
            self.handover_history.pop(0)

        self.in_handover = False
        return event

    def to_dict(self):
        d = {
            'id':               self.id,
            'x':                round(self.x, 1),
            'y':                round(self.y, 1),
            'serving_gnb':      self.serving_gnb_id,
            'rsrp':             self.rsrp,
            'rsrq':             self.rsrq,
            'sinr':             self.sinr,
            'throughput':       self.throughput,
            'pathloss':         self.pathloss,
            'distance':         self.distance,
            'modulation':       self.modulation,
            'handover_count':   self.handover_count,
            'handover_history': self.handover_history,  # CRITICAL: ML detector needs this
            'ping_pong_count':  self.ping_pong_count,
            'velocity':         round(self.get_velocity(), 2),
            'mobility_model':   self.mobility.model_type,
            'active':           self.active,
            'rsrp_history':     self.rsrp_history[-50:],
            'sinr_history':     self.sinr_history[-50:],
            'throughput_history': self.throughput_history[-50:],
            # Send full position history for persistent trace rendering
            'position_history': self.position_history,
            # DC fields
            'dc_enabled':       self.dc_enabled,
            'anchor_gnb_id':    self.anchor_gnb_id,
            'secondary_gnb_id': self.secondary_gnb_id,
            'dc_throughput':    round(self.dc_throughput, 2),
        }
        return d
