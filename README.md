# V20

Web control page for a Siemens SINAMICS V20 drive, connected over Modbus to an S7-1200 (CPU 1214C DC/DC/DC).

A Python server talks to the PLC directly over S7 (python-snap7) and serves the page, so the PLC web server is not needed.

## Features

- Start, stop, reverse and fault reset
- Speed setpoint (0–50 Hz)
- Live actual frequency, running/fault/direction from the drive status word
- Speed graph (actual vs. setpoint, last 1/5/10 minutes)
- CSV logging: one data row per second plus an event log (start/stop, faults, direction and setpoint changes, connection loss), also for changes made from the HMI

## PLC requirements

- IP `192.168.0.1` (change `PLC_IP` in `app.py` if different)
- PLC properties → Protection & Security: **Full access** and **Permit access with PUT/GET communication from remote partner**, then download the hardware configuration
- `Read_Master_DB` (DB1) and `Write_Master_DB` (DB2) with **optimized block access off**

| DB | Offset | Tag | Used for |
|----|--------|-----|----------|
| DB1 | 0 | Actual_freq_analog (Int) | actual speed, 16#4000 = 50 Hz |
| DB1 | 2 | Actual_freq_Hz (Real) | actual speed in Hz (used if filled) |
| DB1 | 8 | ZSW1 (status word) | running, fault, direction |
| DB2 | 0 | Control_Word1 (STW1) | start/stop/reverse/fault ack |
| DB2 | 2 | Setpoint Freq_Hz (Real) | speed setpoint |

Control word: `047E` = ready/stopped, `047F` = run, bit 11 = reverse, bit 7 = fault acknowledge.

## Run

```
pip install -r requirements.txt
python3 app.py
```

Open http://localhost:5000 (or `http://<pc-ip>:5000` from another device on the network).

Logs are written to `logs/` (`v20_data_YYYY-MM-DD.csv` and `v20_events_YYYY-MM-DD.csv`, `;` separated with comma decimals for Excel).

## plc-webserver/

An alternative version that runs on the S7-1200's own web server as user-defined pages (AWP), without a PC. See the comments in `Web_Commands.scl` for the matching PLC logic. Not tested on the PLC.

## Safety

The web page is not an emergency stop. Keep a hardwired E-stop that does not depend on the PLC, network or this software.
