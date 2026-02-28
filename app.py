"""
5G NR Network Simulator - Flask Backend
REST API + SSE for real-time updates
"""
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
import threading
import time
import json
import os

from simulation import NetworkSimulator

app = Flask(__name__)
app.config['SECRET_KEY'] = '5gnr_simulator_secret'

# Global simulator instance
simulator = NetworkSimulator()


# ─────────────────────────────────────────────
#  REST API Routes
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/add_gnb', methods=['POST'])
def add_gnb():
    data = request.json
    gnb_id = simulator.add_gnb(
        x=data.get('x', 400),
        y=data.get('y', 300),
        tx_power=data.get('tx_power', 43),
        num_sectors=data.get('num_sectors', 3)
    )
    return jsonify({'success': True, 'gnb_id': gnb_id})


@app.route('/api/add_ue', methods=['POST'])
def add_ue():
    data = request.json
    ue_id = simulator.add_ue(
        x=data.get('x', 200),
        y=data.get('y', 200),
        mobility=data.get('mobility', 'random_waypoint'),
        speed=data.get('speed', 3.0)
    )
    return jsonify({'success': True, 'ue_id': ue_id})


@app.route('/api/remove_gnb', methods=['POST'])
def remove_gnb():
    data = request.json
    simulator.remove_gnb(data['gnb_id'])
    return jsonify({'success': True})


@app.route('/api/remove_ue', methods=['POST'])
def remove_ue():
    data = request.json
    simulator.remove_ue(data['ue_id'])
    return jsonify({'success': True})

@app.route('/api/move_gnb', methods=['POST'])
def move_gnb():
    data = request.json
    with simulator.lock:
        gnb = simulator.gnbs.get(data['gnb_id'])
        if gnb:
            gnb.x = data['x']
            gnb.y = data['y']
    return jsonify({'success': True})


@app.route('/api/move_ue', methods=['POST'])
def move_ue():
    data = request.json
    with simulator.lock:
        ue = simulator.ues.get(data['ue_id'])
        if ue:
            ue.x = data['x']
            ue.y = data['y']
            ue.mobility.x = data['x']
            ue.mobility.y = data['y']
    return jsonify({'success': True})

@app.route('/api/start_simulation', methods=['POST'])
def start_simulation():
    data = request.json or {}
    scenario = data.get('scenario', 'UMa')
    speed = data.get('speed', 1.0)
    simulator.set_scenario(scenario)
    simulator.speed_factor = float(speed)
    simulator.start()
    return jsonify({'success': True, 'message': 'Simulation started'})


@app.route('/api/stop_simulation', methods=['POST'])
def stop_simulation():
    simulator.stop()
    return jsonify({'success': True, 'message': 'Simulation stopped'})


@app.route('/api/reset', methods=['POST'])
def reset_simulation():
    simulator.reset()
    return jsonify({'success': True, 'message': 'Simulation reset'})


@app.route('/api/get_state', methods=['GET'])
def get_state():
    return jsonify(simulator.get_state())


@app.route('/api/get_metrics', methods=['GET'])
def get_metrics():
    return jsonify({'metrics': simulator.get_metrics()})


@app.route('/api/simulate_step', methods=['POST'])
def simulate_step():
    simulator.simulate_step()
    return jsonify(simulator.get_state())


@app.route('/api/get_handover_details', methods=['GET'])
def get_handover_details():
    return jsonify({'handovers': simulator.get_handover_details()})


@app.route('/api/get_throughput', methods=['GET'])
def get_throughput():
    return jsonify({'throughput': simulator.get_throughput()})


@app.route('/api/set_scenario', methods=['POST'])
def set_scenario():
    data = request.json
    scenario = data.get('scenario', 'UMa')
    simulator.set_scenario(scenario)
    return jsonify({'success': True, 'scenario': scenario})


@app.route('/api/set_speed', methods=['POST'])
def set_speed():
    data = request.json
    speed = float(data.get('speed', 1.0))
    simulator.speed_factor = speed
    return jsonify({'success': True, 'speed': speed})


@app.route('/api/set_params', methods=['POST'])
def set_params():
    data = request.json
    if 'hysteresis' in data:
        simulator.hysteresis_db = float(data['hysteresis'])
    if 'ttt_steps' in data:
        simulator.ttt_steps = int(data['ttt_steps'])
    return jsonify({'success': True})


# ─────────────────────────────────────────────
#  Server-Sent Events (SSE) for real-time updates
# ─────────────────────────────────────────────

@app.route('/api/stream')
def stream():
    """SSE endpoint for real-time state updates"""
    def event_generator():
        while True:
            try:
                state = simulator.get_state()
                data = json.dumps(state)
                yield f"data: {data}\n\n"
                time.sleep(0.2)  # 5 Hz updates
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(1)

    return Response(
        stream_with_context(event_generator()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*'
        }
    )


if __name__ == '__main__':
    print("=" * 60)
    print("  5G NR Network Simulator")
    print("  Starting at http://localhost:8080")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
