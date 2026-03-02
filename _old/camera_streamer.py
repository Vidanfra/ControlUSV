# camera_streamer_updated.py
import subprocess
import shutil
import threading
import time
import os
import signal
import logging

_logger = logging.getLogger("CameraStreamer")
logging.basicConfig(level=logging.INFO)


class CameraStreamer:
    """
    Robust camera streamer for Raspberry Pi.
    - Auto-detects camera format (MJPEG / YUYV) and selects a safe pipeline.
    - Prefers SW encoder (x264enc) as default (reliable). Attempts HW (v4l2h264enc) if available.
    - Auto-restart on failure with exponential backoff.
    """

    def __init__(self,
                 device="/dev/video0",
                 width=640,
                 height=480,
                 bitrate_kbps=800,
                 target_host="192.168.1.14",
                 target_port=5600,
                 fps_preference=(30, 25),
                 use_gst=True,
                 auto_restart=True,
                 restart_delay=2.0,
                 max_retries=5,):
        """
        :param device: v4l2 device
        :param width,height: desired resolution
        :param bitrate_kbps: target bitrate for encoder
        :param target_host: IP of GCS (QGC)
        :param target_port: UDP port for video
        :param fps_preference: tuple of preferred fps to choose from (first tried)
        :param use_gst: use gst-launch-1.0 if available (preferred)
        :param auto_restart: restart streamer on crash
        :param restart_delay: initial restart delay (exponential backoff)
        :param max_retries: how many restart attempts before giving up (None => infinite)
        :param mav: optional pymavlink MAV object (so we can send STATUSTEXT)
        """
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.bitrate_kbps = int(bitrate_kbps)
        self.target_host = target_host
        self.target_port = int(target_port)
        self.fps_pref = list(fps_preference)
        self.use_gst = use_gst and shutil.which("gst-launch-1.0") is not None
        self._gst_bin = shutil.which("gst-launch-1.0")
        self._ffmpeg_bin = shutil.which("ffmpeg")
        if not self.use_gst and not self._ffmpeg_bin:
            raise RuntimeError("Neither gst-launch-1.0 nor ffmpeg found on PATH")
        self.auto_restart = auto_restart
        self.restart_delay = float(restart_delay)
        self.max_retries = None if max_retries is None else int(max_retries)

        self._proc = None
        self._monitor_thread = None
        self._stderr_thread = None
        self._stop_event = threading.Event()
        self._retries = 0
        self._last_error = None

    # ----------------- V4L2/gst detection -----------------
    def _v4l2_info(self):
        try:
            out = subprocess.check_output(["v4l2-ctl", "--list-formats-ext", "-d", self.device],
                                          stderr=subprocess.STDOUT, text=True)
            return out.lower()
        except Exception as e:
            _logger.debug("v4l2-ctl failed: %s", e)
            return ""

    def _detect_caps(self):
        info = self._v4l2_info()
        caps = {"mjpeg": False, "yuyv": False, "mjpeg_fps": [], "yuyv_fps": []}
        if "mjpg" in info or "mjpeg" in info or "jpeg" in info:
            caps["mjpeg"] = True
        if "yuyv" in info or "yuy2" in info or "yuyv2" in info:
            caps["yuyv"] = True

        # detect fps heuristically for requested resolution
        for line in info.splitlines():
            if f"{self.width}x{self.height}" in line:
                # look for fps in following lines
                if "interval" in line and "fps" in line:
                    import re
                    m = re.search(r'(\d+(\.\d+)?)\s*fps', line)
                    if m:
                        fps = int(round(float(m.group(1))))
                        # assign to format by context (simple heuristic)
                        if "jpeg" in info:
                            caps["mjpeg_fps"].append(fps)
                        if "yuyv" in info:
                            caps["yuyv_fps"].append(fps)
        # fallback defaults if empty
        if not caps["mjpeg_fps"]:
            caps["mjpeg_fps"] = [30]
        if not caps["yuyv_fps"]:
            caps["yuyv_fps"] = [25]
        return caps

    def _hw_encoder_available(self):
        try:
            subprocess.check_output(["gst-inspect-1.0", "v4l2h264enc"], stderr=subprocess.STDOUT, text=True)
            return True
        except Exception:
            return False

    # ----------------- Pipeline construction -----------------
    def _pick_fps(self, supported):
        for p in self.fps_pref:
            if p in supported:
                return p
        return supported[0] if supported else self.fps_pref[0]

    def _ensure_camera_free(self):
        """
        Check if /dev/video0 is in use, and kill offending processes if needed.
        """
        camera_in_use = False
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            fd_dir = f"/proc/{pid}/fd"
            if not os.path.exists(fd_dir):
                continue
            try:
                for fd in os.listdir(fd_dir):
                    path = os.readlink(os.path.join(fd_dir, fd))
                    if path == self.device:
                        print(f"Killing process {pid} using {self.device}")
                        os.kill(int(pid), signal.SIGTERM)
                        camera_in_use = True
                        time.sleep(0.1)
            except Exception:
                continue
        if camera_in_use:
            time.sleep(0.5)  # give OS time to release device
        return True


    def _build_pipelines(self):
        """
        Returns a list of pipeline strings to try in order (preferred -> fallback).
        """
        try:
            if not self._ensure_camera_free():
                _logger.error("Camera device %s is busy and could not be freed", self.device)
                return []
        
            caps = self._detect_caps()
            pipelines = []

            # provide a safe SW default (may or may not work depending on camera)
            if not pipelines:
                pipelines.append(
                    f"v4l2src device={self.device} ! video/x-raw,width={self.width},height={self.height},framerate=25/1 ! "
                    f"videoconvert ! queue max-size-buffers=6 leaky=downstream ! "
                    f"x264enc tune=zerolatency bitrate={self.bitrate_kbps} speed-preset=ultrafast ! "
                    f"rtph264pay config-interval=1 pt=96 ! udpsink host={self.target_host} port={self.target_port} sync=false"
                )

            return pipelines
        except Exception as e:
            _logger.error("Error building pipelines: %s", e)
            return []

    # ----------------- Process management -----------------
    def _read_stderr(self, stream):
        try:
            for raw in iter(stream.readline, b''):
                if not raw:
                    break
                line = raw.decode(errors="ignore").rstrip()
                _logger.debug("gst stderr: %s", line)
                # capture errors to last_error
                if "error" in line.lower() or "failed" in line.lower() or "warning" in line.lower():
                    self._last_error = line
        except Exception as e:
            _logger.debug("stderr reader stopped: %s", e)

    def _monitor(self):
        backoff = self.restart_delay
        while not self._stop_event.is_set():
            if not self._proc:
                break
            rc = self._proc.poll()
            if rc is None:
                time.sleep(0.5)
                continue
            # process exited
            _logger.warning("camera streamer exited with rc=%s", rc)
            self._last_error = f"process exited rc={rc}"
            self._proc = None
            # decide restart
            if not self.auto_restart:
                break
            self._retries += 1
            if self.max_retries is not None and self._retries > self.max_retries:
                _logger.error("max_retries exceeded, not restarting")
                break
            _logger.info("Restarting streamer in %.1f s (attempt %d)", backoff, self._retries)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            try:
                self._start_process()
                # if started OK reset backoff and retries
                backoff = self.restart_delay
            except Exception as e:
                _logger.error("Restart attempt failed: %s", e)
                continue

    def _start_process(self):
        pipelines = self._build_pipelines()
        if not pipelines:
            raise RuntimeError("No pipelines available")
        last_err = None
        for pipeline in pipelines:
            # build cmd
            if self.use_gst:
                cmd = f"{self._gst_bin} {pipeline}"
                _logger.info("Attempting pipeline: %s", pipeline)
                try:
                    self._proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
                except Exception as e:
                    last_err = str(e)
                    _logger.warning("Failed to spawn process: %s", e)
                    self._proc = None
                    continue
            else:
                # fallback to ffmpeg - not implemented complex detection here; a simple ffmpeg UDP line could be used
                cmd = [
                    self._ffmpeg_bin, "-f", "v4l2", "-framerate", "25",
                    "-video_size", f"{self.width}x{self.height}", "-i", self.device,
                    "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                    "-b:v", f"{self.bitrate_kbps}k", "-f", "mpegts",
                    f"udp://{self.target_host}:{self.target_port}"
                ]
                _logger.info("Attempting ffmpeg command")
                try:
                    self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=os.setsid)
                except Exception as e:
                    last_err = str(e)
                    self._proc = None
                    _logger.warning("Failed to start ffmpeg: %s", e)
                    continue

            # give it a short time to fail fast if pipeline is invalid
            time.sleep(1.0)
            rc = self._proc.poll()
            if rc is None:
                # started OK
                _logger.info("Streamer started (pid=%s)", getattr(self._proc, "pid", None))
                # spawn stderr reader
                self._stderr_thread = threading.Thread(target=self._read_stderr, args=(self._proc.stderr,), daemon=True)
                self._stderr_thread.start()
                # spawn monitor thread if not started
                if not self._monitor_thread or not self._monitor_thread.is_alive():
                    self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
                    self._monitor_thread.start()
                return
            else:
                # collect stderr for diagnosis
                try:
                    err = self._proc.stderr.read().decode(errors="ignore")
                except Exception:
                    err = "<no stderr>"
                last_err = err
                _logger.warning("Pipeline failed early (rc=%s). stderr:\n%s", rc, err)
                self._proc = None
                # try next pipeline
        raise RuntimeError(f"All pipelines failed. last_err={last_err}")

    # ----------------- Public API -----------------
    def start(self):
        """Start streamer (non-blocking)."""
        try:
            if self._proc and self._proc.poll() is None:
                _logger.info("Streamer already running")
                return
            self._stop_event.clear()
            self._retries = 0
            try:
                self._start_process()
            except Exception as e:
                self._last_error = str(e)
        except Exception as e:
            _logger.error("Failed to start streamer: %s", e)


    def stop(self):
        """Stop streamer and monitor."""
        self._stop_event.set()
        if self._proc:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except Exception:
                pass
            self._proc = None
        # join threads lightly
        try:
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self._stderr_thread and self._stderr_thread.is_alive():
                self._stderr_thread.join(timeout=0.5)
        except Exception:
            pass
        _logger.info("Streamer stopped")

    def is_running(self):
        return self._proc is not None and self._proc.poll() is None

    def get_last_error(self):
        return self._last_error

    def set_target(self, host, port, restart=True):
        """
        Change the target host/port for the stream. If restart==True, will restart the streamer.
        """
        self.target_host = host
        self.target_port = int(port)
        _logger.info("CameraStreamer target updated to %s:%d", host, port)
        if restart and self.is_running():
            _logger.info("Restarting streamer to apply new target")
            self.stop()
            time.sleep(0.2)
            self.start()


if __name__ == "__main__":
    # simple demo: instanciar y arrancar
    s = CameraStreamer(device="/dev/video0", width=640, height=480,
                       bitrate_kbps=800, target_host="192.168.1.14", target_port=5600,
                       auto_restart=True)
    try:
        s.start()
        while True:
            time.sleep(1)
            if not s.is_running():
                _logger.info("Streamer not running (main loop check), last error: %s", s.get_last_error())
                break
    except KeyboardInterrupt:
        pass
    finally:
        s.stop()

