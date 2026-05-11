"""
5G NR Network Simulator — Flask Backend
REST API + SSE real-time stream.

New endpoint: POST /api/add_anchor_gnb
  Creates a special-power AnchorGNB (TX=50 dBm, 6 sectors, is_anchor=True)
  at the requested canvas position. Returns {"gnb_id": "AnchorGNB-N"}.
"""
import json
import time
import os
import csv
import io

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from simulation import NetworkSimulator

app = Flask(__name__)
app.config['SECRET_KEY'] = '5gnr_simulator_secret'

simulator = NetworkSimulator()

# Store detector status for external ML detector queries
detector_status = {
    'evaluation_steps': 0,
    'active_anchors': [],
    'cost_benefit_rejections': 0,
    'false_positives': 0,
    'ue_count': 0,
    'errors': 0,
}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    return '', 204


# ── gNB / UE management ──────────────────────────────────────────────────────

@app.route('/api/add_gnb', methods=['POST'])
def add_gnb():
    d = request.json or {}
    gid = simulator.add_gnb(
        x=d.get('x', 400), y=d.get('y', 300),
        tx_power=d.get('tx_power', 43),
        num_sectors=d.get('num_sectors', 1))
    return jsonify({'success': True, 'gnb_id': gid})


@app.route('/api/add_anchor_gnb', methods=['POST'])
def add_anchor_gnb():
    """
    Add a new special-power AnchorGNB at the HO-density centroid.
    Called by the external ping-pong detector script.

    Body params (all optional with defaults):
      x, y          – canvas position
      tx_power      – default 50 dBm
      num_sectors   – default 6
      is_anchor     – flag for GUI (stored on gNB object)
      triggered_by  – UE id that triggered this (for logging)
      ho_count      – number of HOs that triggered this
    """
    d = request.json or {}
    x           = float(d.get('x', 400))
    y           = float(d.get('y', 300))
    tx_power    = int(d.get('tx_power', 50))
    num_sectors = int(d.get('num_sectors', 6))
    is_anchor   = bool(d.get('is_anchor', True))
    triggered_by = d.get('triggered_by', 'unknown')
    ho_count    = int(d.get('ho_count', 0))

    gid = simulator.add_anchor_gnb(
        x=x, y=y,
        tx_power=tx_power,
        num_sectors=num_sectors,
        is_anchor=is_anchor)

    simulator._log_event(
        f"[AnchorGNB] {gid} placed @ ({x:.0f},{y:.0f}) "
        f"TX={tx_power}dBm sectors={num_sectors} "
        f"triggered by {triggered_by} ({ho_count} HOs)")

    return jsonify({'success': True, 'gnb_id': gid, 'anchor_gnb_id': gid})


@app.route('/api/add_ue', methods=['POST'])
def add_ue():
    d = request.json or {}
    uid = simulator.add_ue(
        x=d.get('x', 200), y=d.get('y', 200),
        mobility=d.get('mobility', 'none'),
        speed=d.get('speed', 3.0))
    return jsonify({'success': True, 'ue_id': uid})


@app.route('/api/remove_gnb', methods=['POST'])
def remove_gnb():
    simulator.remove_gnb((request.json or {})['gnb_id'])
    return jsonify({'success': True})


@app.route('/api/remove_ue', methods=['POST'])
def remove_ue():
    simulator.remove_ue((request.json or {})['ue_id'])
    return jsonify({'success': True})


@app.route('/api/move_gnb', methods=['POST'])
def move_gnb():
    d = request.json or {}
    with simulator.lock:
        gnb = simulator.gnbs.get(d['gnb_id'])
        if gnb:
            gnb.x = d['x']; gnb.y = d['y']
    return jsonify({'success': True})


@app.route('/api/move_ue', methods=['POST'])
def move_ue():
    d = request.json or {}
    with simulator.lock:
        ue = simulator.ues.get(d['ue_id'])
        if ue:
            ue.x = d['x']; ue.y = d['y']
            ue.mobility.x = d['x']; ue.mobility.y = d['y']
    return jsonify({'success': True})


@app.route('/api/set_ue_mobility', methods=['POST'])
def set_ue_mobility():
    d = request.json or {}
    uid = d.get('ue_id')
    if not uid:
        return jsonify({'success': False, 'error': 'ue_id required'}), 400
    with simulator.lock:
        ue = simulator.ues.get(uid)
        if not ue:
            return jsonify({'success': False, 'error': 'UE not found'}), 404
        model    = d.get('mobility', ue.mobility.model_type)
        speed    = float(d.get('speed', ue.mobility.speed))
        old_x, old_y, old_bounds = ue.mobility.x, ue.mobility.y, ue.mobility.bounds
        from simulation.mobility import MobilityModel
        kwargs = dict(speed=speed, bounds=old_bounds)
        if model == 'file_based':
            kwargs['file_trace'] = getattr(ue.mobility, '_file_trace', [])
            kwargs['file_ue_id'] = getattr(ue.mobility, '_file_ue_id', None)
        ue.mobility = MobilityModel(old_x, old_y, model_type=model, **kwargs)
    return jsonify({'success': True, 'ue_id': uid, 'mobility': model, 'speed': speed})


@app.route('/api/upload_mobility_trace', methods=['POST'])
def upload_mobility_trace():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    raw = request.files['file'].read()
    if raw[:2] == b'PK':
        return jsonify({'success': False,
                        'error': 'Upload plain CSV, not Excel'}), 400
    content = raw.decode('utf-8-sig', errors='replace')
    text_io = io.StringIO(content, newline='')
    try:
        sample = text_io.read(4096); text_io.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        except csv.Error:
            dialect = csv.get_dialect('excel')
        reader = csv.DictReader(text_io, dialect=dialect, skipinitialspace=True)
        rows_by_ue: dict = {}
        for row in reader:
            if not row: continue
            uid = None
            for k, v in row.items():
                if k and k.strip().lower() == 'ue_id':
                    uid = str(v).strip(); break
            x_val = y_val = t_val = None
            for k, v in row.items():
                if v is None: continue
                key = (k or '').strip().lower(); val = str(v).strip()
                if not val: continue  # Skip empty values
                if key == 'x':   x_val = float(val)
                elif key == 'y': y_val = float(val)
                elif key in ('t','time','timestamp'): t_val = float(val)
            if uid is None or x_val is None or y_val is None: continue
            rows_by_ue.setdefault(uid, [])
            t = t_val if t_val is not None else len(rows_by_ue[uid])*1.0
            rows_by_ue[uid].append({'t':t,'x':x_val,'y':y_val})
    except Exception as e:
        return jsonify({'success': False, 'error': f'CSV parse error: {e}'}), 400
    if not rows_by_ue:
        return jsonify({'success': False,
                        'error': 'No valid rows. Need: UE_ID, x, y'}), 400
    applied = []; skipped = []
    from simulation.mobility import MobilityModel
    speed = float(request.form.get('speed', 3.0))
    with simulator.lock:
        for uid, trace in rows_by_ue.items():
            ue = simulator.ues.get(uid)
            if not ue: skipped.append(uid); continue
            trace.sort(key=lambda r: r['t'])
            ue.mobility = MobilityModel(
                trace[0]['x'], trace[0]['y'],
                model_type='file_based', speed=speed,
                bounds=ue.mobility.bounds,
                file_trace=trace, file_ue_id=uid)
            ue.x = trace[0]['x']; ue.y = trace[0]['y']
            applied.append(uid)
    return jsonify({'success': True, 'applied': applied, 'skipped': skipped,
                    'message': f'Trace loaded for {len(applied)} UE(s).'})


# ── simulation control ────────────────────────────────────────────────────────

@app.route('/api/start_simulation', methods=['POST'])
def start_simulation():
    d = request.json or {}
    simulator.set_channel_config(
        pathloss_model  = d.get('pathloss_model'),
        scenario        = d.get('scenario', 'UMa'),
        log_dist_n      = d.get('log_dist_n'),
        log_dist_shadow = d.get('log_dist_shadow'),
        fading_model    = d.get('fading_model'),
    )
    simulator.speed_factor = float(d.get('speed', 1.0))
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


@app.route('/api/detector_status', methods=['GET'])
def get_detector_status():
    """Get current ML detector status (for test validation)."""
    global detector_status
    return jsonify(detector_status)


@app.route('/api/update_detector_status', methods=['POST'])
def update_detector_status():
    """Update detector status (called by external ML detector)."""
    global detector_status
    data = request.json or {}
    detector_status = {
        'evaluation_steps': data.get('evaluation_steps', detector_status.get('evaluation_steps', 0)),
        'active_anchors': data.get('active_anchors', detector_status.get('active_anchors', [])),
        'cost_benefit_rejections': data.get('cost_benefit_rejections', detector_status.get('cost_benefit_rejections', 0)),
        'false_positives': data.get('false_positives', detector_status.get('false_positives', 0)),
        'ue_count': data.get('ue_count', detector_status.get('ue_count', 0)),
        'errors': data.get('errors', detector_status.get('errors', 0)),
    }
    return jsonify({'success': True, 'message': 'Detector status updated'})


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
    d = request.json or {}
    simulator.set_scenario(d.get('scenario', 'UMa'))
    return jsonify({'success': True})


@app.route('/api/set_channel_config', methods=['POST'])
def set_channel_config():
    d = request.json or {}
    simulator.set_channel_config(
        pathloss_model  = d.get('pathloss_model'),
        scenario        = d.get('scenario'),
        log_dist_n      = d.get('log_dist_n'),
        log_dist_shadow = d.get('log_dist_shadow'),
        fading_model    = d.get('fading_model'),
    )
    return jsonify({'success': True})


@app.route('/api/set_speed', methods=['POST'])
def set_speed():
    speed = float((request.json or {}).get('speed', 1.0))
    simulator.speed_factor = speed
    return jsonify({'success': True, 'speed': speed})


@app.route('/api/set_params', methods=['POST'])
def set_params():
    d = request.json or {}
    if 'hysteresis' in d: simulator.hysteresis_db = float(d['hysteresis'])
    if 'ttt_steps'  in d: simulator.ttt_steps     = int(d['ttt_steps'])
    return jsonify({'success': True})


# ── anchor endpoints ──────────────────────────────────────────────────────────

@app.route('/api/anchor/status', methods=['GET'])
def anchor_status():
    return jsonify(simulator.anchor_manager.get_status_dict())


@app.route('/api/anchor/scores', methods=['GET'])
def anchor_scores():
    am = simulator.anchor_manager
    with am._lock:
        return jsonify({'anchor_gnb_id': am.anchor_gnb_id,
                        'scores': {k: round(v,4) for k,v in am._anchor_scores.items()}})


@app.route('/api/anchor/charts', methods=['GET'])
def anchor_charts():
    charts = sorted(
        [f for f in os.listdir('handover_charts') if f.endswith('.png')],
        reverse=True) if os.path.isdir('handover_charts') else []
    return jsonify({'charts': charts, 'count': len(charts)})


@app.route('/api/anchor/enable', methods=['POST'])
def anchor_enable():
    ok, msg = simulator.anchor_manager.enable()
    return jsonify({'success': ok, 'message': msg})


@app.route('/api/anchor/disable', methods=['POST'])
def anchor_disable():
    ok, msg = simulator.anchor_manager.disable()
    return jsonify({'success': ok, 'message': msg})


# ── SSE stream ────────────────────────────────────────────────────────────────

@app.route('/api/stream')
def stream():
    def events():
        while True:
            try:
                state = simulator.get_state()
                yield f"data: {json.dumps(state)}\n\n"
                time.sleep(0.2)
            except GeneratorExit:
                break
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(1)
    return Response(stream_with_context(events()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no',
                             'Access-Control-Allow-Origin': '*'})


if __name__ == '__main__':
    print("=" * 60)
    print("  5G NR Network Simulator  (Dynamic AnchorGNB enabled)")
    print("  Web UI  →  http://localhost:8080")
    print("  TCP HO  →  port 5555")
    print("=" * 60)
    app.run(host='0.0.0.0', port=8080, debug=False, threaded=True)
