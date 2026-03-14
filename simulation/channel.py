"""
5G NR Channel Model
Supports:
  - 3GPP TR 38.901 (UMa, UMi, RMa) with log-normal shadow fading
  - Log Distance pathloss model with optional log-normal shadowing
Fading: Rayleigh (selectable, extendable later)
"""
import math
import random
import numpy as np


class ChannelModel:
    """Channel Model supporting 3GPP TR 38.901 and Log Distance"""

    # Radio parameters
    FREQ_GHZ = 3.5
    FREQ_HZ = 3.5e9
    BANDWIDTH_HZ = 100e6
    K_BOLTZMANN = 1.38e-23
    TEMP_KELVIN = 290
    NOISE_FIGURE_DB = 7
    SPEED_OF_LIGHT = 3e8

    # Log Distance reference distance (1 m)
    LOG_DIST_D0 = 1.0
    LOG_DIST_SIGMA_DB = 8.0   # typical log-normal shadowing std-dev

    def __init__(self, scenario='UMa', pathloss_model='3GPP',
                 log_dist_n=3.5, log_dist_shadow='lognormal',
                 fading_model='Rayleigh'):
        self.scenario        = scenario
        self.pathloss_model  = pathloss_model          # '3GPP' | 'LogDistance'
        self.log_dist_n      = float(log_dist_n)       # 1.6 – 6.0
        self.log_dist_shadow = log_dist_shadow          # 'lognormal' | 'none'
        self.fading_model    = fading_model             # 'Rayleigh'
        self.thermal_noise_dbm = self._calculate_thermal_noise()

    # ─────────────────────────────────────────
    #  Public interface
    # ─────────────────────────────────────────

    def calculate_pathloss(self, distance_m, gnb_height=25, ue_height=1.5):
        """Return (pathloss_dB, is_los) tuple"""
        if distance_m < 1:
            distance_m = 1

        if self.pathloss_model == 'LogDistance':
            return self._log_distance_pathloss(distance_m)

        # 3GPP TR 38.901
        if self.scenario == 'UMa':
            return self._uma_pathloss(distance_m, gnb_height, ue_height)
        elif self.scenario == 'UMi':
            return self._umi_pathloss(distance_m, gnb_height, ue_height)
        elif self.scenario == 'RMa':
            return self._rma_pathloss(distance_m, gnb_height, ue_height)
        else:
            return self._free_space_pathloss(distance_m)

    # ─────────────────────────────────────────
    #  Log Distance Model
    # ─────────────────────────────────────────

    def _log_distance_pathloss(self, distance_m):
        """
        Log Distance Pathloss Model
        PL(d) = PL(d0) + 10·n·log10(d/d0) + Xσ

        PL(d0) = free-space loss at d0 = 1 m (Friis)
        n      = pathloss exponent (user-configurable, 1.6–6.0)
        Xσ     = Gaussian(0, σ=8 dB) if shadow='lognormal', else 0
        """
        d0 = self.LOG_DIST_D0
        n  = self.log_dist_n

        # Free-space loss at d0 (Friis formula)
        pl_d0 = 20 * math.log10(4 * math.pi * d0 * self.FREQ_HZ / self.SPEED_OF_LIGHT)

        # Log-distance path loss
        pl = pl_d0 + 10 * n * math.log10(distance_m / d0)

        # Optional log-normal shadowing
        if self.log_dist_shadow == 'lognormal':
            pl += random.gauss(0, self.LOG_DIST_SIGMA_DB)

        # Fading
        pl += self._apply_fading()

        return pl, True   # No LOS/NLOS distinction in log-distance

    # ─────────────────────────────────────────
    #  3GPP TR 38.901 Models
    # ─────────────────────────────────────────

    def _uma_pathloss(self, d_2d, h_bs=25, h_ut=1.5):
        """3GPP TR 38.901 Urban Macro (UMa) — Table 7.4.1-1"""
        fc = self.FREQ_GHZ
        c  = self.SPEED_OF_LIGHT

        h_e        = 1.0
        h_bs_prime = h_bs - h_e
        h_ut_prime = h_ut - h_e

        d_bp = 4 * h_bs_prime * h_ut_prime * self.FREQ_HZ / c
        d_3d = math.sqrt(d_2d**2 + (h_bs - h_ut)**2)

        if d_2d <= 18:
            p_los = 1.0
        else:
            p_los = (18/d_2d + math.exp(-d_2d/63) * (1 - 18/d_2d)) * \
                    (1 + 1.25*(5/4)*(d_2d/100)**3 * math.exp(-d_2d/150) if h_ut >= 13 else 1)

        is_los = random.random() < p_los

        if is_los:
            if d_2d <= d_bp:
                pl = 28.0 + 22*math.log10(d_3d) + 20*math.log10(fc)
            else:
                pl = 28.0 + 40*math.log10(d_3d) + 20*math.log10(fc) \
                     - 9*math.log10(d_bp**2 + (h_bs - h_ut)**2)
            sigma = 4.0
        else:
            pl_nlos = 13.54 + 39.08*math.log10(d_3d) + 20*math.log10(fc) - 0.6*(h_ut - 1.5)
            pl_los  = 28.0  + 22*math.log10(d_3d)    + 20*math.log10(fc)
            pl      = max(pl_nlos, pl_los)
            sigma   = 6.0

        pl += random.gauss(0, sigma) + self._apply_fading()
        return pl, is_los

    def _umi_pathloss(self, d_2d, h_bs=10, h_ut=1.5):
        """3GPP TR 38.901 Urban Micro (UMi) Street Canyon — Table 7.4.1-1"""
        fc = self.FREQ_GHZ
        c  = self.SPEED_OF_LIGHT

        h_e        = 1.0
        h_bs_prime = h_bs - h_e
        h_ut_prime = h_ut - h_e

        d_bp = 4 * h_bs_prime * h_ut_prime * self.FREQ_HZ / c
        d_3d = math.sqrt(d_2d**2 + (h_bs - h_ut)**2)

        if d_2d <= 18:
            p_los = 1.0
        else:
            p_los = 18/d_2d + math.exp(-d_2d/36) * (1 - 18/d_2d)

        is_los = random.random() < p_los

        if is_los:
            if d_2d <= d_bp:
                pl = 32.4 + 21*math.log10(d_3d) + 20*math.log10(fc)
            else:
                pl = 32.4 + 40*math.log10(d_3d) + 20*math.log10(fc) \
                     - 9.5*math.log10(d_bp**2 + (h_bs - h_ut)**2)
            sigma = 4.0
        else:
            pl_nlos = 35.3*math.log10(d_3d) + 22.4 + 21.3*math.log10(fc) - 0.3*(h_ut - 1.5)
            pl_los  = 32.4 + 21*math.log10(d_3d) + 20*math.log10(fc)
            pl      = max(pl_nlos, pl_los)
            sigma   = 7.82

        pl += random.gauss(0, sigma) + self._apply_fading()
        return pl, is_los

    def _rma_pathloss(self, d_2d, h_bs=35, h_ut=1.5, w=20, h=5):
        """3GPP TR 38.901 Rural Macro (RMa) — Table 7.4.1-1"""
        fc   = self.FREQ_GHZ
        d_3d = math.sqrt(d_2d**2 + (h_bs - h_ut)**2)
        d_bp = 2 * math.pi * h_bs * h_ut * self.FREQ_HZ / self.SPEED_OF_LIGHT

        if d_2d <= 10:
            p_los = 1.0
        else:
            p_los = math.exp(-(d_2d - 10) / 1000)

        is_los = random.random() < p_los

        if is_los:
            if d_2d <= d_bp:
                pl = 20*math.log10(40*math.pi*d_3d*fc/3) \
                     + min(0.03*h**1.72, 10)*math.log10(d_3d) \
                     - min(0.044*h**1.72, 14.77) \
                     + 0.002*math.log10(h)*d_3d
            else:
                pl = 20*math.log10(40*math.pi*d_bp*fc/3) \
                     + min(0.03*h**1.72, 10)*math.log10(d_bp) \
                     - min(0.044*h**1.72, 14.77) \
                     + 0.002*math.log10(h)*d_bp \
                     + 40*math.log10(d_3d / d_bp)
            sigma = 4.0
        else:
            pl = 161.04 - 7.1*math.log10(w) + 7.5*math.log10(h) \
                 - (24.37 - 3.7*(h/h_bs)**2)*math.log10(h_bs) \
                 + (43.42 - 3.1*math.log10(h_bs))*(math.log10(d_3d) - 3) \
                 + 20*math.log10(fc) \
                 - (3.2*(math.log10(11.75*h_ut))**2 - 4.97)
            sigma = 8.0

        pl += random.gauss(0, sigma) + self._apply_fading()
        return pl, is_los

    def _free_space_pathloss(self, distance_m):
        """Free space path loss (Friis)"""
        pl = 20 * math.log10(4 * math.pi * distance_m * self.FREQ_HZ / self.SPEED_OF_LIGHT)
        return pl + self._apply_fading(), True

    # ─────────────────────────────────────────
    #  Fading
    # ─────────────────────────────────────────

    def _apply_fading(self):
        """Return fading component in dB"""
        if self.fading_model == 'Rayleigh':
            return self._rayleigh_fading()
        return 0.0

    def _rayleigh_fading(self):
        """
        Rayleigh fast fading in dB.
        Clipped to ±6 dB so individual fading events don't dominate the
        link budget. The EMA smoothing in simulator._calculate_ue_metrics
        handles residual step-to-step variation, giving stable SINR colours
        that correctly reflect distance rather than pure random noise.
        """
        i = random.gauss(0, 1.0 / math.sqrt(2))
        q = random.gauss(0, 1.0 / math.sqrt(2))
        amplitude = math.sqrt(i**2 + q**2)
        if amplitude <= 0:
            amplitude = 1e-10
        fading_db = -20 * math.log10(amplitude)
        return max(-6.0, min(6.0, fading_db))

    # ─────────────────────────────────────────
    #  Link budget helpers (unchanged from original)
    # ─────────────────────────────────────────

    def _calculate_thermal_noise(self):
        noise_watts = self.K_BOLTZMANN * self.TEMP_KELVIN * self.BANDWIDTH_HZ
        noise_dbm   = 10 * math.log10(noise_watts * 1000)
        return noise_dbm + self.NOISE_FIGURE_DB

    def calculate_rsrp(self, tx_power_dbm, pathloss_db, antenna_gain_db=15):
        return tx_power_dbm + antenna_gain_db - pathloss_db

    def calculate_sinr(self, rsrp_dbm, interference_list_dbm):
        signal_linear = 10 ** (rsrp_dbm / 10)
        noise_linear  = 10 ** (self.thermal_noise_dbm / 10)
        total_interference = noise_linear
        for interf_dbm in interference_list_dbm:
            if interf_dbm > -150:
                total_interference += 10 ** (interf_dbm / 10)
        sinr_linear = signal_linear / total_interference
        return 10 * math.log10(max(sinr_linear, 1e-10))

    def calculate_throughput(self, sinr_db, bandwidth_hz=100e6, mimo_layers=4):
        sinr_linear       = 10 ** (sinr_db / 10)
        efficiency_factor = 0.75
        shannon_bps       = bandwidth_hz * math.log2(1 + sinr_linear) * efficiency_factor
        max_se            = 5.5
        practical_bps     = min(shannon_bps, max_se * bandwidth_hz * mimo_layers)
        mcs, modulation, code_rate = self._select_mcs(sinr_db)
        cqi_throughput    = self._cqi_throughput(sinr_db, bandwidth_hz)
        return cqi_throughput / 1e6, mcs, modulation

    def _select_mcs(self, sinr_db):
        if sinr_db < -3:   return 0,  'QPSK',   0.12
        elif sinr_db < 0:  return 1,  'QPSK',   0.19
        elif sinr_db < 3:  return 4,  'QPSK',   0.37
        elif sinr_db < 6:  return 7,  'QPSK',   0.60
        elif sinr_db < 9:  return 10, '16QAM',  0.45
        elif sinr_db < 12: return 15, '16QAM',  0.65
        elif sinr_db < 15: return 18, '64QAM',  0.55
        elif sinr_db < 20: return 22, '64QAM',  0.75
        else:              return 28, '64QAM',  0.93

    def _cqi_throughput(self, sinr_db, bandwidth_hz):
        cqi_table = [
            (-10, 1e6),  (-6,  2e6),  (-3,  5e6),  (0,   10e6),
            (3,  20e6),  (6,  40e6),  (9,  70e6),  (12, 110e6),
            (15, 160e6), (18, 220e6), (21, 280e6), (24, 350e6),
            (27, 420e6), (30, 480e6), (33, 550e6),
        ]
        throughput = 0
        for threshold, tp in cqi_table:
            if sinr_db >= threshold:
                throughput = tp
        return throughput

    def calculate_rsrq(self, rsrp_dbm, rssi_dbm):
        n_rb = 66
        return 10 * math.log10(n_rb) + rsrp_dbm - rssi_dbm

    def calculate_doppler(self, velocity_ms, angle_rad=0):
        return velocity_ms * self.FREQ_HZ * math.cos(angle_rad) / self.SPEED_OF_LIGHT
