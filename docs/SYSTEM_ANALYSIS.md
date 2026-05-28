# ControlUSV — Critical System Analysis

*Independent top-down audit · 2026-05-20*

This document is the result of a focused critical review of the ControlUSV
codebase (backend + frontend) against its stated operating environment: a
single Raspberry Pi 4 on a shallow-water USV, 4G uplink in rural areas (poor
and intermittent signal), one commander as the active operator, optional
read-only viewers (not yet implemented), an ESP32 driving PWM motors and
relays, a UM982 RTK GNSS, a WT901 IMU, a PZEM-017 power meter.

The analysis is ordered top-down: **architecture → communication → failsafes
→ real-time → security → scalability → code-level**. Each finding has a
severity tag, a concrete file:line reference, and a recommendation. Findings
not already documented in the README "Bugs" / "In Development" tables are
flagged **NEW**. Confirmed defects are encoded in `tests/test_audit_findings.py`
(11 tests, all currently passing — they describe present, buggy behaviour and
will fail once the underlying issue is fixed).

Severity scale: **🔴 Critical** · **🟠 High** · **🟡 Medium** · **🟢 Low**.

---

## Executive Summary

The system is well-structured for a single-developer project: clean
five-process ZMQ pub/sub design, real Pydantic models, working watchdog,
documented bug log, and recent rounds of disciplined fixes (B-01..B-15).
Many things commonly missing in hobby vehicle stacks are *present*: motor
output gating by ARM, GNSS-failsafe latch, exponential-backoff process
restarts, server-side validation of GNC config, atomic-ish frontend reconnect
on zombie sockets.

However, the system in its current form **is not yet field-safe for the
stated operating profile**. The single most important reason is that the
"commander disconnect" failsafe — the one that matters most when 4G drops on
a lake — does not actually monitor the commander. It monitors the local
Manager process, which keeps publishing whether the link is up or not. The
second most important reason is that the persistence layer (which holds
`home_wp`, failsafe thresholds and GNC tuning) is written non-atomically, so
a brown-out during a save corrupts the file and the next boot silently
reverts to defaults — without an alert. The third is that the WebSocket
endpoint exposed through ngrok has no authentication: anyone who guesses the
public URL can ARM the vehicle.

### Top risks, ranked by field impact

| # | Risk | Severity | What goes wrong in the field |
|---|------|----------|------------------------------|
| 1 | **Comm-loss failsafe wired to wrong heartbeat** (NEW) | 🔴 | 4G drops mid-mission; commander goes blind; vehicle keeps running its current mission because the local Manager heartbeat is still ticking. |
| 2 | **Persistence is not atomic** (NEW) | 🔴 | Low battery → brown-out during a settings save → corrupted JSON → next boot loads defaults silently → `home_wp` lost, failsafe thresholds reset. |
| 3 | **No authentication on the public WS / ngrok URL** (NEW) | 🔴 | Anyone with the URL can ARM / SET_MODE / send MANUAL_INPUT. |
| 4 | **No ESP32 firmware-side dead-man's switch documented** (NEW) | 🟠 | If the Pi or the GNC process freezes between sends, motors keep running at the last commanded value for ≥ 3 s (Esp32Node reconnect window). |
| 5 | **No mission persistence** (D-02-adjacent) | 🟠 | Watchdog restart of GNCProcess mid-mission loses the waypoint list silently; vehicle disarms, drifts, and operator must re-upload. |

The rest of the document expands these and lists 30+ smaller findings.

---

## 1. Architecture-level findings

### 1.1 Five-process model is sound; one global authority is missing
**🟢 / observational.** The split (Manager · HAL · Navigation · GNC · Comms +
broker) is appropriate. State authority is mostly clean: Manager owns
config and mode; GNC owns control state; HAL owns hardware. The frontend
correctly defers to backend on config (B-09 fix).

What is missing is an explicit "vehicle health" state machine. ARM, mode,
station-active, route-active, sim-active and the various failsafe latches
are scattered across Manager and GNC; transitions are implicit. A reader of
`gnc/process.py` and `manager/process.py` has to mentally compose the truth
table to understand "can this command happen now?" — and the GNC ↔ Manager
sync uses `_source: 'gnc_internal'` payload tags that are easy to miss.

**Recommendation:** factor an explicit `VehicleState` enum (e.g.
`DISARMED_IDLE`, `DISARMED_FAULT`, `ARMED_MANUAL`, `ARMED_AUTO_ROUTE`,
`ARMED_AUTO_STATION`, `FAILSAFE_RTH`, `FAILSAFE_STATION`, `SIM`) owned by
Manager and broadcast every heartbeat. GNC consumes it as the single source
of truth instead of three separate booleans (`is_armed`, `wp_route_active`,
`station_active`).

### 1.2 GNCProcess publishes commands to itself via `COMMAND_USER`
**🟡 / NEW.** In `_emergency_stop`, `_failsafe_station_keeping` and
`_failsafe_return_home`, GNC publishes synthesized `CommandMessage`s back on
`command/user` to sync Manager. Manager and GNC both subscribe to
`command/user`, which means **GNC receives its own synthetic commands** and
re-processes them. This is currently harmless (the GNC handlers are
idempotent), but it's a footgun: the next person who adds a side-effect to a
GNC handler will discover it ten ways.

**File:** `src/gnc/process.py:832-846, 859-873, 895-899`.
**Recommendation:** route GNC→Manager sync over a dedicated
`gnc/internal_sync` topic (or add a `from_process` field to `CommandMessage`
and have GNC drop messages with `from_process == 'gnc'`).

### 1.3 Broker is a `daemon=True` subprocess
**🟡 / NEW.** `main.py:127` starts the ZMQ broker as a daemon — if main dies
violently, broker is killed but children stay up briefly, sending into a void.
Children re-publish on a re-connected socket once the broker comes back, but
nothing tracks the message gap. Combined with the lack of process-level
sequencing, an ARM/DISARM lost in the gap is gone forever.

**Recommendation:** put the broker under the same watchdog discipline as the
other services, or co-locate it inside the Manager process (the broker is
just `zmq.proxy` — it doesn't need its own multiprocessing).

### 1.4 The viewer/broadcast plane is undesigned
**🟡 / NEW.** The README and the user's stated architecture envisage *one
commander* connected to the USV plus *one or more read-only viewers* fed
from the commander's PC. None of this exists. The current WebSocket
endpoint is "open" — every connected client both receives telemetry and can
send commands. Adding viewers naively (just opening more browsers against
the same URL) creates N command-capable operators.

**Recommendation:** design this before it gets implemented ad-hoc. Three
viable shapes:
- (a) **WS topic split:** introduce `/ws/cmd` (auth-required, single
  connection enforced server-side) and `/ws/telemetry` (read-only). Viewers
  connect only to `/ws/telemetry`. The commander's browser connects to both.
- (b) **Commander-relay:** vehicle exposes only `/ws/cmd`; the commander PC
  runs a small relay process that re-broadcasts telemetry to LAN viewers
  over WebRTC or a separate WS. Keeps the vehicle's 4G upload at exactly one
  stream.
- (c) **Read-only proxy:** an nginx in front of the Pi exposes
  `read.<domain>` with `auth_request` rejecting WS frames that aren't
  pure-text-pong. Cheap but fragile.

I would recommend (b) for bandwidth reasons — 4G uplink is the bottleneck
and you don't want every viewer pulling from the vehicle.

---

## 2. Communication & sync findings

### 2.1 🔴 Comm-loss failsafe is bound to local heartbeat, not link liveness (NEW)
**File:** `src/gnc/process.py:281, 807-813`; `src/manager/process.py:90`;
`src/comms/web_server.py` (no offending line — the bug is the *absence* of
code).

`GNCProcess._consume_status` bumps `self.last_heartbeat_time = time.time()`
every time it receives `SYSTEM_STATUS`. `ManagerProcess` publishes
`SYSTEM_STATUS` at 10 Hz **unconditionally**, regardless of whether the
WebSocket has any clients connected. Therefore `_check_failsafes`'s
`now - self.last_heartbeat_time > fs.comm_timeout` branch can only trigger if
Manager itself is dead — but if Manager is dead, the watchdog will already
restart it and Manager-internal heartbeats resume, so the failsafe is
effectively dormant.

The user's risk model — *"unstable 4G in rural areas, the link can drop"* —
is exactly what this failsafe is documented to handle (`comm_timeout`,
`comm_action: station_keeping | return_home`). In its current form, **the
failsafe does not do what its name implies**.

**Reproduction:** disconnect the frontend from a running vehicle. The
backend continues to publish heartbeats internally; GNC never trips the
comm failsafe; if a mission was running, it continues.

**Fix (recommended):**
1. Add a counter `connected_ws_clients: int` to `ConnectionManager` and a
   small publisher in `web_server` that emits `{"ws_clients": N, "ts": ...}`
   on `system/status` every 1 s.
2. Either include `ws_clients` in Manager's heartbeat or have GNC subscribe
   directly to a new `comms/link` topic.
3. In `GNCProcess._consume_status` (or a new `_consume_link`), only bump
   `last_heartbeat_time` when `ws_clients >= 1` (or when an explicit ping
   from the frontend arrives).
4. Add an end-to-end uplink heartbeat from the frontend: every 1 s send a
   `{"type":"PING"}` over the WS that the backend translates into a
   `comms/link` event. This is the only way to detect WS half-open / NAT
   stuck connections (the OS-level TCP RST may take 2 minutes).

**Confirming test:** `tests/test_audit_findings.py::test_comm_failsafe_bound_to_local_manager_not_to_frontend_link`.

### 2.2 🔴 No authentication on the WebSocket endpoint (NEW)
**File:** `src/comms/web_server.py:169-183, 148-166`.

`@app.websocket("/ws")` accepts any connection and `process_incoming_command`
parses any payload that fits `CommandMessage`. Combined with the recently
added ngrok dynamic host detection (B-07), the vehicle is one URL away from
being remotely controlled.

**Mitigations, in order of effort:**
- (cheapest) Move the WS to a path with a random per-vehicle token
  (`/ws/<token>`) loaded from `data/manager_settings.json`; require the token
  on every connect; reject other paths with 404.
- (better) HMAC-sign every `CommandMessage` from the frontend with a shared
  secret; reject messages with bad signatures or stale timestamps (replay).
- (correct) Run the public surface (ngrok / Cloudflare Tunnel) behind a
  TLS-mutual-auth or OAuth proxy; the local LAN access stays open for
  development.

**Confirming test:** `test_websocket_endpoint_has_no_authentication`.

### 2.3 🟠 Commands have no sequence number / nonce / ack (NEW)
**File:** `src/core/models.py:91-97`.

`CommandMessage` has only `timestamp`, `type`, `payload`. There is no
sequence number, nonce, or vehicle-side ack. Consequences:
- A retransmitted ARM (frontend retried because UI didn't see status update)
  cannot be deduplicated.
- A command queued in a TCP buffer and re-delivered after a reconnect can
  re-fire an ARM.
- The frontend cannot tell which commands the vehicle actually received vs.
  which are still in flight on a flaky link.

**Recommendation:** add `seq: int` (monotonic per session) and `ack_seq` in
`system/status`. The frontend retries unacked commands; the backend dedups by
`(session_id, seq)`. This is the canonical pattern used in MAVLink and is
cheap to add.

**Confirming test:** `test_command_message_has_no_sequence_or_nonce`.

### 2.4 🟡 ZMQ default HWM may drop SYSTEM_STATUS on slow consumers (NEW)
**File:** `src/core/messaging.py:55-73, 75-86`.

Neither `Publisher` nor `Subscriber` sets `zmq.SNDHWM` / `zmq.RCVHWM`.
Default high-water-mark is 1000 messages. At 50 Hz HAL + 20 Hz GNC over a
slow consumer (e.g. WebSocket pumping over a saturated 4G uplink) this can
silently start dropping messages.

For PUB/SUB, ZMQ drops on the publisher side when HWM is reached — *silently*.
There is no log line, no alert. In the field, the symptom is "telemetry feels
jittery sometimes" with no explanation.

**Recommendation:** set explicit HWMs (e.g. `RCVHWM=200`, `SNDHWM=200` for
sensor topics; `SNDHWM=10` for `system/status`), and monitor drops with
`socket.getsockopt(zmq.EVENTS)` or by hashing message IDs.

### 2.5 🟡 Subscribers use `timeout_ms=0` polling busy-loops (NEW)
**File:** `src/manager/process.py:54-69`, `src/gnc/process.py:_consume_*`.

Manager and GNC drain their subscriber queues with `timeout_ms=0` inside a
`while True`, which on Windows/Linux yields zero-wait polls. The outer
ServiceProcess loop runs at 10/20 Hz with its own sleep, so this isn't a
busy spin in practice — but on a loaded Pi, the inner loops are not bounded:
if Manager is backed up and 500 commands arrive at once (e.g. on
reconnection), Manager will process all 500 inside one tick, missing its
sensor draining for that loop. Combined with point 2.4 (HWM defaults), this
can cause stale sensor data to flow into GNC.

**Recommendation:** cap inner drain loops (`for _ in range(50): ...`) so one
slow message can never starve sibling subscribers.

### 2.6 🟡 ngrok-served frontend caches stale `index.html` only via no-cache headers
The `serve_index` route sets `Cache-Control: no-cache, no-store,
must-revalidate` (good). But the static mount in line 432 inherits FastAPI
defaults for hashed assets — fine. However ngrok's free tier sometimes
re-encodes responses and ignores `Cache-Control` on intermediate CDN hops.
**Mitigation:** add an explicit `?v=<build_id>` query string to the
`<script>` reference in `index.html` so different builds bust caches reliably.

---

## 3. Failsafe & reliability findings

### 3.1 🔴 `manager_settings.json` is written non-atomically (NEW)
**File:** `src/manager/process.py:230-241`.

```python
with open(_SETTINGS_FILE, 'w') as f:    # truncates immediately
    json.dump({...}, f, indent=2)        # may crash / power-fail mid-write
```

Power loss between `open(... 'w')` and `f.close()` leaves a truncated /
empty file. `_load_settings` catches `json.JSONDecodeError` and silently
logs a *warning* (`logger.warning(...)`), then proceeds with `GncConfig()`
and `FailsafeConfig()` defaults — and `home_wp` becomes `None`. **The
operator is not alerted.**

For a vehicle that is *expected* to brown-out (the user explicitly named
"running out of battery" as a scenario), this is unacceptable.

**Fix:**
```python
# Atomic write
tmp = _SETTINGS_FILE + ".tmp"
with open(tmp, 'w') as f:
    json.dump(payload, f, indent=2)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, _SETTINGS_FILE)        # atomic on POSIX & Windows
```
And on load failure, publish a `system/status` alert at level=critical so
the frontend banner pops up, instead of a warning log no one will see.

**Confirming tests:** `test_settings_save_is_not_atomic`,
`test_settings_load_swallows_corrupted_file_silently`.

### 3.2 🟠 ESP32 link loss: no firmware dead-man's-switch documented
**File:** `src/drivers/esp32.py:43-58, 113-157`.

When `ESP32Driver.send_command` times out (200 ms), it raises;
`Esp32Node.run` catches it, **closes the serial port and reconnects after
3 s** (`_RETRY_INTERVAL = 3.0`). Between the timeout and the reconnect,
**no commands reach the firmware**. Unless the ESP32 firmware itself has a
heartbeat timeout that pulls M1/M2 to 0, the motors keep running at the last
value for ≥ 3 s. The README does not mention any firmware-side timeout, and
the project's `_old/` folder doesn't ship firmware.

**Recommendation:**
1. (Firmware) implement a 250 ms watchdog inside the ESP32: if no valid JSON
   has been received in 250 ms, zero M1/M2 and open R1 (motor relay). Send a
   `{"WDT":1}` notification so the Pi knows.
2. (Driver) on `TimeoutError`, before disconnecting, attempt an immediate
   resend (the ACK may have been corrupted, not the motor command). Only
   tear down on N consecutive timeouts.
3. (Driver) add an explicit "zero motors" send on `Esp32Node` shutdown and
   on outer-loop disconnect, *before* closing the port.

**Confirming tests:** `test_esp32_send_command_has_no_retry`,
`test_esp32_relays_hardwired_on`.

### 3.3 🟠 Mission state is not persisted (NEW; relates to D-02)
**File:** `src/manager/process.py:230-241` (only `gnc_config`,
`failsafe_config`, `home_wp` are saved).

The active waypoint list lives in `GNCProcess.wp_route_waypoints` (RAM).
The watchdog can restart GNC at any time (exponential backoff up to 5
crashes / 60 s) and there is no resume. The README acknowledges this
implicitly (D-02 RTL is also missing) but doesn't list mission resume as a
known bug.

**Recommendation:** when Manager handles `UPLOAD_MISSION` / `START_WP_ROUTE`,
persist `{waypoints, started_at, current_index}` to a separate
`data/active_mission.json` (atomically — see 3.1). On GNC restart, GNC
queries Manager via `system/status` for the active mission and resumes from
`current_index` if `time.time() - started_at < max_resume_age`.

**Confirming test:** `test_mission_state_is_not_persisted`.

### 3.4 🟠 ARM has no pre-conditions (D-04, NEW assertion)
**File:** `src/manager/process.py:98-103`.

The only gate on ARM is `sim_mode != SIMULATION`. There is no check for:
- GNSS fix quality ≥ `failsafe_config.min_gnss_fix`.
- IMU presence (status OK).
- Battery level above some floor.
- `home_wp` set (for RTL fallback).
- ESP32 link healthy.

This is a textbook pre-arm hazard. README D-04 captures it; severity should
be raised to 🟠.

**Confirming test:** `test_arm_is_unconditional`.

### 3.5 🟠 Battery failsafe gap (D-03, confirmed)
ManagerProcess receives `battery_level_pct` from somewhere (not from the
power node directly — actually it never updates this field: the line
`self.battery_level_pct = 0.0` at L43 is the *only* assignment). The
heartbeat carries a hard-coded `"battery_voltage": 12.6` (L87) — confusing
and misleading. The frontend computes battery % from the `sensor/battery`
topic directly; the Manager line is dead.

**Recommendation:** delete the dead `battery_level_pct` / `battery_voltage`
fields from Manager's heartbeat OR wire them to the actual PZEM stream and
add a battery-failsafe handler.

### 3.6 🟡 GNSS failsafe latch can mask a recovery-then-loss (acknowledged trade-off)
**File:** `src/gnc/process.py:792-804`.

The latch (B-01 fix) prevents flooding. Correct. But if RTK is briefly
restored and then lost again, the latch resets on the recovery and re-arms
on the next loss — fine. The subtler issue: the latch resets on `fix_type
>= min_gnss_fix`, but a single noisy NMEA frame with a transient high fix
value could clear the latch prematurely. Consider requiring N consecutive
good frames (e.g. 1 s sustained) before clearing.

### 3.7 🟡 No time-source discipline; reliance on wall clock
Throughout the codebase, `time.time()` (wall clock) is used for failsafe
timers. If the Pi gets an NTP step (e.g. after 4G reconnect), all timers
jump. `time.monotonic()` should be used for any *interval* measurement.

**Files affected:** `src/gnc/process.py` (last_heartbeat_time,
gnss_lost_since), `src/manager/process.py` (last_command_time),
`src/drivers/esp32.py` (ACK loop), `main.py` (watchdog window).

### 3.8 🟡 No hardware watchdog
The watchdog described in `main.py` is purely software. If the Pi's kernel
hangs (rare but possible under voltage sag during motor inrush), nothing
recovers. The Pi 4 has a hardware watchdog (`/dev/watchdog`) — enable it in
`/boot/config.txt` (`dtparam=watchdog=on`) and tickle it from `main.py`.

### 3.9 🟡 Logs grow uncapped during long missions
loguru is configured to rotate at 10 MB and keep 1 week — but the user's
mission profile (long lake/sea operations, no easy access to the SD card) can
fill it. More importantly, `logs/usv_control.log` is on the same SD card
that holds `manager_settings.json`. A full SD card breaks both. Move the log
directory to a tmpfs ring buffer (`/run/usv_log`) plus a periodic flush to
disk *only on critical events*.

### 3.10 🟡 GNSS reconnect logic is bounded by retry interval, not by reboot of receiver
**File:** `src/drivers/gnss_um982.py` (B-08 fix).

The fix retries every 3 s. UM982 cold-start after a power-cycle takes 30–60 s
to first fix. The driver will reconnect to the serial port quickly but
will publish `DISCONNECTED` until first fix; the frontend cannot easily
distinguish "no serial" from "no satellites". Surface the difference in
`sensor/status` ("port_open=False" vs "port_open=True, fix=False").

### 3.11 🟡 NTRIP credentials in `data/manager_settings.json`?
Need to verify (out of scope for this audit): if NTRIP user/password are
persisted in the settings file, they should *not* be readable by a
plaintext frontend localStorage dump (the frontend syncs the full settings
JSON to localStorage per the B-09 fix).

### 3.12 🟡 Watchdog can give up permanently on a safety-critical process
**File:** `main.py:95-103`.

After 5 crashes in 60 s, the watchdog adds the process to `gave_up` and
**never tries again**. For safety-critical processes (HAL, GNC) this is a
soft brick: the vehicle will sit there, unresponsive, possibly with motors
free-running (if firmware doesn't have its own watchdog). At minimum, when
a safety-critical process is given up on, **send a final EMERGENCY_STOP
command into the bus before going dormant** so any remaining listeners
(ESP32 node) zero the motors. Better: do not "give up" on the HAL — use a
longer backoff (e.g. 60 s sustained) and keep trying forever.

---

## 4. Real-time & performance findings

### 4.1 🟡 50 Hz HAL is threaded inside a Python process — GIL pressure
**File:** `src/drivers/process.py:13-69`.

GnssNode (1 Hz), ImuNode (20 Hz), PowerNode (1 Hz) and Esp32Node all run as
threads inside one HALProcess. Their internal serial reads release the GIL,
which is fine. But the HALProcess `loop()` runs at 50 Hz on top, and the
ZMQ-asyncio bridge in `web_server.py` runs in a separate Python interpreter
— so there's no GIL contention between processes. However, *within* the HAL
process, the four threads compete with the loop. On a Pi 4 this is typically
fine; on a Pi 3, less so. **No action required for Pi 4** but document it.

### 4.2 🟡 ESP32 ACK wait is a 200 ms blocking spin
**File:** `src/drivers/esp32.py:43-58`. Inside a 5 ms-spaced `time.sleep`
loop, this thread spins for up to 200 ms per command. At GNC's 20 Hz output
rate (50 ms period), **the ACK can be longer than the command interval**.
Combined with the lack of retry (3.2), this means: under any consistent
serial slowness, every other GNC command is dropped silently.

**Recommendation:** make the ACK wait shorter (e.g. 30 ms) and decouple it
from the send loop — fire-and-forget the next command at 50 ms regardless of
ACK arrival, then reconcile ACKs out-of-band.

### 4.3 🟡 Frontend telemetry history is unbounded (D-11)
Pinia store grows `gncHistory`, `gnssHistory`, `imuHistory`, `powerHistory`
unbounded. Charts clip the visible window but the in-memory array doesn't.
A 4-hour mission at 20 Hz = ~288,000 entries per array. On a low-end laptop
this causes a Chart.js redraw stall around hour 2.

Already in D-11. Recommend a strict ring buffer (`Array` rotation or
`Deque`-style overwrite at 3600 entries).

### 4.4 🟢 LOG_DECIMATION in simulation results is correct but undocumented
**File:** `src/comms/web_server.py:276`. Decimates to ~10 Hz output. Fine.

### 4.5 🟡 `process_incoming_command` does a full Pydantic validation per WS frame
**File:** `src/comms/web_server.py:148-166`.

At MANUAL_INPUT rates (typically ~30 Hz if joystick), this is
~30 validations/sec — not a problem on Pi 4. Mentioned only for awareness.

---

## 5. Security findings

### 5.1 🔴 No authentication (covered in 2.2).

### 5.2 🟠 Frontend sends entire settings JSON over plaintext WS
NTRIP credentials, if persisted, will travel over the WS in cleartext if the
deployment is `ws://` (no TLS). ngrok provides TLS termination, but a LAN
deployment (`http://vehicle-ip:8000`) does not. Add a startup check that
warns if `request.url.scheme != 'https'` and credentials are present.

### 5.3 🟡 CSV waypoint upload accepts arbitrary file content
**File:** `src/comms/web_server.py:380-405`. Validates lat/lon as float but
no upper bound on file size — a multi-MB upload from a malicious client could
consume memory. Add `Content-Length` and line-count guards.

### 5.4 🟢 ngrok host in WS URL detection trusts `window.location.host`
Standard browser pattern; fine. Document that the project intentionally
relies on the browser as the source of host truth.

---

## 6. Scalability & viewer-plane findings (forward-looking)

The user explicitly mentioned a future "viewer plane" broadcast from the
commander PC. Three concrete points to lock down before that lands:

1. **Bandwidth budget:** the vehicle currently broadcasts every sensor topic
   at full rate over WS. At 20 Hz IMU + 1 Hz GNSS/Power + 10 Hz status +
   20 Hz control_debug = ~ 5 kB/s steady, peaking ~ 20 kB/s during sim
   playback. Adding viewers should NOT multiply this from the vehicle side
   — the commander PC must do the fan-out.

2. **Command channel must be one-writer:** server-side enforcement that
   only one connection is the commander. Currently any connection can send
   commands. The `/ws/cmd` vs `/ws/telemetry` split (see 1.4) is the
   simplest answer.

3. **Replay log / black box:** if there are viewers, they will sometimes
   miss connection windows. Decide now whether the vehicle keeps a rolling
   replay log (last N minutes) that a viewer can request on connect. This
   shapes whether `system/status` carries a sequence number that viewers
   use as a resume token.

---

## 7. Smaller code-level findings

| # | Severity | File:line | Finding |
|---|----------|-----------|---------|
| C1 | 🟢 | `src/core/messaging.py:62` | `time.sleep(0.1)` after Publisher connect is a fixed ZMQ slow-joiner workaround; should be configurable or replaced with `socket_monitor` + `EVENT_CONNECTED`. |
| C2 | 🟢 | `src/core/messaging.py:56-73` | B-12: per-instance `zmq.Context`. Should use a module-level singleton context. **Confirming test:** `test_each_subscriber_creates_its_own_zmq_context`. |
| C3 | 🟡 | `src/manager/process.py:87` | `"battery_voltage": 12.6` hard-coded in heartbeat — misleading. Remove. |
| C4 | 🟡 | `src/manager/process.py:43-44` | `battery_level_pct` and `last_command_time` are assigned but never updated/read after init. Dead state. |
| C5 | 🟢 | `src/comms/web_server.py:122` | `@app.on_event("startup")` is deprecated in FastAPI ≥ 0.93. Migrate to `lifespan`. |
| C6 | 🟡 | `src/comms/web_server.py:36-49` | `ConnectionManager.broadcast` mutates `active_connections` inside iteration via `self.disconnect()`. The `[:]` copy guards iteration, but the call-then-close pattern can fire `disconnect` twice for the same socket if the receive loop also catches the disconnect. Race is small but real. |
| C7 | 🟢 | `src/comms/web_server.py:181` | Bare `except Exception` in WS handler swallows everything (incl. coding errors). At minimum log `traceback.format_exc()`. |
| C8 | 🟡 | `src/drivers/process.py:13-69` | `HALProcess.setup()` catches per-node startup exceptions and proceeds with the node set to `None`. There is no later retry: if `/dev/esp32` was missing at boot but plugged in later, the system never recovers without a process restart. (Note: the inner `Esp32Node.run` *does* retry — but only if `__init__` succeeded. The `try` here catches `__init__` failures and never spawns the thread.) |
| C9 | 🟢 | `src/drivers/esp32.py:30` | `checksum = int(m1) + int(m2) + ...` — silent truncation if motor% is fractional (e.g. 12.7 → 12). Probably intended; document. |
| C10 | 🟡 | `src/drivers/esp32.py:132` | `send_command(port_pct, stbd_pct, 1, 1, 1)` — all three relays hard-coded ON. No way from frontend/GNC to power-cycle the payload or open the motor relay for E-stop. **Confirming test:** `test_esp32_relays_hardwired_on`. |
| C11 | 🟢 | `src/core/process.py:53` | B-14: `dt` computed but never passed to `loop()`. Minor. |
| C12 | 🟡 | `src/gnc/process.py:281` | `last_heartbeat_time` bump (the root of finding 2.1). |
| C13 | 🟡 | `src/gnc/process.py:832-846` | GNC publishes synthesized commands back on `command/user` to sync Manager (finding 1.2). |
| C14 | 🟡 | `src/manager/process.py:130` | MANUAL_INPUT only publishes on `mode == MANUAL`. Switching modes without disarming first leaves the last MANUAL throttle latched in the ESP32 buffer until the GNC mode kicks in (one tick). Recommend: publish a single zero-throttle frame on mode transition. |
| C15 | 🟢 | `main.py:107-109` | Backoff multiplier starts at 1 s and doubles, but `_MAX_BACKOFF = 30 s`. If a process repeatedly dies on startup (e.g. missing serial port), the cycle 1 → 2 → 4 → 8 → 16 → 30 → 30 → ... is reasonable. |
| C16 | 🟢 | `src/comms/web_server.py:130-133` | `cmd_pub` is created post-fork in `startup_event` — correct fix for the documented fork-socket issue, well commented. |
| C17 | 🟡 | `src/core/models.py:91-97` | `CommandMessage` accepts `payload: Dict[str, Any]` — no per-CommandType payload schema validation. Each handler validates ad-hoc (e.g. SET_FAILSAFE_CONFIG uses `FailsafeConfig(**cmd.payload)`). For ARM, SET_MODE, MANUAL_INPUT, payload is essentially unchecked. Define a discriminated union per `CommandType` to make this enforceable. |
| C18 | 🟡 | `tests/test_zmq.py` | Hangs (or appears to) when run as part of the full suite — needs investigation. Suite passes when this file is excluded. |
| C19 | 🟢 | `src/drivers/arduino_nano.py` | B-13 acknowledged in README as an exact duplicate of `esp32.py`. It is in fact divergent (different timeout, buffer reset, rounding). Either remove the file or rewrite README B-13. **Confirming test:** `test_arduino_nano_legacy_driver_still_shipped`. |
| C20 | 🟢 | `_old/` directory | Old camera streamer / INS code lives here. Ensure not imported anywhere in `src/`; if not, delete to reduce surface area. |

---

## 8. Recommendations, ranked by impact-per-effort

Highest leverage first. Treat the top 4 as **must-do before any field
deployment beyond a controlled pond**.

1. **Wire the comm-loss failsafe to actual frontend liveness** (finding 2.1
   / §C12). One new ZMQ topic (`comms/link`), a 1-second uplink ping from
   the frontend, ~30 lines of code.
2. **Atomic settings write + corruption alert** (finding 3.1 / §C12).
   `os.replace` + `f.fsync()` + a critical-level alert when load fails. ~10
   lines.
3. **Authentication on the WS endpoint** (finding 2.2). Even a per-vehicle
   random token gates the ngrok URL. ~20 lines.
4. **Firmware-side motor watchdog** + driver-side resend on ACK miss
   (finding 3.2 / C10). Without this, the Pi watchdog can't protect the
   user from a runaway boat after a Python freeze. ESP32 firmware change
   plus ~20 lines in the driver.
5. **Mission state persistence** (finding 3.3). Same atomic-write pattern;
   plus a `RESUME_MISSION` handler in GNC. ~50 lines.
6. **Explicit VehicleState enum** (finding 1.1). Replace three booleans
   with one enum; one heartbeat field; simplifies every downstream check.
7. **Pre-arm checks** (finding 3.4 / D-04). Gate ARM on GNSS fix, IMU OK,
   home_wp set, ESP32 alive. ~20 lines.
8. **Command sequence numbers + acks** (finding 2.3). Needed for idempotent
   commands over flaky 4G. ~80 lines across model + frontend + Manager.
9. **Hardware watchdog enabled** (finding 3.8). One line in `/boot/config.txt`
   + a tickle in `main.py`.
10. **Viewer-plane design** (finding 1.4 / §6). Lock in *before* it grows
    organically.

The remaining items (HWM tuning, monotonic-clock migration, history ring
buffer, log placement, etc.) are quality-of-life and can land in a slower
cadence.

---

## 9. Verification

- Existing test suite: **42 passed** (excluding `test_zmq.py`, which appears
  to hang during a clean run — see C18). No production code was touched.
- New audit suite: **11 passed** in `tests/test_audit_findings.py`. Each
  test encodes a defect described above and serves as a regression marker:
  it will fail (correctly) when the underlying defect is fixed, prompting
  removal of the test along with the bug.

Run the audit suite locally with:
```
python -m pytest tests/test_audit_findings.py -v
```

Open `tests/test_audit_findings.py` next to this document — every test
header points back to the section here.

---

## Appendix A. Bug-table delta vs README

The README's "Bugs" table tracks B-01..B-15 (most FIXED). This audit adds:

| New ID | Severity | Title | Section |
|--------|----------|-------|---------|
| B-16 | 🔴 | Comm-loss failsafe wired to local Manager heartbeat, not to commander link | §2.1 |
| B-17 | 🔴 | `manager_settings.json` non-atomic write; corruption silently reverts to defaults | §3.1 |
| B-18 | 🔴 | WebSocket / public ngrok URL has no authentication | §2.2 |
| B-19 | 🟠 | No firmware-side motor dead-man's switch; driver has no resend on ACK timeout | §3.2 |
| B-20 | 🟠 | Mission state lost on GNCProcess restart (no resume) | §3.3 |
| B-21 | 🟠 | `CommandMessage` lacks `seq` / `nonce`; no per-command ack | §2.3 |
| B-22 | 🟡 | GNC publishes synthesized commands back on `COMMAND_USER` (self-loop) | §1.2 |
| B-23 | 🟡 | Wall-clock used for interval measurements; NTP step breaks failsafe timers | §3.7 |
| B-24 | 🟡 | Dead heartbeat fields (`battery_voltage=12.6`, `battery_level_pct=0`) in Manager status | §3.5, C3-C4 |
| B-25 | 🟡 | ESP32 relays R1/R2/R3 hard-coded ON in driver — no per-relay command path | §3.2, C10 |
| B-26 | 🟡 | No hardware watchdog enabled | §3.8 |
| B-27 | 🟡 | ZMQ HWM defaults; silent SYSTEM_STATUS / sensor drops under slow consumers | §2.4 |
| B-28 | 🟡 | Watchdog "give up" path leaves motors potentially running on safety-critical process death | §3.12 |
| B-29 | 🟡 | HAL never retries node `__init__` after first failure (vs. the per-node inner retry which only kicks in after a successful `__init__`) | C8 |
| B-30 | 🟢 | Deprecated `@app.on_event("startup")` | C5 |

— End of analysis —
