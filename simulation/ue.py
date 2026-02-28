"""
5G NR UE (User Equipment)
"""
import math
from .mobility import MobilityModel


class UE:
    """5G NR User Equipment"""

    ue_counter = 0

    def __init__(self, x, y, mobility_model='random_waypoint', speed=3.0, bounds=(0,0,800,600)):
        UE.ue_counter += 1
        self.id = f"UE-{UE.ue_counter}"
        self.x = x
        self.y = y
        
        # Mobility
        self.mobility = MobilityModel(
            x, y, 
            model_type=mobility_model,
            speed=speed,
            bounds=bounds
        )
        
        # Radio
        self.tx_power_dbm = 23  # 200mW
        self.rx_gain_db = 0
        self.noise_figure_db = 7
        
        # Serving cell
        self.serving_gnb_id = None
        self.serving_sector = None
        
        # Measurements
        self.rsrp = -120  # dBm
        self.rsrq = -15   # dB
        self.sinr = -10   # dB
        self.throughput = 0  # Mbps
        self.pathloss = 150  # dB
        self.distance = 0    # m (pixels)
        self.modulation = 'QPSK'
        
        # Handover
        self.handover_count = 0
        self.handover_history = []
        self.ping_pong_count = 0
        self.in_handover = False
        
        # TTT (Time-to-Trigger) for handover
        self.ttt_timer = 0
        self.ttt_target = None
        self.ttt_threshold = 3  # steps (300ms)
        
        # History for charts
        self.rsrp_history = []
        self.sinr_history = []
        self.throughput_history = []
        self.position_history = []
        
        self.active = True

    def update_position(self, dt=0.1):
        """Update UE position via mobility model"""
        self.mobility.update(dt)
        self.x = self.mobility.x
        self.y = self.mobility.y
        
        # Store position history (limit to 100 points)
        self.position_history.append({'x': round(self.x, 1), 'y': round(self.y, 1)})
        if len(self.position_history) > 100:
            self.position_history.pop(0)

    def update_measurements(self, rsrp, sinr, throughput, pathloss, distance):
        """Update radio measurements"""
        self.rsrp = round(rsrp, 2)
        self.sinr = round(sinr, 2)
        self.throughput = round(throughput, 2)
        self.pathloss = round(pathloss, 2)
        self.distance = round(distance, 2)
        
        # RSRQ estimate
        self.rsrq = round(self.rsrp - (self.sinr / 2), 2)
        
        # Store history (limit to 200 points)
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
        
        # Check for ping-pong (handover back within short time)
        if len(self.handover_history) >= 2:
            last = self.handover_history[-1]
            if last['target'] == old_gnb_id and (self.handover_count - last['count']) < 5:
                self.ping_pong_count += 1
        
        event = {
            'count': self.handover_count,
            'from': old_gnb_id,
            'target': new_gnb_id,
            'reason': reason,
            'rsrp': self.rsrp,
            'sinr': self.sinr
        }
        self.handover_history.append(event)
        self.handover_count += 1
        
        # Keep last 50 handovers
        if len(self.handover_history) > 50:
            self.handover_history.pop(0)
        
        self.in_handover = False
        return event

    def to_dict(self):
        return {
            'id': self.id,
            'x': round(self.x, 1),
            'y': round(self.y, 1),
            'serving_gnb': self.serving_gnb_id,
            'rsrp': self.rsrp,
            'rsrq': self.rsrq,
            'sinr': self.sinr,
            'throughput': self.throughput,
            'pathloss': self.pathloss,
            'distance': self.distance,
            'modulation': self.modulation,
            'handover_count': self.handover_count,
            'ping_pong_count': self.ping_pong_count,
            'velocity': round(self.get_velocity(), 2),
            'active': self.active,
            'rsrp_history': self.rsrp_history[-50:],
            'sinr_history': self.sinr_history[-50:],
            'throughput_history': self.throughput_history[-50:]
        }
