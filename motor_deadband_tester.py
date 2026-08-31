#!/usr/bin/env python3
"""Standalone web tester for measuring the deadband of the two thrusters.

Stop the ControlUSV stack before connecting this program to /dev/esp32.
Open the shown URL from a PC on the same network.
"""

import argparse
import json
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial


BAUDRATE = 115200
HEARTBEAT_S = 0.1


@dataclass
class ProfileSegment:
    kind: str
    motor_1: float
    motor_2: float
    duration_s: float


class MotorController:
    def __init__(self, port: str):
        self.port_name = port
        self.serial_port = None
        self.command_m1 = 0.0
        self.command_m2 = 0.0
        self.segments: list[ProfileSegment] = []
        self.profile_running = False
        self.loop_profile = False
        self.profile_index = 0
        self.profile_segment_started_at = 0.0
        self.segment_start_m1 = 0.0
        self.segment_start_m2 = 0.0
        self.message = "Desconectado"
        self.lock = threading.Lock()
        self.running = True
        self.heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat.start()

    @staticmethod
    def percent(value) -> float:
        value = float(value)
        if not -100 <= value <= 100:
            raise ValueError("Los valores de motor deben estar entre -100 y 100.")
        return value

    def connect(self):
        with self.lock:
            if self.serial_port and self.serial_port.is_open:
                return
            self.serial_port = serial.Serial(self.port_name, BAUDRATE, timeout=0.05)
        time.sleep(2)  # The ESP32 can reset after opening the port.
        with self.lock:
            self.message = f"Conectado a {self.port_name} a {BAUDRATE} baud"
            self._write_command(0, 0)

    def disconnect(self):
        with self.lock:
            self._stop_locked()
            if self.serial_port:
                self.serial_port.close()
            self.serial_port = None
            self.message = "Desconectado"

    def state(self):
        with self.lock:
            return {
                "connected": bool(self.serial_port and self.serial_port.is_open),
                "message": self.message,
                "motor_1": self.command_m1,
                "motor_2": self.command_m2,
                "profile_running": self.profile_running,
                "loop_profile": self.loop_profile,
                "profile_index": self.profile_index,
                "segments": [asdict(segment) for segment in self.segments],
            }

    def set_manual(self, motor_1, motor_2):
        with self.lock:
            self.command_m1 = self.percent(motor_1)
            self.command_m2 = self.percent(motor_2)
            self.profile_running = False
            self.message = "Control manual activo"
            self._write_command(self.command_m1, self.command_m2)

    def set_profile(self, segments, loop_profile):
        parsed = []
        for segment in segments:
            kind = segment["kind"]
            if kind not in ("Escalon", "Rampa"):
                raise ValueError("El tipo de segmento debe ser Escalon o Rampa.")
            duration = float(segment["duration_s"])
            if duration <= 0:
                raise ValueError("La duracion debe ser mayor que cero.")
            parsed.append(ProfileSegment(
                kind, self.percent(segment["motor_1"]), self.percent(segment["motor_2"]), duration
            ))
        with self.lock:
            self.segments = parsed
            self.loop_profile = bool(loop_profile)
            self.message = f"Perfil preparado con {len(parsed)} segmento(s)"

    def start_profile(self):
        with self.lock:
            if not self.serial_port or not self.serial_port.is_open:
                raise ValueError("Conecta el ESP32 antes de iniciar el perfil.")
            if not self.segments:
                raise ValueError("Anade al menos un segmento al perfil.")
            self.profile_running = True
            self.profile_index = 0
            self.profile_segment_started_at = time.monotonic()
            self.segment_start_m1 = self.command_m1
            self.segment_start_m2 = self.command_m2
            self.message = "Perfil en marcha"

    def stop(self):
        with self.lock:
            self._stop_locked()

    def _stop_locked(self):
        self.profile_running = False
        self.command_m1 = 0.0
        self.command_m2 = 0.0
        self._write_command(0, 0)
        self.message = "Motores detenidos"

    def _write_command(self, motor_1, motor_2):
        if not self.serial_port or not self.serial_port.is_open:
            return
        payload = {"M1": motor_1, "M2": motor_2, "R1": 0, "R2": 1, "R3": 0}
        payload["C"] = int(motor_1) + int(motor_2) + 1
        try:
            self.serial_port.write((json.dumps(payload) + "\n").encode("utf-8"))
        except serial.SerialException as error:
            self.serial_port = None
            self.message = f"Error de serie: {error}"

    def _update_profile(self):
        segment = self.segments[self.profile_index]
        now = time.monotonic()
        elapsed = now - self.profile_segment_started_at
        while elapsed >= segment.duration_s and self.profile_running:
            self.command_m1, self.command_m2 = segment.motor_1, segment.motor_2
            self.profile_index += 1
            if self.profile_index == len(self.segments):
                if not self.loop_profile:
                    self._stop_locked()
                    self.message = "Perfil finalizado; motores a cero"
                    return
                self.profile_index = 0
            self.profile_segment_started_at = now
            self.segment_start_m1, self.segment_start_m2 = self.command_m1, self.command_m2
            segment = self.segments[self.profile_index]
            elapsed = now - self.profile_segment_started_at
        if segment.kind == "Rampa":
            progress = elapsed / segment.duration_s
            self.command_m1 = self.segment_start_m1 + progress * (segment.motor_1 - self.segment_start_m1)
            self.command_m2 = self.segment_start_m2 + progress * (segment.motor_2 - self.segment_start_m2)
        else:
            self.command_m1, self.command_m2 = segment.motor_1, segment.motor_2
        self.message = f"Perfil: segmento {self.profile_index + 1}/{len(self.segments)} ({elapsed:.1f}/{segment.duration_s:g} s)"

    def _heartbeat_loop(self):
        while self.running:
            with self.lock:
                if self.profile_running:
                    self._update_profile()
                self._write_command(self.command_m1, self.command_m2)
            time.sleep(HEARTBEAT_S)


PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ControlUSV | Test de deadband</title><style>
:root { font-family: ui-sans-serif, sans-serif; color:#18231f; background:#edf3ed; }
body { max-width: 960px; margin: 0 auto; padding: 24px; } h1 { margin:0 0 4px; } p { margin-top:4px; }
section { background:#fff; border:1px solid #c8d4ca; border-radius:8px; padding:18px; margin:16px 0; }
.row { display:flex; flex-wrap:wrap; gap:12px; align-items:end; } label { display:grid; gap:5px; font-weight:600; }
input,select,button { font:inherit; padding:8px; border:1px solid #8da28f; border-radius:4px; } input { width:92px; }
button { cursor:pointer; background:#176b43; color:#fff; border-color:#176b43; font-weight:700; } button.alt { background:#fff; color:#176b43; }
button.stop { width:100%; background:#b42318; border-color:#b42318; font-size:18px; padding:14px; } button.small { padding:5px 8px; }
#status { font-weight:700; } table { width:100%; border-collapse:collapse; margin-top:14px; } th,td { padding:8px; border-bottom:1px solid #d8e0d8; text-align:left; }
@media(max-width:600px) { body { padding:12px; } input { width:72px; } }
</style></head><body>
<h1>Test de deadband</h1><p>Herramienta independiente. Deten la interfaz de ControlUSV antes de conectar.</p>
<section><div class="row"><button id="connect">Conectar ESP32</button><span id="status">Cargando...</span></div></section>
<section><h2>Comando instantaneo</h2><div class="row"><label>M1 babor (%)<input id="manual1" type="number" min="-100" max="100" value="0"></label><label>M2 estribor (%)<input id="manual2" type="number" min="-100" max="100" value="0"></label><button onclick="manual()">Enviar M1/M2</button><label>Ambos igual (%)<input id="both" type="number" min="-100" max="100" value="0"></label><button onclick="both()">Aplicar ambos</button></div></section>
<section><h2>Timeline de perfil</h2><div class="row"><label>Tipo<select id="kind"><option>Escalon</option><option>Rampa</option></select></label><label>M1 (%)<input id="m1" type="number" min="-100" max="100" value="0"></label><label>M2 (%)<input id="m2" type="number" min="-100" max="100" value="0"></label><label>Tiempo<input id="duration" type="number" min="0.1" step="0.1" value="1"></label><label>Unidad<select id="unit"><option value="1">s</option><option value="60">min</option></select></label><button onclick="add()">Anadir</button></div>
<table><thead><tr><th>Tipo</th><th>M1</th><th>M2</th><th>Duracion</th><th></th></tr></thead><tbody id="segments"></tbody></table>
<div class="row" style="margin-top:14px"><label><input id="loop" type="checkbox"> Repetir en loop</label><button onclick="start()">Iniciar perfil</button></div></section>
<button class="stop" onclick="stop()">STOP - MOTORES A CERO</button>
<script>
let segments=[];
async function api(path, body) { const res=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}); const data=await res.json(); if(!res.ok) throw Error(data.detail); return data; }
function value(id) { return Number(document.getElementById(id).value); }
function render() { document.getElementById('segments').innerHTML=segments.map((s,i)=>`<tr><td>${s.kind}</td><td>${s.motor_1}%</td><td>${s.motor_2}%</td><td>${s.duration_s}s</td><td><button class="small alt" onclick="removeSegment(${i})">Eliminar</button></td></tr>`).join(''); }
function add() { const duration=value('duration')*value('unit'); if(!(duration>0)) return alert('Tiempo no valido'); segments.push({kind:document.getElementById('kind').value,motor_1:value('m1'),motor_2:value('m2'),duration_s:duration}); render(); }
function removeSegment(i) { segments.splice(i,1); render(); }
async function manual() { try { await api('/api/manual',{motor_1:value('manual1'),motor_2:value('manual2')}); } catch(e) { alert(e.message); } }
async function both() { document.getElementById('manual1').value=document.getElementById('both').value; document.getElementById('manual2').value=document.getElementById('both').value; await manual(); }
async function start() { try { await api('/api/profile',{segments,loop_profile:document.getElementById('loop').checked}); await api('/api/start'); } catch(e) { alert(e.message); } }
async function stop() { try { await api('/api/stop'); } catch(e) { alert(e.message); } }
document.getElementById('connect').onclick=async()=>{ try { await api('/api/connect'); } catch(e) { alert(e.message); } };
setInterval(async()=>{ try { const s=await (await fetch('/api/state')).json(); document.getElementById('status').textContent=s.message; document.getElementById('connect').textContent=s.connected?'ESP32 conectado':'Conectar ESP32'; } catch(e) {} },500);
</script></body></html>"""


def make_handler(controller):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/state":
                self._json(200, controller.state())
            else:
                self._json(404, {"detail": "No encontrado"})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/connect":
                    controller.connect()
                elif self.path == "/api/manual":
                    controller.set_manual(data["motor_1"], data["motor_2"])
                elif self.path == "/api/profile":
                    controller.set_profile(data["segments"], data.get("loop_profile", False))
                elif self.path == "/api/start":
                    controller.start_profile()
                elif self.path == "/api/stop":
                    controller.stop()
                else:
                    self._json(404, {"detail": "No encontrado"})
                    return
                self._json(200, controller.state())
            except (KeyError, TypeError, ValueError, serial.SerialException) as error:
                self._json(400, {"detail": str(error)})

        def log_message(self, _format, *_args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Web tester for ControlUSV motor deadband.")
    parser.add_argument("--port", default="/dev/esp32", help="ESP32 serial port (default: /dev/esp32)")
    parser.add_argument("--web-port", default=8081, type=int, help="Web server port (default: 8081)")
    args = parser.parse_args()
    controller = MotorController(args.port)
    server = ThreadingHTTPServer(("0.0.0.0", args.web_port), make_handler(controller))
    print(f"Abre desde tu PC: http://<IP-DE-LA-RASPBERRY>:{args.web_port}")
    print("Pulsa Ctrl+C para detener el servidor y mandar los motores a cero.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        controller.running = False
        controller.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()