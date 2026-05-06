"""5G NR Scheduler"""
import math
class Scheduler:
    def __init__(self, bandwidth_mhz=100, scs_khz=30):
        self.bandwidth_mhz=bandwidth_mhz; self.scs_khz=scs_khz
        total_subcarriers=int(bandwidth_mhz*1e6/(scs_khz*1000))
        self.n_rb=total_subcarriers//12; self.slot_duration_ms=0.5
        self.slots_per_subframe=2; self.overhead_factor=0.86
    def allocate_resources(self, ues_metrics):
        if not ues_metrics: return {}
        weights={}; total_weight=0
        for ue_id,metrics in ues_metrics.items():
            instant_rate=metrics.get('instant_rate',1); avg_rate=max(metrics.get('avg_rate',1),0.1)
            pf_weight=instant_rate/avg_rate; weights[ue_id]=pf_weight; total_weight+=pf_weight
        allocations={}
        for ue_id,weight in weights.items():
            rb_share=int((weight/total_weight)*self.n_rb) if total_weight>0 else self.n_rb//len(ues_metrics)
            allocations[ue_id]=max(1,rb_share)
        return allocations
    def calculate_rb_throughput(self, rb_count, sinr_db, mimo_layers=4):
        sinr_linear=10**(sinr_db/10); bits_per_re=math.log2(1+sinr_linear)*self.overhead_factor
        re_per_slot=12*14; bits_per_slot=bits_per_re*re_per_slot*rb_count*mimo_layers
        slots_per_sec=1000/self.slot_duration_ms
        return min((bits_per_slot*slots_per_sec)/1e6, 500)
