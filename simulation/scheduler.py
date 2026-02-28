"""
5G NR Scheduler - Resource Block Allocation
Implements Proportional Fair scheduling
"""
import math


class Scheduler:
    """NR Resource Block Scheduler"""

    def __init__(self, bandwidth_mhz=100, scs_khz=30):
        self.bandwidth_mhz = bandwidth_mhz
        self.scs_khz = scs_khz
        
        # Calculate number of resource blocks
        # One RB = 12 subcarriers
        subcarrier_spacing_hz = scs_khz * 1000
        total_subcarriers = int(bandwidth_mhz * 1e6 / subcarrier_spacing_hz)
        self.n_rb = total_subcarriers // 12
        
        # Slot duration: 14 OFDM symbols per slot, 0.5ms per slot for 30kHz SCS
        self.slot_duration_ms = 0.5
        self.slots_per_subframe = 2
        
        # Overhead
        self.overhead_factor = 0.86  # Accounts for DMRS, CSI-RS, etc.
        
    def allocate_resources(self, ues_metrics):
        """
        Proportional Fair scheduling
        Returns RB allocation per UE
        """
        if not ues_metrics:
            return {}
        
        # PF metric: current_rate / average_rate
        allocations = {}
        total_weight = 0
        weights = {}
        
        for ue_id, metrics in ues_metrics.items():
            instant_rate = metrics.get('instant_rate', 1)
            avg_rate = metrics.get('avg_rate', 1)
            if avg_rate < 0.1:
                avg_rate = 0.1
            pf_weight = instant_rate / avg_rate
            weights[ue_id] = pf_weight
            total_weight += pf_weight
        
        # Allocate RBs proportionally
        for ue_id, weight in weights.items():
            if total_weight > 0:
                rb_share = int((weight / total_weight) * self.n_rb)
            else:
                rb_share = self.n_rb // len(ues_metrics)
            allocations[ue_id] = max(1, rb_share)
        
        return allocations

    def calculate_rb_throughput(self, rb_count, sinr_db, mimo_layers=4):
        """Calculate throughput for given RB allocation"""
        sinr_linear = 10 ** (sinr_db / 10)
        
        # Bits per RE per layer
        bits_per_re = math.log2(1 + sinr_linear) * self.overhead_factor
        
        # REs per slot per RB
        re_per_slot_per_rb = 12 * 14  # 12 subcarriers * 14 symbols
        
        # Throughput per slot
        bits_per_slot = bits_per_re * re_per_slot_per_rb * rb_count * mimo_layers
        
        # Scale to Mbps
        slots_per_second = 1000 / self.slot_duration_ms
        throughput_mbps = (bits_per_slot * slots_per_second) / 1e6
        
        # Cap at practical maximum
        max_throughput = 500  # Mbps for 4x4 MIMO 100MHz
        return min(throughput_mbps, max_throughput)
