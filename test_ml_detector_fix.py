#!/usr/bin/env python3
"""
Test script to validate ML detector fix for ping-pong detection.

This script:
1. Loads the 8-UE multi-zone mobility CSV
2. Runs the simulator with the detector
3. Verifies handover_history is being sent by simulator
4. Checks that ML detector receives and processes HO events
5. Validates that anchors are deployed correctly

Usage:
    python3 test_ml_detector_fix.py --verbose
"""

import requests
import json
import time
import sys
from datetime import datetime

def colorize(text, color):
    """Print colored text."""
    colors = {
        'green': '\033[92m',
        'red': '\033[91m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'reset': '\033[0m'
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"

def test_simulator_connection(sim_url):
    """Test connection to simulator."""
    print(f"\n[TEST 1] Checking simulator connection...")
    try:
        resp = requests.get(f"{sim_url}/api/get_state", timeout=3.0)
        if resp.status_code == 200:
            print(colorize("✓ Simulator is reachable", 'green'))
            return True
        else:
            print(colorize(f"✗ Simulator returned status {resp.status_code}", 'red'))
            return False
    except Exception as e:
        print(colorize(f"✗ Connection failed: {e}", 'red'))
        return False

def load_mobility_csv(sim_url, csv_file):
    """Load mobility CSV into simulator."""
    print(f"\n[TEST 2] Loading mobility CSV: {csv_file}")
    try:
        # The simulator expects a file upload via /api/upload_mobility_trace
        with open(csv_file, 'rb') as f:
            files = {'file': f}
            data = {'speed': 3.0}
            
            resp = requests.post(
                f"{sim_url}/api/upload_mobility_trace",
                files=files,
                data=data,
                timeout=5.0
            )
        
        if resp.status_code == 200:
            result = resp.json()
            if result.get('success'):
                print(colorize(f"✓ CSV loaded successfully", 'green'))
                print(f"  Applied to: {result.get('applied', [])}")
                return True
            else:
                print(colorize(f"✗ Failed to load CSV: {result.get('error', 'Unknown error')}", 'red'))
                return False
        else:
            print(colorize(f"✗ Failed to load CSV (HTTP {resp.status_code}): {resp.text}", 'red'))
            return False
    except FileNotFoundError:
        print(colorize(f"✗ CSV file not found: {csv_file}", 'red'))
        return False
    except Exception as e:
        print(colorize(f"✗ Failed to load CSV: {e}", 'red'))
        return False

def check_handover_history(sim_url):
    """Check if simulator is sending handover_history in UE state."""
    print(f"\n[TEST 3] Checking if handover_history is in UE state...")
    try:
        resp = requests.get(f"{sim_url}/api/get_state", timeout=3.0)
        state = resp.json()
        
        ues = state.get('ues', {})
        if not ues:
            print(colorize("⚠ No UEs in simulation yet", 'yellow'))
            return False
        
        first_ue_id = list(ues.keys())[0]
        first_ue = ues[first_ue_id]
        
        if 'handover_history' in first_ue:
            ho_count = len(first_ue['handover_history'])
            print(colorize(f"✓ handover_history field present in UE state", 'green'))
            print(f"  Example UE: {first_ue_id}")
            print(f"  Handovers recorded: {ho_count}")
            
            if ho_count > 0:
                print(f"  Last HO: {first_ue['handover_history'][-1]}")
            return True
        else:
            print(colorize("✗ handover_history NOT in UE state", 'red'))
            print(f"  Available fields: {list(first_ue.keys())}")
            return False
    except Exception as e:
        print(colorize(f"✗ Error checking UE state: {e}", 'red'))
        return False

def check_feature_extraction(sim_url):
    """Check if detector is extracting features with valid handover data."""
    print(f"\n[TEST 4] Checking feature extraction...")
    try:
        resp = requests.get(f"{sim_url}/api/get_state", timeout=3.0)
        state = resp.json()
        
        ues = state.get('ues', {})
        if not ues:
            print(colorize("⚠ No UEs in simulation yet", 'yellow'))
            return False
        
        # Check all UEs for handover history
        ues_with_hos = 0
        for ue_id, ue in ues.items():
            ho_hist = ue.get('handover_history', [])
            if len(ho_hist) >= 2:
                ues_with_hos += 1
        
        print(f"  UEs with handovers: {ues_with_hos}/{len(ues)}")
        
        if ues_with_hos >= 4:
            print(colorize("✓ Sufficient HO data for feature extraction", 'green'))
            return True
        else:
            print(colorize("⚠ Limited HO data, detector needs more time", 'yellow'))
            return False
    except Exception as e:
        print(colorize(f"✗ Error: {e}", 'red'))
        return False

def check_detector_status(sim_url):
    """Check ML detector status."""
    print(f"\n[TEST 5] Checking ML detector status...")
    try:
        resp = requests.get(f"{sim_url}/api/detector_status", timeout=3.0)
        if resp.status_code == 404:
            print(colorize("⚠ Detector status endpoint not available", 'yellow'))
            return False
        
        status = resp.json()
        
        print(f"  Evaluation cycles: {status.get('evaluation_steps', 'N/A')}")
        print(f"  UEs tracked: {status.get('ue_count', 'N/A')}")
        print(f"  Active anchors: {len(status.get('active_anchors', []))}")
        print(f"  Cost-benefit rejections: {status.get('cost_benefit_rejections', 'N/A')}")
        
        # Print recent detector logs for debugging
        recent_logs = status.get('recent_logs', [])
        if recent_logs:
            print(f"\n  Recent detector events:")
            for log in recent_logs[-10:]:  # Last 10 events
                print(f"    - {log}")
        
        anchors = status.get('active_anchors', [])
        if anchors:
            print(colorize(f"✓ Anchors deployed: {len(anchors)}", 'green'))
            for anchor in anchors:
                print(f"    - {anchor.get('id', 'N/A')} at {anchor.get('centroid', 'N/A')}")
            return True
        else:
            print(colorize("⚠ No anchors deployed yet", 'yellow'))
            return False
    except Exception as e:
        print(colorize(f"✗ Error: {e}", 'red'))
        return False

def run_simulation(sim_url, duration=15):
    """Run simulation for a specified duration."""
    print(f"\n[TEST 6] Running simulation for {duration} seconds...")
    try:
        start_time = time.time()
        
        while time.time() - start_time < duration:
            resp = requests.get(f"{sim_url}/api/get_state", timeout=3.0)
            state = resp.json()
            
            sim_time = state.get('sim_time', 0.0)
            elapsed = time.time() - start_time
            
            print(f"  Sim time: {sim_time:.1f}s (elapsed: {elapsed:.1f}s)", end='\r')
            time.sleep(0.5)
        
        print(f"\n✓ Simulation completed {duration}s")
        return True
    except Exception as e:
        print(colorize(f"\n✗ Simulation error: {e}", 'red'))
        return False

def print_summary(results):
    """Print test summary."""
    print(f"\n{'='*70}")
    print("TEST SUMMARY")
    print(f"{'='*70}")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = colorize("✓ PASS", 'green') if passed_test else colorize("✗ FAIL", 'red')
        print(f"{status} {test_name}")
    
    print(f"\n{colorize(f'Result: {passed}/{total} tests passed', 'green' if passed == total else 'yellow')}")
    
    if passed == total:
        print(colorize("\n✓✓✓ ML Detector fix is working! Anchors should deploy shortly. ✓✓✓", 'green'))
    else:
        print(colorize("\n✗ Some tests failed. Check the output above.", 'red'))
    
    return passed == total

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Test ML detector fix')
    parser.add_argument('--simulator-url', default='http://localhost:8080',
                       help='Simulator base URL (default: http://localhost:8080)')
    parser.add_argument('--csv-file', 
                       default='d:\\dell pc\\Downloads\\5G_Simulator\\sample_8ue_multizone_mobility.csv',
                       help='Path to 8-UE mobility CSV')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    print(colorize("="*70, 'blue'))
    print(colorize("ML Detector Fix Validation", 'blue'))
    print(colorize("="*70, 'blue'))
    print(f"Simulator URL: {args.simulator_url}")
    print(f"CSV file: {args.csv_file}")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # Test 1: Connection
    if not test_simulator_connection(args.simulator_url):
        print(colorize("\n✗ Cannot continue without simulator connection", 'red'))
        return False
    results['Simulator connection'] = True
    
    # Test 2: Load CSV
    if not load_mobility_csv(args.simulator_url, args.csv_file):
        print(colorize("\n✗ Cannot continue without loading CSV", 'red'))
        return False
    results['Load mobility CSV'] = True
    
    # Give simulator time to generate some handovers
    print("\n⏳ Waiting 5 seconds for simulator to generate handover events...")
    time.sleep(5)
    
    # Test 3: Check handover_history
    results['Handover history in UE state'] = check_handover_history(args.simulator_url)
    
    # Test 4: Check feature extraction
    results['Feature extraction data'] = check_feature_extraction(args.simulator_url)
    
    # Run simulation for a bit
    time.sleep(3)
    
    # Test 5: Check detector status
    results['ML detector status'] = check_detector_status(args.simulator_url)
    
    # Print summary
    success = print_summary(results)
    
    print(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if not success:
        print(colorize("\n💡 Troubleshooting tips:", 'yellow'))
        print("  1. Check that app.py is running with simulator backend")
        print("  2. Check that ml_detector_external.py is running")
        print("  3. Verify simulator logs for errors")
        print("  4. Run with --verbose flag for more details")
    
    return success

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
