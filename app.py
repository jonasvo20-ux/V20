"""V20 drive control page: talks to the S7-1200 directly over S7 (snap7), no PLC web server needed.

Run:  python app.py   then open http://localhost:5000
"""
import csv
import threading
import time
from collections import deque
from datetime import datetime
import os

DEMO = os.environ.get("DEMO_MODE") == "1"

if not DEMO:
    import snap7
    from snap7.util import get_bool, get_int, get_real, set_real

from flask import Flask, abort, jsonify, request, send_from_directory

PLC_IP = "192.168.0.1"
RACK, SLOT = 0, 1
READ_DB = 1   # Read_Master_DB
WRITE_DB = 2  # Write_Master_DB
MAX_HZ = 50.0
POLL_S = 0.3
HISTORY_S = 10 * 60   # graph history kept in memory
LOG_INTERVAL_S = 1.0  # one CSV data row per second
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# Control word 1 (STW1). Byte 0 = bits 8-15, byte 1 = bits 0-7 (matches Control_Word1 in DB2).
STW_STOP = 0x047E   # control from PLC + Off2/Off3/pulse/RFG/setpoint enable, On/Off1 = 0
STW_ON = 0x0001     # On/Off1 (bit 0)
STW_ACK = 0x0080    # fault acknowledge (bit 7)
STW_REV = 0x0800    # reversing (bit 11)

app = Flask(__name__, static_folder="static")
plc = None if DEMO else snap7.client.Client()
lock = threading.Lock()
status = {"online": False}
history = deque(maxlen=int(HISTORY_S / POLL_S) + 10)  # (time, actual Hz, setpoint Hz)
events = deque(maxlen=50)
last_log = 0.0
prev = {}
demo_state = {
    "running": True,
    "fault": False,
    "reverse_cmd": False,
    "setpoint_hz": None,
}


def demo_status(now=None):
    """Return a stable fake drive state for static/demo rendering."""
    now = time.time() if now is None else now
    setpoint = demo_state["setpoint_hz"]
    if setpoint is None:
        setpoint = 32.0 + 2.0 * ((now / 20.0) % 1.0)
    freq_hz = max(0.0, setpoint - 1.2) if demo_state["running"] else 0.0
    return {
        "online": True,
        "demo": True,
        "freq_hz": round(freq_hz, 2),
        "freq_raw": int(freq_hz / MAX_HZ * 0x4000),
        "running": demo_state["running"],
        "fault": demo_state["fault"],
        "forward": not demo_state["reverse_cmd"],
        "status_word": "0404",
        "temperature": 41.5,
        "pressure": 2.35,
        "setpoint_hz": round(setpoint, 2),
        "control_word": "0C7F" if demo_state["reverse_cmd"] else "047F",
        "reverse_cmd": demo_state["reverse_cmd"],
    }


if DEMO:
    status = demo_status()
    now = time.time()
    for index in range(120):
        sample_time = now - (120 - index) * POLL_S
        sample = demo_status(sample_time)
        history.append((round(sample_time, 2), sample["freq_hz"], sample["setpoint_hz"]))
    events.append({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": "Demo mode active"})

DATA_FIELDS = ["time", "freq_hz", "setpoint_hz", "running", "fault", "forward", "status_word", "control_word"]


def ensure_connected():
    if DEMO:
        return
    if not plc.get_connected():
        plc.connect(PLC_IP, RACK, SLOT)


def update_control_word(set_bits=0, clear_bits=0, toggle_bits=0):
    """Read Control_Word1, change only the given bits, write it back. Base bits are always set."""
    if DEMO:
        return
    with lock:
        ensure_connected()
        word = int.from_bytes(plc.db_read(WRITE_DB, 0, 2), "big")
        word = ((word | STW_STOP | set_bits) & ~clear_bits) ^ toggle_bits
        plc.db_write(WRITE_DB, 0, bytearray(word.to_bytes(2, "big")))


def write_setpoint(hz):
    if DEMO:
        return
    buf = bytearray(4)
    set_real(buf, 0, hz)
    with lock:
        ensure_connected()
        plc.db_write(WRITE_DB, 2, buf)  # Setpoint Freq_Hz


def append_csv(kind, fields, row):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, "v20_%s_%s.csv" % (kind, datetime.now().strftime("%Y-%m-%d")))
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if new:
            w.writerow(fields)
        w.writerow(row)


def log_event(text):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    events.appendleft({"time": now, "text": text})
    append_csv("events", ["time", "event"], [now, text])


def decimal(v):
    # Comma decimals so Excel with Belgian/Dutch settings opens the CSV correctly
    return ("%.2f" % v).replace(".", ",")


def record(st):
    """Graph history, CSV data row, and events on state changes (from web, HMI or PLC)."""
    global last_log, prev
    now = time.time()
    if not st["online"]:
        if prev.get("online", True):
            log_event("PLC connection lost")
        prev = {"online": False}
        return
    history.append((round(now, 2), st["freq_hz"], st["setpoint_hz"]))

    if prev.get("online") is False:
        log_event("PLC connection restored")
    elif prev:
        if st["running"] != prev["running"]:
            log_event("Drive started" if st["running"] else "Drive stopped")
        if st["fault"] != prev["fault"]:
            log_event("FAULT (status word %s)" % st["status_word"] if st["fault"] else "Fault cleared")
        if st["reverse_cmd"] != prev["reverse_cmd"]:
            log_event("Direction: reverse" if st["reverse_cmd"] else "Direction: forward")
        if st["setpoint_hz"] != prev["setpoint_hz"]:
            log_event("Setpoint %.1f Hz -> %.1f Hz" % (prev["setpoint_hz"], st["setpoint_hz"]))
    else:
        log_event("Logging started")
    prev = st

    if now - last_log >= LOG_INTERVAL_S:
        last_log = now
        append_csv("data", DATA_FIELDS, [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            decimal(st["freq_hz"]), decimal(st["setpoint_hz"]),
            int(st["running"]), int(st["fault"]), int(st["forward"]),
            st["status_word"], st["control_word"],
        ])


def poll_loop():
    global status
    while True:
        try:
            if DEMO:
                status = demo_status()
                time.sleep(POLL_S)
                continue
            with lock:
                ensure_connected()
                r = plc.db_read(READ_DB, 0, 24)
                w = plc.db_read(WRITE_DB, 0, 6)
            # Status word 1 from the drive (ZSW1, DB1 bytes 8-9, byte 8 = bits 8-15)
            zsw = int.from_bytes(r[8:10], "big")
            freq_raw = get_int(r, 0)
            freq_hz = get_real(r, 2)
            if freq_hz == 0 and freq_raw != 0:
                freq_hz = freq_raw * MAX_HZ / 0x4000  # 16#4000 = 100 % = 50 Hz
            status = {
                "online": True,
                "freq_hz": round(freq_hz, 2),
                "freq_raw": freq_raw,
                "running": bool(zsw & (1 << 2)),   # operation enabled
                "fault": bool(zsw & (1 << 3)),     # fault present
                "forward": bool(zsw & (1 << 14)),  # motor rotates forward
                "status_word": "%04X" % zsw,
                "temperature": round(get_real(r, 12), 1),
                "pressure": round(get_real(r, 20), 2),
                "setpoint_hz": round(get_real(w, 2), 2),
                "control_word": "%04X" % int.from_bytes(w[0:2], "big"),
                "reverse_cmd": bool(w[0] & 0x08),  # bit 11 = byte 0, bit 3
            }
            record(status)
        except Exception as e:
            status = {"online": False, "error": str(e)}
            record(status)
            try:
                plc.disconnect()
            except Exception:
                pass
            time.sleep(2)
        time.sleep(POLL_S)


def command(fn):
    try:
        fn()
        return jsonify(ok=True)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


def demo_write_response(update=None):
    if update:
        update()
    return jsonify(ok=True, demo=True, message="Demo write ignored")


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/status.json")
def api_status():
    if DEMO:
        return jsonify(demo_status())
    return jsonify(status)


@app.route("/api/history.json")
def api_history():
    return jsonify(list(history))


@app.route("/api/events.json")
def api_events():
    return jsonify(list(events))


@app.route("/api/logs.json")
def api_logs():
    files = sorted(os.listdir(LOG_DIR), reverse=True) if os.path.isdir(LOG_DIR) else []
    return jsonify([f for f in files if f.endswith(".csv")])


@app.route("/logs/<name>")
def download_log(name):
    if not name.endswith(".csv"):
        abort(404)
    return send_from_directory(LOG_DIR, name, as_attachment=True)


@app.route("/api/start", methods=["POST"])
def api_start():
    if DEMO:
        return demo_write_response(lambda: demo_state.update(running=True))
    return command(lambda: update_control_word(set_bits=STW_ON))


@app.route("/api/stop", methods=["POST"])
def api_stop():
    if DEMO:
        return demo_write_response(lambda: demo_state.update(running=False))
    return command(lambda: update_control_word(clear_bits=STW_ON))


@app.route("/api/reset", methods=["POST"])
def api_reset():
    if DEMO:
        return demo_write_response(lambda: demo_state.update(fault=False))
    def pulse():
        update_control_word(set_bits=STW_ACK)
        time.sleep(0.3)
        update_control_word(clear_bits=STW_ACK)
    return command(pulse)


@app.route("/api/reverse", methods=["POST"])
def api_reverse():
    if DEMO:
        return demo_write_response(lambda: demo_state.update(reverse_cmd=not demo_state["reverse_cmd"]))
    return command(lambda: update_control_word(toggle_bits=STW_REV))


@app.route("/api/setpoint", methods=["POST"])
def api_setpoint():
    if DEMO:
        try:
            hz = float(request.get_json(force=True).get("hz", 0))
        except (TypeError, ValueError):
            return jsonify(ok=False, error="invalid value"), 400
        hz = max(0.0, min(MAX_HZ, hz))
        return demo_write_response(lambda: demo_state.update(setpoint_hz=hz))
    try:
        hz = float(request.get_json(force=True).get("hz", 0))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="invalid value"), 400
    hz = max(0.0, min(MAX_HZ, hz))
    return command(lambda: write_setpoint(hz))


if __name__ == "__main__":
    if not DEMO:
        threading.Thread(target=poll_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
