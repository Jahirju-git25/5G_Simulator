"""
5G NR Channel Model - 3GPP TR 38.901 Based
Implements UMa, UMi, RMa pathloss models with shadow fading
"""
import math
import random
import numpy as np


class ChannelModel:
    """3GPP TR 38.901 Channel Model for 5G NR"""

    # Radio parameters
    FREQ_GHZ = 3.5          # Carrier frequency in GHz
    FREQ_HZ = 3.5e9         # Carrier frequency in Hz
    BANDWIDTH_HZ = 100e6    # 100 MHz bandwidth
    K_BOLTZMANN = 1.38e-23  # Boltzmann constant
    TEMP_KELVIN = 290        # Room temperature
    NOISE_FIGURE_DB = 7      # UE noise figure
    SPEED_OF_LIGHT = 3e8

    def __init__(self, scenario='UMa'):
        self.scenario = scenario
        self.thermal_noise_dbm = self._calculate_thermal_noise()

    def _calculate_thermal_noise(self):
        """Thermal noise power in dBm: N = kTB"""
        noise_watts = self.K_BOLTZMANN * self.TEMP_KELVIN * self.BANDWIDTH_HZ
        noise_dbm = 10 * math.log10(noise_watts * 1000)
        return noise_dbm + self.NOISE_FIGURE_DB

    def calculate_pathloss(self, distance_m, gnb_height=25, ue_height=1.5):
        """Calculate pathloss based on scenario"""
        if distance_m < 1:
            distance_m = 1

        if self.scenario == 'UMa':
            return self._uma_pathloss(distance_m, gnb_height, ue_height)
        elif self.scenario == 'UMi':
            return self._umi_pathloss(distance_m, gnb_height, ue_height)
        elif self.scenario == 'RMa':
            return self._rma_pathloss(distance_m, gnb_height, ue_height)
        else:
            return self._free_space_pathloss(distance_m)

    def _uma_pathloss(self, d_2d, h_bs=25, h_ut=1.5):
        """
        3GPP TR 38.901 Urban Macro (UMa) Pathloss
        Table 7.4.1-1
        """
        fc = self.FREQ_GHZ
        c = self.SPEED_OF_LIGHT
        
        # 3D distance calculation
        h_e = 1.0  # effective environment height (simplified)
        h_bs_prime = h_bs - h_e
        h_ut_prime = h_ut - h_e
        
        d_bp = 4 * h_bs_prime * h_ut_prime * self.FREQ_HZ / c
        d_3d = math.sqrt(d_2d**2 + (h_bs - h_ut)**2)

        # LOS probability
        if d_2d <= 18:
            p_los = 1.0
        else:
            p_los = (18/d_2d + math.exp(-d_2d/63) * (1 - 18/d_2d)) * \
                    (1 + 1.25 * (5/4) * (d_2d/100)**3 * math.exp(-d_2d/150) if h_ut >= 13 else 1)
        
        is_los = random.random() < p_los

        if is_los:
            # UMa LOS
            if d_2d <= d_bp:
                pl = 28.0 + 22 * math.log10(d_3d) + 20 * math.log10(fc)
            else:
                pl = 28.0 + 40 * math.log10(d_3d) + 20 * math.log10(fc) - \
                     9 * math.log10(d_bp**2 + (h_bs - h_ut)**2)
            sigma = 4.0  # LOS shadow fading std dev
        else:
            # UMa NLOS
            pl_nlos = 13.54 + 39.08 * math.log10(d_3d) + 20 * math.log10(fc) - \
                      0.6 * (h_ut - 1.5)
            pl_los = 28.0 + 22 * math.log10(d_3d) + 20 * math.log10(fc)
            pl = max(pl_nlos, pl_los)
            sigma = 6.0  # NLOS shadow fading std dev

        # Shadow fading (log-normal)
        shadow = random.gauss(0, sigma)
        return pl + shadow, is_los

    def _umi_pathloss(self, d_2d, h_bs=10, h_ut=1.5):
        """
        3GPP TR 38.901 Urban Micro (UMi) - Street Canyon
        Table 7.4.1-1
        """
        fc = self.FREQ_GHZ
        c = self.SPEED_OF_LIGHT
        
        h_e = 1.0
        h_bs_prime = h_bs - h_e
        h_ut_prime = h_ut - h_e
        
        d_bp = 4 * h_bs_prime * h_ut_prime * self.FREQ_HZ / c
        d_3d = math.sqrt(d_2d**2 + (h_bs - h_ut)**2)

        # LOS probability for UMi
        if d_2d <= 18:
            p_los = 1.0
        else:
            p_los = 18/d_2d + math.exp(-d_2d/36) * (1 - 18/d_2d)
        
        is_los = random.random() < p_los

        if is_los:
            if d_2d <= d_bp:
                pl = 32.4 + 21 * math.log10(d_3d) + 20 * math.log10(fc)
            else:
                pl = 32.4 + 40 * math.log10(d_3d) + 20 * math.log10(fc) - \
                     9.5 * math.log10(d_bp**2 + (h_bs - h_ut)**2)
            sigma = 4.0
        else:
            # UMi NLOS - Street canyon effect
            pl_nlos = 35.3 * math.log10(d_3d) + 22.4 + 21.3 * math.log10(fc) - \
                      0.3 * (h_ut - 1.5)
            pl_los = 32.4 + 21 * math.log10(d_3d) + 20 * math.log10(fc)
            pl = max(pl_nlos, pl_los)
            sigma = 7.82

        # Fast fading for UMi (Rayleigh)
        fast_fading = self._rayleigh_fading()
        shadow = random.gauss(0, sigma)
        return pl + shadow + fast_fading, is_los

    def _rma_pathloss(self, d_2d, h_bs=35, h_ut=1.5, w=20, h=5):
        """
        3GPP TR 38.901 Rural Macro (RMa)
        Table 7.4.1-1
        """
        fc = self.FREQ_GHZ
        d_3d = math.sqrt(d_2d**2 + (h_bs - h_ut)**2)
        
        # Break point distance
        d_bp = 2 * math.pi * h_bs * h_ut * self.FREQ_HZ / self.SPEED_OF_LIGHT

        # LOS probability for RMa
        if d_2d <= 10:
            p_los = 1.0
        else:
            p_los = math.exp(-(d_2d - 10) / 1000)
        
        is_los = random.random() < p_los

        if is_los:
            if d_2d <= d_bp:
                pl = 20 * math.log10(40 * math.pi * d_3d * fc / 3) + \
                     min(0.03 * h**1.72, 10) * math.log10(d_3d) - \
                     min(0.044 * h**1.72, 14.77) + 0.002 * math.log10(h) * d_3d
            else:
                pl = 20 * math.log10(40 * math.pi * d_bp * fc / 3) + \
                     min(0.03 * h**1.72, 10) * math.log10(d_bp) - \
                     min(0.044 * h**1.72, 14.77) + 0.002 * math.log10(h) * d_bp + \
                     40 * math.log10(d_3d / d_bp)
            sigma = 4.0
        else:
            # RMa NLOS
            pl = 161.04 - 7.1 * math.log10(w) + 7.5 * math.log10(h) - \
                 (24.37 - 3.7 * (h/h_bs)**2) * math.log10(h_bs) + \
                 (43.42 - 3.1 * math.log10(h_bs)) * (math.log10(d_3d) - 3) + \
                 20 * math.log10(fc) - (3.2 * (math.log10(11.75 * h_ut))**2 - 4.97)
            sigma = 8.0

        shadow = random.gauss(0, sigma)
        return pl + shadow, is_los

    def _free_space_pathloss(self, distance_m):
        """Free space path loss (Friis formula)"""
        fc = self.FREQ_HZ
        pl = 20 * math.log10(4 * math.pi * distance_m * fc / self.SPEED_OF_LIGHT)
        return pl, True

    def _rayleigh_fading(self):
        """Rayleigh fast fading component in dB"""
        # Generate Rayleigh amplitude
        amplitude = math.sqrt(random.gauss(0,1)**2 + random.gauss(0,1)**2) / math.sqrt(2)
        if amplitude > 0:
            return -20 * math.log10(amplitude)
        return 0

    def calculate_rsrp(self, tx_power_dbm, pathloss_db, antenna_gain_db=15):
        """Reference Signal Received Power"""
        return tx_power_dbm + antenna_gain_db - pathloss_db

    def calculate_sinr(self, rsrp_dbm, interference_list_dbm):
        """SINR = Signal / (Interference + Noise)"""
        # Convert signal to linear
        signal_linear = 10 ** (rsrp_dbm / 10)
        
        # Convert noise to linear
        noise_linear = 10 ** (self.thermal_noise_dbm / 10)
        
        # Sum interference in linear
        total_interference = noise_linear
        for interf_dbm in interference_list_dbm:
            if interf_dbm > -150:  # Valid interference
                total_interference += 10 ** (interf_dbm / 10)
        
        sinr_linear = signal_linear / total_interference
        sinr_db = 10 * math.log10(max(sinr_linear, 1e-10))
        return sinr_db

    def calculate_throughput(self, sinr_db, bandwidth_hz=100e6, mimo_layers=4):
        """Shannon capacity with practical MCS mapping"""
        # Shannon capacity: C = B * log2(1 + SINR)
        sinr_linear = 10 ** (sinr_db / 10)
        
        # Apply efficiency factor (not all RBs used, overhead)
        efficiency_factor = 0.75
        
        shannon_bps = bandwidth_hz * math.log2(1 + sinr_linear) * efficiency_factor
        
        # MIMO gain (imperfect, scaled)
        mimo_gain = math.log2(1 + mimo_layers * 0.7)
        
        # Apply MCS ceiling (max 64QAM practical ~5.5 bits/s/Hz)
        max_spectral_efficiency = 5.5  # bits/s/Hz for 64QAM 5/6
        practical_bps = min(shannon_bps, max_spectral_efficiency * bandwidth_hz * mimo_layers)
        
        # MCS selection based on SINR
        mcs, modulation, code_rate = self._select_mcs(sinr_db)
        
        # CQI-based throughput
        cqi_throughput = self._cqi_throughput(sinr_db, bandwidth_hz)
        
        return cqi_throughput / 1e6, mcs, modulation  # Return in Mbps

    def _select_mcs(self, sinr_db):
        """MCS selection table"""
        if sinr_db < -3:
            return 0, 'QPSK', 0.12
        elif sinr_db < 0:
            return 1, 'QPSK', 0.19
        elif sinr_db < 3:
            return 4, 'QPSK', 0.37
        elif sinr_db < 6:
            return 7, 'QPSK', 0.60
        elif sinr_db < 9:
            return 10, '16QAM', 0.45
        elif sinr_db < 12:
            return 15, '16QAM', 0.65
        elif sinr_db < 15:
            return 18, '64QAM', 0.55
        elif sinr_db < 20:
            return 22, '64QAM', 0.75
        else:
            return 28, '64QAM', 0.93

    def _cqi_throughput(self, sinr_db, bandwidth_hz):
        """CQI-based throughput calculation - fixed thresholds"""
        # CQI table: (min_sinr_dB, throughput_bps)
        # Realistic 5G NR 100MHz 4x4 MIMO values
        cqi_table = [
            (-10, 1e6),    # CQI 1:  QPSK  ~1 Mbps
            (-6,  2e6),    # CQI 2:  QPSK  ~2 Mbps
            (-3,  5e6),    # CQI 3:  QPSK  ~5 Mbps
            (0,   10e6),   # CQI 4:  QPSK  ~10 Mbps
            (3,   20e6),   # CQI 5:  QPSK  ~20 Mbps
            (6,   40e6),   # CQI 6:  16QAM ~40 Mbps
            (9,   70e6),   # CQI 7:  16QAM ~70 Mbps
            (12,  110e6),  # CQI 8:  16QAM ~110 Mbps
            (15,  160e6),  # CQI 9:  64QAM ~160 Mbps
            (18,  220e6),  # CQI 10: 64QAM ~220 Mbps
            (21,  280e6),  # CQI 11: 64QAM ~280 Mbps
            (24,  350e6),  # CQI 12: 64QAM ~350 Mbps
            (27,  420e6),  # CQI 13: 256QAM ~420 Mbps
            (30,  480e6),  # CQI 14: 256QAM ~480 Mbps
            (33,  550e6),  # CQI 15: 256QAM ~550 Mbps
        ]

        throughput = 0
        for threshold, tp in cqi_table:
            if sinr_db >= threshold:
                throughput = tp

        # 4x4 MIMO spatial multiplexing gain (already baked in above values)
        return throughput

    def calculate_rsrq(self, rsrp_dbm, rssi_dbm):
        """Reference Signal Received Quality"""
        n_rb = 66  # Resource blocks
        return 10 * math.log10(n_rb) + rsrp_dbm - rssi_dbm

    def calculate_doppler(self, velocity_ms, angle_rad=0):
        """Doppler frequency shift"""
        fd = velocity_ms * self.FREQ_HZ * math.cos(angle_rad) / self.SPEED_OF_LIGHT
        return fd
