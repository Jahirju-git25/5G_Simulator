"""
5G NR Network Simulator - Flask Backend
REST API + SSE for real-time updates
"""
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
import threading
import time
import json
import csv
import io
import os

from simulation import NetworkSimulator

app = Flask(__name__)
app.config['SECRET_KEY'] = '5gnr_simulator_secret'

simulator = NetworkSimulator()

# In-memory store for uploaded CSV mobility traces  { ue_id_str: [{t,x,y}, ...] }
mobility_traces = {}


# ─────────────────────────────────────────────
#  REST API Routes
# ─────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/api/add_gnb', methods=['POST'])
def add_gnb():
    data = request.json
    gnb_id = simulator.add_gnb(
        x=data.get('x', 400),
        y=data.get('y', 300),
        tx_power=data.get('tx_power', 43),
        num_sectors=data.get('num_sectors', 1)
    )
    return jsonify({'success': True, 'gnb_id': gnb_id})


@app.route('/api/add_ue', methods=['POST'])
def add_ue():
    data     = request.json
    mobility = data.get('mobility', 'random_waypoint')
    ue_id = simulator.add_ue(
        x=data.get('x', 200),
        y=data.get('y', 200),
        mobility=mobility,
        speed=data.get('speed', 3.0)
    )
    # If file_based, inject the parsed CSV trace into the newly created UE
    if mobility == 'file_based' and mobility_traces:
        with simulator.lock:
            ue = simulator.ues.get(ue_id)
            if ue:
                # Use trace keyed to this UE's id, or first available trace
                trace = (mobility_traces.get(ue_id) or
                         next(iter(mobility_traces.values())))
                ue.mobility._file_trace = trace
                ue.mobility._file_ue_id = ue_id
                ue.mobility._file_idx   = 0
                ue.mobility._file_time  = 0.0
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
    data     = request.json or {}
    scenario = data.get('scenario', 'UMa')
    speed    = data.get('speed', 1.0)

    simulator.set_channel_config(
        pathloss_model  = data.get('pathloss_model'),
        scenario        = scenario,
        log_dist_n      = data.get('log_dist_n'),
        log_dist_shadow = data.get('log_dist_shadow'),
        fading_model    = data.get('fading_model'),
    )
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
    data     = request.json
    scenario = data.get('scenario', 'UMa')
    simulator.set_scenario(scenario)
    return jsonify({'success': True, 'scenario': scenario})


@app.route('/api/set_channel_config', methods=['POST'])
def set_channel_config():
    """
    Configure pathloss model, shadowing, and fading.
    Body (all fields optional):
      pathloss_model  : '3GPP' | 'LogDistance'
      scenario        : 'UMa' | 'UMi' | 'RMa'   (3GPP only)
      log_dist_n      : float 1.6–6.0             (LogDistance only)
      log_dist_shadow : 'lognormal' | 'none'      (LogDistance only)
      fading_model    : 'Rayleigh'
    """
    data = request.json or {}
    simulator.set_channel_config(
        pathloss_model  = data.get('pathloss_model'),
        scenario        = data.get('scenario'),
        log_dist_n      = data.get('log_dist_n'),
        log_dist_shadow = data.get('log_dist_shadow'),
        fading_model    = data.get('fading_model'),
    )
    return jsonify({'success': True})


@app.route('/api/set_speed', methods=['POST'])
def set_speed():
    data  = request.json
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
#  CSV Mobility Trace Upload
# ─────────────────────────────────────────────

@app.route('/api/upload_mobility_csv', methods=['POST'])
def upload_mobility_csv():
    """
    Accept a CSV file with columns:
        time_stamp, Ue_ID, x_cord, y_cord
    Parses and stores traces in memory, grouped by Ue_ID.
    Returns a summary of parsed rows per UE.
    """
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file in request'}), 400

    f = request.files['file']
    if f.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'}), 400

    try:
        content = f.read().decode('utf-8')
        reader  = csv.DictReader(io.StringIO(content))
        raw_rows = list(reader)

        if not raw_rows:
            return jsonify({'success': False, 'error': 'CSV is empty'}), 400

        # Validate headers (case-insensitive, strip whitespace)
        EXPECTED = {'time_stamp', 'ue_id', 'x_cord', 'y_cord'}
        actual   = {k.strip().lower() for k in raw_rows[0].keys()}
        missing  = EXPECTED - actual
        if missing:
            return jsonify({
                'success': False,
                'error': f'Missing columns: {", ".join(sorted(missing))}'
            }), 400

        parsed = {}
        for row in raw_rows:
            norm  = {k.strip().lower(): v.strip() for k, v in row.items()}
            ue_id = norm['ue_id']
            try:
                entry = {
                    't': float(norm['time_stamp']),
                    'x': float(norm['x_cord']),
                    'y': float(norm['y_cord']),
                }
            except ValueError as e:
                return jsonify({'success': False, 'error': f'Parse error in row: {e}'}), 400
            parsed.setdefault(ue_id, []).append(entry)

        # Sort each UE trace by timestamp
        for ue_id, rows in parsed.items():
            parsed[ue_id] = sorted(rows, key=lambda r: r['t'])

        mobility_traces.clear()
        mobility_traces.update(parsed)

        summary = {ue_id: len(rows) for ue_id, rows in parsed.items()}
        return jsonify({
            'success':  True,
            'ue_count': len(parsed),
            'rows':     summary,
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────
#  Server-Sent Events (SSE) for real-time updates
# ─────────────────────────────────────────────

@app.route('/api/stream')
def stream():
    def event_generator():
        while True:
            try:
                state = simulator.get_state()
                data  = json.dumps(state)
                yield f"data: {data}\n\n"
                time.sleep(0.2)
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(1)

    return Response(
        stream_with_context(event_generator()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':               'no-cache',
            'X-Accel-Buffering':           'no',
            'Access-Control-Allow-Origin': '*',
        }
    )


if __name__ == '__main__':
    print("=" * 60)
    print("  5G NR Network Simulator")
    print("  Starting at http://localhost:8080")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
