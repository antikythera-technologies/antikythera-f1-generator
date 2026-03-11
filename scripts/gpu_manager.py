"""
Tiny HTTP management server for GPU process lifecycle on RunPod.

Runs on port 7777 and allows the pipeline to start/stop Ovi independently
of ComfyUI, enabling GPU VRAM sharing on a single A6000.

Endpoints:
    GET  /health          → 200 OK
    GET  /ovi/status      → {"running": bool, "pid": int|null}
    POST /ovi/start       → Start Ovi Gradio server
    POST /ovi/stop        → Kill Ovi Gradio server
    GET  /gpu/status      → GPU memory usage summary
"""

import json
import os
import signal
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

OVI_START_SCRIPT = "/workspace/start-ovi-now.sh"
OVI_PORT = 8888


def find_ovi_pid() -> int | None:
    """Find the Ovi Gradio process PID."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "gradio_app.py"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
    except Exception:
        pass
    return None


def find_ovi_parent_pid() -> int | None:
    """Find the start-ovi-now.sh parent shell PID."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "start-ovi-now.sh"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            return int(pids[0])
    except Exception:
        pass
    return None


def get_gpu_status() -> dict:
    """Get GPU memory usage via nvidia-smi."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            return {
                "total_mib": int(parts[0]),
                "used_mib": int(parts[1]),
                "free_mib": int(parts[2]),
            }
    except Exception as e:
        return {"error": str(e)}
    return {"error": "nvidia-smi failed"}


class GPUManagerHandler(BaseHTTPRequestHandler):
    def _send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok"})

        elif self.path == "/ovi/status":
            pid = find_ovi_pid()
            self._send_json({"running": pid is not None, "pid": pid})

        elif self.path == "/gpu/status":
            self._send_json(get_gpu_status())

        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/ovi/start":
            pid = find_ovi_pid()
            if pid:
                self._send_json({"status": "already_running", "pid": pid})
                return

            if not os.path.exists(OVI_START_SCRIPT):
                self._send_json(
                    {"error": f"{OVI_START_SCRIPT} not found"}, 500
                )
                return

            # Start Ovi in background
            subprocess.Popen(
                ["bash", OVI_START_SCRIPT],
                stdout=open("/tmp/ovi-start.log", "w"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self._send_json({"status": "starting", "message": "Ovi process launched"})

        elif self.path == "/ovi/stop":
            pid = find_ovi_pid()
            parent_pid = find_ovi_parent_pid()

            if not pid and not parent_pid:
                self._send_json({"status": "not_running"})
                return

            killed = []
            for p in [pid, parent_pid]:
                if p:
                    try:
                        os.kill(p, signal.SIGTERM)
                        killed.append(p)
                    except ProcessLookupError:
                        pass

            # Wait briefly for graceful shutdown, then force kill
            time.sleep(2)
            for p in [pid]:
                if p:
                    try:
                        os.kill(p, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

            self._send_json({"status": "stopped", "killed_pids": killed})

        else:
            self._send_json({"error": "not found"}, 404)

    def log_message(self, format, *args):
        print(f"[gpu-manager] {args[0]}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 7777), GPUManagerHandler)
    print(f"GPU Manager listening on port 7777")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down GPU Manager")
        server.shutdown()
