"""
Verifies the UM982 NTRIP link recovers on its own (without restarting the
serial reader) after the caster drops the stream, and that the periodic GGA
uplink never runs on the NMEA reader thread.
"""
import socket
import threading
import time

from src.drivers.gnss_um982 import UM982Driver

# Valid NMEA checksums so pynmea2 accepts them.
GGA_RTK = "$GPGGA,120000.00,3919.2000,N,00034.8000,W,4,12,0.80,10.0,M,45.0,M,,*7C"
GGA_FIX = "$GPGGA,120000.00,3919.2000,N,00034.8000,W,1,08,1.00,10.0,M,45.0,M,,*7B"


class FakeSerial:
    """Minimal pyserial stand-in that records RTCM writes."""

    def __init__(self):
        self.is_open = True
        self.written = bytearray()
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            self.written.extend(data)
        return len(data)

    def readline(self):
        time.sleep(0.05)
        return b""

    def close(self):
        self.is_open = False


class FakeCaster(threading.Thread):
    """NTRIP caster that streams a few RTCM bytes then drops the connection."""

    daemon = True

    def __init__(self, drops=1):
        super().__init__()
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        self.connections = 0
        self.gga_received = []
        self._drops = drops
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                self.srv.settimeout(0.5)
                conn, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            try:
                conn.settimeout(1.0)
                conn.recv(1024)  # request header
                conn.sendall(b"ICY 200 OK\r\n\r\n")
                deadline = time.time() + (0.6 if self.connections <= self._drops else 3.0)
                while time.time() < deadline and not self._stop.is_set():
                    conn.sendall(b"\xd3\x00\x13RTCM")
                    try:
                        data = conn.recv(4096, socket.MSG_DONTWAIT)
                        if data and b"GGA" in data:
                            self.gga_received.append(data)
                    except (BlockingIOError, socket.timeout):
                        pass
                    time.sleep(0.1)
            except Exception:
                pass
            finally:
                conn.close()

    def stop(self):
        self._stop.set()
        try:
            self.srv.close()
        except Exception:
            pass


def _make_driver(caster):
    drv = UM982Driver(
        ntrip_caster="127.0.0.1",
        ntrip_port=caster.port,
        mountpoint="TEST",
        username="u",
        password="p",
    )
    drv.ser = FakeSerial()
    drv.running = True
    return drv


def test_ntrip_reconnects_after_stream_drop():
    caster = FakeCaster(drops=1)
    caster.start()
    drv = _make_driver(caster)

    t = threading.Thread(target=drv._rtcm_loop, daemon=True)
    t.start()
    try:
        deadline = time.time() + 20
        while time.time() < deadline and caster.connections < 2:
            time.sleep(0.1)

        assert caster.connections >= 2, "driver did not reconnect to the caster"
        assert drv._rtcm_bytes > 0, "no RTCM forwarded to the receiver"
        assert bytes(drv.ser.written).count(b"RTCM") > 0
        assert drv.ser.is_open, "serial port must stay open across NTRIP reconnects"
    finally:
        drv.running = False
        t.join(timeout=5)
        caster.stop()


def test_gga_uplink_is_throttled_and_needs_a_fix():
    caster = FakeCaster(drops=0)
    caster.start()
    drv = _make_driver(caster)
    try:
        assert drv._reconnect_ntrip() is True

        # No fix yet -> nothing is uploaded (would request corrections for 0,0).
        drv._latest_gga = "$GPGGA,,,,,,0,,,,,,,,"
        drv._uplink_gga()
        assert drv._last_gga_uplink == 0.0

        drv.data["fix_type"] = 1
        drv.data["lat"] = 39.32
        drv.data["lon"] = -0.58
        drv._latest_gga = GGA_FIX
        drv._uplink_gga()
        first = drv._last_gga_uplink
        assert first > 0.0, "GGA should be uploaded once a fix is available"

        # Second immediate call must be throttled, not sent every fix.
        drv._uplink_gga()
        assert drv._last_gga_uplink == first
    finally:
        drv.running = False
        drv._close_ntrip()
        caster.stop()


def test_dispatch_does_no_socket_io():
    """The reader thread must only cache the GGA; blocking sends there stall NMEA."""
    caster = FakeCaster(drops=0)
    caster.start()
    drv = _make_driver(caster)
    try:
        line = GGA_RTK
        drv._dispatch(line)
        assert drv._latest_gga == line
        assert drv._last_gga_uplink == 0.0, "reader thread must not touch the NTRIP socket"
    finally:
        drv.running = False
        caster.stop()
