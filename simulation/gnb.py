"""
5G NR gNB (gNodeB) - Base Station
Supports 3-sector configuration
"""
import math


class gNB:
    """5G NR Base Station with sectorization"""

    gnb_counter = 0

    def __init__(self, x, y, tx_power_dbm=43, antenna_gain_db=15, num_sectors=1):
        gNB.gnb_counter += 1
        self.id = f"gNB-{gNB.gnb_counter}"
        self.x = x
        self.y = y
        self.tx_power_dbm = tx_power_dbm
        self.antenna_gain_db = antenna_gain_db
        self.num_sectors = num_sectors
        self.height = 25  # meters (UMa default)
        
        # Sector azimuths (3-sector: 0°, 120°, 240°)
        self.sectors = []
        for i in range(num_sectors):
            azimuth = i * (360 / num_sectors)
            self.sectors.append({
                'id': f"{self.id}-S{i+1}",
                'azimuth': azimuth,
                'half_power_bw': 65,  # degrees
                'active_ues': []
            })
        
        # Connected UEs
        self.connected_ues = []
        
        # Metrics
        self.total_throughput = 0
        self.active = True
        
        # Xn interface (neighboring gNBs)
        self.neighbors = []

    def distance_to(self, x, y):
        """Calculate 2D distance to a point"""
        return math.sqrt((self.x - x)**2 + (self.y - y)**2)

    def get_sector_for_ue(self, ue_x, ue_y):
        """Determine which sector a UE belongs to"""
        angle_rad = math.atan2(ue_y - self.y, ue_x - self.x)
        angle_deg = math.degrees(angle_rad) % 360

        best_sector = 0
        min_diff = 360
        for i, sector in enumerate(self.sectors):
            diff = abs(angle_deg - sector['azimuth'])
            if diff > 180:
                diff = 360 - diff
            if diff < min_diff:
                min_diff = diff
                best_sector = i
        return best_sector

    def get_sector_gain(self, ue_x, ue_y):
        """Omni antenna = uniform gain in all directions"""
        return self.antenna_gain_db

    def add_neighbor(self, gnb):
        """Add Xn interface neighbor"""
        if gnb not in self.neighbors:
            self.neighbors.append(gnb)

    def to_dict(self):
        return {
            'id': self.id,
            'x': self.x,
            'y': self.y,
            'tx_power_dbm': self.tx_power_dbm,
            'antenna_gain_db': self.antenna_gain_db,
            'num_sectors': self.num_sectors,
            'height': self.height,
            'connected_ues': len(self.connected_ues),
            'total_throughput': round(self.total_throughput, 2),
            'sectors': [{'id': s['id'], 'azimuth': s['azimuth']} for s in self.sectors],
            'active': self.active
        }
