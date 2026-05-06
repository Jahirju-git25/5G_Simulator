"""5G NR gNB (gNodeB) - Base Station
Extended with is_anchor flag for AnchorGNB-N nodes.
"""
import math

class gNB:
    gnb_counter = 0

    def __init__(self, x, y, tx_power_dbm=43, antenna_gain_db=15, num_sectors=1):
        gNB.gnb_counter += 1
        self.id = f"gNB-{gNB.gnb_counter}"
        self.x = x; self.y = y
        self.tx_power_dbm = tx_power_dbm
        self.antenna_gain_db = antenna_gain_db
        self.num_sectors = num_sectors
        self.height = 25
        self.is_anchor = False   # set to True for AnchorGNB-N nodes
        self.sectors = []
        for i in range(num_sectors):
            self.sectors.append({
                'id': f"{self.id}-S{i+1}",
                'azimuth': i*(360/num_sectors),
                'half_power_bw': 65,
                'active_ues': [],
            })
        self.connected_ues = []
        self.total_throughput = 0
        self.active = True
        self.neighbors = []

    def distance_to(self, x, y):
        return math.sqrt((self.x-x)**2 + (self.y-y)**2)

    def get_sector_for_ue(self, ue_x, ue_y):
        angle_deg = math.degrees(math.atan2(ue_y-self.y, ue_x-self.x)) % 360
        best_sector, min_diff = 0, 360
        for i, sector in enumerate(self.sectors):
            diff = abs(angle_deg - sector['azimuth'])
            if diff > 180: diff = 360 - diff
            if diff < min_diff:
                min_diff = diff; best_sector = i
        return best_sector

    def get_sector_gain(self, ue_x, ue_y):
        return self.antenna_gain_db

    def add_neighbor(self, gnb):
        if gnb not in self.neighbors:
            self.neighbors.append(gnb)

    def to_dict(self):
        return {
            'id':               self.id,
            'x':                self.x,
            'y':                self.y,
            'tx_power_dbm':     self.tx_power_dbm,
            'antenna_gain_db':  self.antenna_gain_db,
            'num_sectors':      self.num_sectors,
            'height':           self.height,
            'is_anchor':        self.is_anchor,       # NEW — GUI uses this
            'connected_ues':    len(self.connected_ues),
            'total_throughput': round(self.total_throughput, 2),
            'sectors': [{'id': s['id'], 'azimuth': s['azimuth']}
                        for s in self.sectors],
            'active': self.active,
        }
