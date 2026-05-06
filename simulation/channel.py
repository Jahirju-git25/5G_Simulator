"""5G NR Channel Model"""
import math, random
try:
    import numpy as np
except ImportError:
    pass

class ChannelModel:
    FREQ_GHZ=3.5; FREQ_HZ=3.5e9; BANDWIDTH_HZ=100e6; K_BOLTZMANN=1.38e-23
    TEMP_KELVIN=290; NOISE_FIGURE_DB=7; SPEED_OF_LIGHT=3e8; LOG_DIST_D0=1.0; LOG_DIST_SIGMA_DB=8.0
    def __init__(self, scenario='UMa', pathloss_model='3GPP', log_dist_n=3.5, log_dist_shadow='lognormal', fading_model='Rayleigh'):
        self.scenario=scenario; self.pathloss_model=pathloss_model; self.log_dist_n=float(log_dist_n)
        self.log_dist_shadow=log_dist_shadow; self.fading_model=fading_model
        self.thermal_noise_dbm=self._calculate_thermal_noise()
    def calculate_pathloss(self, distance_m, gnb_height=25, ue_height=1.5):
        if distance_m<1: distance_m=1
        if self.pathloss_model=='LogDistance': return self._log_distance_pathloss(distance_m)
        if self.scenario=='UMa': return self._uma_pathloss(distance_m, gnb_height, ue_height)
        elif self.scenario=='UMi': return self._umi_pathloss(distance_m, gnb_height, ue_height)
        elif self.scenario=='RMa': return self._rma_pathloss(distance_m, gnb_height, ue_height)
        return self._free_space_pathloss(distance_m)
    def calculate_sinr(self, rsrp_dbm, interference_list_dbm, noise_figure_db=7):
        signal_mw=10**(rsrp_dbm/10); noise_mw=10**(self.thermal_noise_dbm/10)*10**(noise_figure_db/10)
        interf_mw=sum(10**(i/10) for i in interference_list_dbm) if interference_list_dbm else 0
        sinr_linear=signal_mw/(noise_mw+interf_mw+1e-15)
        return max(-20,min(40,10*math.log10(sinr_linear)))
    def calculate_throughput(self, sinr_db):
        mcs_index,modulation,code_rate=self._sinr_to_mcs(sinr_db)
        throughput=self._cqi_throughput(sinr_db, self.BANDWIDTH_HZ)
        return throughput/1e6, mcs_index, modulation
    def calculate_rsrq(self, rsrp_dbm, rssi_dbm): return 10*math.log10(66)+rsrp_dbm-rssi_dbm
    def calculate_doppler(self, velocity_ms, angle_rad=0): return velocity_ms*self.FREQ_HZ*math.cos(angle_rad)/self.SPEED_OF_LIGHT
    def _log_distance_pathloss(self, distance_m):
        d0=self.LOG_DIST_D0; pl_d0=20*math.log10(4*math.pi*d0*self.FREQ_HZ/self.SPEED_OF_LIGHT)
        pl=pl_d0+10*self.log_dist_n*math.log10(distance_m/d0)
        if self.log_dist_shadow=='lognormal': pl+=random.gauss(0,self.LOG_DIST_SIGMA_DB)
        pl+=self._apply_fading(); return pl, True
    def _uma_pathloss(self, d_2d, h_bs=25, h_ut=1.5):
        fc=self.FREQ_GHZ; c=self.SPEED_OF_LIGHT; h_e=1.0
        h_bs_prime=h_bs-h_e; h_ut_prime=h_ut-h_e; d_bp=4*h_bs_prime*h_ut_prime*self.FREQ_HZ/c
        d_3d=math.sqrt(d_2d**2+(h_bs-h_ut)**2)
        p_los=1.0 if d_2d<=18 else (18/d_2d+math.exp(-d_2d/63)*(1-18/d_2d))
        is_los=random.random()<p_los
        if is_los:
            pl=28.0+22*math.log10(d_3d)+20*math.log10(fc) if d_2d<=d_bp else 28.0+40*math.log10(d_3d)+20*math.log10(fc)-9*math.log10(d_bp**2+(h_bs-h_ut)**2)
            sigma=4.0
        else:
            pl_nlos=13.54+39.08*math.log10(d_3d)+20*math.log10(fc)-0.6*(h_ut-1.5)
            pl=max(pl_nlos,28.0+22*math.log10(d_3d)+20*math.log10(fc)); sigma=6.0
        pl+=random.gauss(0,sigma)+self._apply_fading(); return pl, is_los
    def _umi_pathloss(self, d_2d, h_bs=10, h_ut=1.5):
        fc=self.FREQ_GHZ; c=self.SPEED_OF_LIGHT; h_e=1.0
        d_bp=4*(h_bs-h_e)*(h_ut-h_e)*self.FREQ_HZ/c; d_3d=math.sqrt(d_2d**2+(h_bs-h_ut)**2)
        p_los=1.0 if d_2d<=18 else 18/d_2d+math.exp(-d_2d/36)*(1-18/d_2d)
        is_los=random.random()<p_los
        if is_los:
            pl=32.4+21*math.log10(d_3d)+20*math.log10(fc) if d_2d<=d_bp else 32.4+40*math.log10(d_3d)+20*math.log10(fc)-9.5*math.log10(d_bp**2+(h_bs-h_ut)**2)
            sigma=4.0
        else:
            pl_nlos=35.3*math.log10(d_3d)+22.4+21.3*math.log10(fc)-0.3*(h_ut-1.5)
            pl=max(pl_nlos,32.4+21*math.log10(d_3d)+20*math.log10(fc)); sigma=7.82
        pl+=random.gauss(0,sigma)+self._apply_fading(); return pl, is_los
    def _rma_pathloss(self, d_2d, h_bs=35, h_ut=1.5, w=20, h=5):
        fc=self.FREQ_GHZ; d_3d=math.sqrt(d_2d**2+(h_bs-h_ut)**2)
        d_bp=2*math.pi*h_bs*h_ut*self.FREQ_HZ/self.SPEED_OF_LIGHT
        p_los=1.0 if d_2d<=10 else math.exp(-(d_2d-10)/1000)
        is_los=random.random()<p_los
        if is_los:
            if d_2d<=d_bp: pl=20*math.log10(40*math.pi*d_3d*fc/3)+min(0.03*h**1.72,10)*math.log10(d_3d)-min(0.044*h**1.72,14.77)+0.002*math.log10(h)*d_3d
            else: pl=20*math.log10(40*math.pi*d_bp*fc/3)+min(0.03*h**1.72,10)*math.log10(d_bp)-min(0.044*h**1.72,14.77)+0.002*math.log10(h)*d_bp+40*math.log10(d_3d/d_bp)
            sigma=4.0
        else:
            pl=161.04-7.1*math.log10(w)+7.5*math.log10(h)-(24.37-3.7*(h/h_bs)**2)*math.log10(h_bs)+(43.42-3.1*math.log10(h_bs))*(math.log10(d_3d)-3)+20*math.log10(fc)-(3.2*(math.log10(11.75*h_ut))**2-4.97)
            sigma=8.0
        pl+=random.gauss(0,sigma)+self._apply_fading(); return pl, is_los
    def _free_space_pathloss(self, distance_m):
        pl=20*math.log10(4*math.pi*distance_m*self.FREQ_HZ/self.SPEED_OF_LIGHT); return pl+self._apply_fading(), True
    def _apply_fading(self):
        if self.fading_model=='Rayleigh': return self._rayleigh_fading()
        return 0.0
    def _rayleigh_fading(self):
        i=random.gauss(0,1); q=random.gauss(0,1); envelope=math.sqrt(i**2+q**2)
        if envelope<1e-10: return 0.0
        return max(-6.0,min(6.0,20*math.log10(envelope/math.sqrt(2))))
    def _sinr_to_mcs(self, sinr_db):
        if sinr_db<-6: return 1,'QPSK',0.08
        elif sinr_db<-3: return 2,'QPSK',0.15
        elif sinr_db<0: return 3,'QPSK',0.23
        elif sinr_db<3: return 5,'QPSK',0.38
        elif sinr_db<6: return 7,'QPSK',0.60
        elif sinr_db<9: return 10,'16QAM',0.45
        elif sinr_db<12: return 15,'16QAM',0.65
        elif sinr_db<15: return 18,'64QAM',0.55
        elif sinr_db<20: return 22,'64QAM',0.75
        else: return 28,'64QAM',0.93
    def _cqi_throughput(self, sinr_db, bandwidth_hz):
        cqi_table=[(-10,1e6),(-6,2e6),(-3,5e6),(0,10e6),(3,20e6),(6,40e6),(9,70e6),(12,110e6),(15,160e6),(18,220e6),(21,280e6),(24,350e6),(27,420e6),(30,480e6),(33,550e6)]
        throughput=0
        for threshold,tp in cqi_table:
            if sinr_db>=threshold: throughput=tp
        return throughput
    def _calculate_thermal_noise(self):
        noise_power=self.K_BOLTZMANN*self.TEMP_KELVIN*self.BANDWIDTH_HZ
        return 10*math.log10(noise_power)+30
