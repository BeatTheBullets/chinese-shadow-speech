"""First-run bootstrap for the Windows package (standard library only: it runs under the shipped standalone Python before
any venv exists). Creates the app's environment with uv, prepares the models while a progress page is shown in the browser,
updates yt-dlp once a day, then starts the launcher."""
from __future__ import annotations
import datetime
import hashlib
import json
import logging
import logging.handlers
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

PREFERRED_PORT = 47231
MODELS_GB = 4                 # shown to the user
NEEDED_GB = 8                 # free space required before the first setup (models, venv, uv cache)
UPDATE_NEEDED_GB = 2          # free space required when an update reruns setup (the models are already there)
LAUNCH_WAIT = 180             # seconds to wait for the launcher's /health
YTDLP_TIMEOUT = 60            # seconds before the daily yt-dlp update is killed
PAGE_GONE_AFTER = 75          # seconds without a /status poll before the progress tab counts as closed (a hidden
                              # tab's timers can slow to once a minute, so a shorter wait would open a second tab)
NO_INTERNET = "No internet connection \u2014 connect and press Retry"
_NETWORK = re.compile(r"dns|resolve|getaddrinfo|connection|connect error|timed out|timeout|unreachable|network|"
                      r"error sending request|ssl|certificate|name or service", re.I)
WIN = sys.platform == "win32"
HERE = Path(__file__).resolve().parent


def home_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "chinese-shadow-speech"


_loggers: dict[str, logging.Logger] = {}


def log(home: Path, msg: str) -> None:
    """Append to <home>/logs/bootstrap.log (one rotating handler per home; never raises, never prints)."""
    try:
        key = str(home)
        lg = _loggers.get(key)
        if lg is None:
            path = Path(home) / "logs" / "bootstrap.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            lg = logging.Logger(f"bootstrap:{key}")
            h = logging.handlers.RotatingFileHandler(path, maxBytes=200_000, backupCount=1, encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            lg.addHandler(h)
            _loggers[key] = lg
        lg.warning(msg)
    except Exception:  # noqa: BLE001 - logging must never break the app (and stdout may be None under pythonw)
        pass


def lock_hash(app_dir: Path) -> str:
    """Names the ready marker: setup (uv sync, then prepare) runs again whenever uv.lock or pyproject.toml changes,
    so every new app version rebuilds what it stores, such as the int8 copies whose format the app can change
    without touching uv.lock, before the app starts and not during the first take."""
    h = hashlib.sha256()
    try:
        h.update((Path(app_dir) / "backend" / "uv.lock").read_bytes())
    except OSError:
        return "nolock"
    try:
        h.update(b"\0" + (Path(app_dir) / "backend" / "pyproject.toml").read_bytes())
    except OSError:
        pass
    return h.hexdigest()[:16]


def venv_python(home: Path, gui: bool = False) -> Path:
    scripts = Path(home) / "venv" / ("Scripts" if WIN else "bin")
    return scripts / (("pythonw.exe" if gui else "python.exe") if WIN else "python")


def model_env(home: Path) -> dict[str, str]:      # keep in sync with shadow.laptop.model_env (a test compares them)
    models = Path(home) / "models"
    return {"HF_HOME": str(models / "hf"), "MODELSCOPE_CACHE": str(models / "modelscope"),
            "TORCH_HOME": str(models / "torch"), "SHADOW_MODELS_DIR": str(models / "shadow")}


def laptop_config_text(home: Path) -> str:        # keep in sync with shadow.laptop.laptop_config_text
    data = json.dumps((Path(home) / "data").as_posix(), ensure_ascii=False)
    return (f'data_dir = {data}\n\n'
            '[models]\ndevice = "cpu"\nint8 = true\npunctuation = "sherpa"\n')


def ensure_laptop_config(home: Path) -> Path:
    path = Path(home) / "config.toml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(laptop_config_text(home), encoding="utf-8")
    return path


def _flags() -> int:
    return subprocess.CREATE_NO_WINDOW if WIN else 0


# ---------------------------------------------------------------- ports

# For our own 127.0.0.1 server only: no proxy. urlopen would send even loopback requests through a proxy from the
# environment (HTTP_PROXY, e.g. set to reach YouTube) or the Windows system proxy, which cannot reach this machine; the
# check would then never succeed and a running app would be taken for a failed start. Downloads keep the proxy.
_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _health_ok(port: int) -> bool:
    try:
        with _LOCAL.open(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def running_port(home: Path) -> int | None:
    try:
        port = int((Path(home) / "run" / "port").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return port if _health_ok(port) else None


def choose_port(preferred: int = PREFERRED_PORT) -> int:
    for port in (preferred, 0):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            return s.getsockname()[1]
        except OSError:
            continue
        finally:
            s.close()
    raise OSError("no free port")


# ---------------------------------------------------------------- setup

def ready_marker(home: Path, lock: str) -> Path:
    return Path(home) / "venv" / f".ready-{lock}"


def setup_needed(home: Path, lock: str) -> bool:
    return not ready_marker(home, lock).exists()


def first_setup(home: Path) -> bool:
    """True before this home was ever set up: no ready marker of any version and no stored models. Every new app
    version reruns setup, which then only updates the venv and checks the models."""
    venv, models = Path(home) / "venv", Path(home) / "models"
    if venv.is_dir() and any(venv.glob(".ready-*")):
        return False
    return not (models.is_dir() and any(p.is_file() for p in models.rglob("*")))


class SetupLock:
    """A cross-process lock on <home>/run/setup.lock (msvcrt on Windows, flock elsewhere); it dies with the process."""

    def __init__(self, home: Path):
        self.path = Path(home) / "run" / "setup.lock"
        self.f = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")
        try:
            if WIN:
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.f = f
        return True

    def release(self) -> None:
        f, self.f = self.f, None
        if f is None:
            return
        try:
            if WIN:
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            f.close()


def setup_running(home: Path) -> bool:
    lock = SetupLock(home)
    if lock.acquire():
        lock.release()
        return False
    return True


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


def _online() -> bool:
    for host in ("pypi.org", "github.com"):
        try:
            socket.create_connection((host, 443), timeout=3).close()
            return True
        except OSError:
            continue
    return False


def _run(cmd: list[str], env: dict[str, str], on_line: Callable[[str], None] | None = None,
         cwd: str | None = None, timeout: float | None = None) -> int:
    """Run a command with no window, feeding its output lines to on_line; return the exit code.
    With a timeout the process is killed when it expires."""
    p = subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=_flags())
    timer = threading.Timer(timeout, p.kill) if timeout else None
    if timer:
        timer.start()
    try:
        assert p.stdout is not None
        for line in p.stdout:
            if on_line:
                on_line(line.rstrip("\n"))
        return p.wait()
    finally:
        if timer:
            timer.cancel()


def _failure_text(detail: str, lines: list[str]) -> str:
    """The message for a failed step: a plain one when it looks like the network (output pattern or a failed probe)."""
    if _NETWORK.search(" ".join(lines + [detail])) or not _online():
        return NO_INTERNET
    return detail


def run_setup(home: Path, app_dir: Path, report: Callable[[dict], None], lock: SetupLock | None = None) -> bool:
    """One setup attempt. Pass the SetupLock the caller already holds (main does, across Retry); without one this
    takes and releases its own."""
    home, app_dir = Path(home), Path(app_dir)
    own = lock is None
    if own:
        lock = SetupLock(home)
        if not lock.acquire():
            report({"error": "Setup is already running"})
            return False
    try:
        return _setup(home, app_dir, report)
    except Exception as e:  # noqa: BLE001
        log(home, traceback.format_exc())
        report({"error": f"{type(e).__name__}: {e}"})
        return False
    finally:
        if own:
            lock.release()


def _setup(home: Path, app_dir: Path, report: Callable[[dict], None]) -> bool:
    home.mkdir(parents=True, exist_ok=True)
    first = first_setup(home)
    free, needed = free_gb(home), (NEEDED_GB if first else UPDATE_NEEDED_GB)
    if free < needed:
        report({"error": f"Not enough disk space: {free:.0f} GB free, about {needed} GB needed"})
        return False
    # a re-setup (every new app version) finds the models already there: it must not announce a 4 GB download
    size = {"size": f"about {MODELS_GB} GB"} if first else {}
    python_stage = "Setting up Python" if first else "Updating the app"
    models_stage = f"Downloading speech models ({size['size']})" if first else "Checking speech models"
    prepare_stage = "Preparing models" if first else "Checking speech models"
    base = {**os.environ, "PYTHONUTF8": "1", "UV_HTTP_TIMEOUT": "10", "UV_PROJECT_ENVIRONMENT": str(home / "venv"),
            "UV_CACHE_DIR": str(home / "uv-cache")}
    tail: list[str] = []

    def stage(name: str, done: int = 0, total: int = 1, **extra) -> None:
        report({"stage": name, **extra, **size, "done": done, "total": total, "update": not first})

    def keep(line: str) -> None:
        log(home, line)
        tail.append(line)
        del tail[:-20]

    stage(python_stage)
    sync = [str(app_dir / "uv.exe"), "sync", "--frozen", "--no-dev", "--extra", "models", "--extra", "desktop",
            "--python", str(app_dir / "python" / "python.exe")]
    if _run(sync, base, keep, cwd=str(app_dir / "backend")) != 0:
        report({"error": _failure_text(f"{python_stage} failed: " + (tail[-1] if tail else "see bootstrap.log"),
                                       tail)})
        return False

    stage(models_stage)
    failure: list[str] = []

    def relay(line: str) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            keep(line)
            return
        if not isinstance(msg, dict):
            return
        if "error" in msg:
            failure.append(str(msg["error"]))
        elif "step" in msg:
            stage(prepare_stage, msg.get("done", 0), msg.get("total", 1), detail=msg["step"])

    config = ensure_laptop_config(home)
    env = {**base, **model_env(home), "SHADOW_CONFIG": str(config), "PYTHONPYCACHEPREFIX": str(home / "pycache")}
    code = _run([str(venv_python(home)), "-m", "shadow.laptop", "prepare"], env, relay)
    if code != 0 or failure:
        report({"error": _failure_text(failure[-1] if failure else f"Preparing models failed (exit {code})",
                                       tail + failure)})
        return False

    marker = ready_marker(home, lock_hash(app_dir))
    marker.parent.mkdir(parents=True, exist_ok=True)
    for old in marker.parent.glob(".ready-*"):
        try:
            old.unlink()
        except OSError:
            pass
    marker.write_text("ok", encoding="utf-8")
    for old in (home / "run").glob("ytdlp-*"):    # uv sync put the locked yt-dlp back: update it again today
        try:
            old.unlink()
        except OSError:
            pass
    return True


def update_ytdlp(home: Path, app_dir: Path) -> None:
    """Once a day, upgrade yt-dlp inside the venv; any failure is ignored (the old version keeps working)."""
    home = Path(home)
    marker = home / "run" / f"ytdlp-{datetime.date.today().isoformat()}"
    if marker.exists():
        return
    try:
        env = {**os.environ, "PYTHONUTF8": "1", "UV_HTTP_TIMEOUT": "10", "UV_CACHE_DIR": str(home / "uv-cache")}
        _run([str(Path(app_dir) / "uv.exe"), "pip", "install", "--upgrade-package", "yt-dlp",
              "--upgrade-package", "yt-dlp-ejs", "yt-dlp[default]", "--python", str(venv_python(home))],
             env, lambda line: log(home, line), timeout=YTDLP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        log(home, f"yt-dlp update failed: {e}")
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        for old in marker.parent.glob("ytdlp-*"):
            old.unlink()
        marker.write_text("1", encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- progress page

class Progress:
    def __init__(self):
        self.status: dict = {"stage": "Starting", "done": 0, "total": 1}
        self.retry = threading.Event()
        self.last_poll: float | None = None

    def report(self, msg: dict) -> None:
        self.status = msg

    def polled(self, now: float | None = None) -> None:
        self.last_poll = time.monotonic() if now is None else now

    def page_open(self, now: float | None = None) -> bool:
        """Whether the progress tab is still polling: only then does it redirect itself to the app at the end."""
        if self.last_poll is None:
            return False
        return (time.monotonic() if now is None else now) - self.last_poll < PAGE_GONE_AFTER


def make_progress_server(progress: Progress, port: int) -> ThreadingHTTPServer:
    html = (HERE / "progress.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, html, "text/html; charset=utf-8")
            elif self.path == "/status":
                progress.polled()
                self._send(200, json.dumps(progress.status).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802
            if self.path == "/retry":
                progress.retry.set()
                self._send(200, b"{}", "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *args):  # silent (stderr may be None under pythonw)
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def setup_port_file(home: Path) -> Path:
    return Path(home) / "run" / "setup-port"


def start_launcher(home: Path, app_dir: Path, port: int, no_browser: bool = False) -> subprocess.Popen:
    config = ensure_laptop_config(home)
    env = {**os.environ, **model_env(home), "PYTHONUTF8": "1", "PYTHONPYCACHEPREFIX": str(home / "pycache"),
           "SHADOW_CONFIG": str(config),
           "SHADOW_FRONTEND_DIST": str(app_dir / "frontend" / "dist"),
           "SHADOW_ICON": str(app_dir / "icon.ico"),
           "PATH": str(app_dir / "tools") + os.pathsep + os.environ.get("PATH", "")}
    flags = 0
    if WIN:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    cmd = [str(venv_python(home, gui=True)), "-m", "shadow.launcher", "--port", str(port), "--home", str(home)]
    if no_browser:
        cmd.append("--no-browser")
    return subprocess.Popen(cmd, env=env, cwd=str(home), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True)


def default_app_dir() -> Path:
    env = os.environ.get("SHADOW_APP_DIR")
    return Path(env) if env else Path(sys.executable).resolve().parent.parent


def wait_running(home: Path, seconds: float) -> int | None:
    end = time.time() + seconds
    while True:
        port = running_port(home)
        if port:
            return port
        if time.time() >= end:
            return None
        time.sleep(0.5)


def _second_instance(home: Path) -> int:
    """Another bootstrap holds the lock (setting up, or starting the app): show the progress page if there is one,
    else wait (bounded) for the app and open it."""
    end = time.time() + LAUNCH_WAIT
    while time.time() < end:
        try:
            open_browser(f"http://127.0.0.1:{int(setup_port_file(home).read_text().strip())}/")
            return 0
        except (OSError, ValueError):
            pass
        port = running_port(home)
        if port:
            open_browser(f"http://127.0.0.1:{port}/")
            return 0
        time.sleep(0.5)
    log(home, "another instance holds the lock but never became ready")
    return 1


def main() -> int:
    home = home_dir()
    app_dir = default_app_dir()
    log(home, "bootstrap start")
    port = running_port(home)
    if port:
        open_browser(f"http://127.0.0.1:{port}/")
        return 0
    lock = SetupLock(home)
    if not lock.acquire():
        return _second_instance(home)
    try:                                           # held until the app answers, so a double-click cannot start a second
        return _first_instance(home, app_dir, lock)
    finally:
        lock.release()


def _first_instance(home: Path, app_dir: Path, lock: SetupLock) -> int:
    port = choose_port()
    progress = Progress()
    servers: list[ThreadingHTTPServer] = []

    def serve() -> None:
        server = make_progress_server(progress, port)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        setup_port_file(home).parent.mkdir(parents=True, exist_ok=True)
        setup_port_file(home).write_text(str(port), encoding="utf-8")

    def stop() -> None:
        while servers:
            server = servers.pop()
            server.shutdown()
            server.server_close()
        try:
            setup_port_file(home).unlink()
        except OSError:
            pass

    def wait_retry() -> None:
        progress.retry.clear()
        progress.retry.wait()                      # the Retry button; the page shows the error meanwhile

    shown = setup_needed(home, lock_hash(app_dir))
    if shown:
        serve()
        open_browser(f"http://127.0.0.1:{port}/")
        while not run_setup(home, app_dir, progress.report, lock):
            wait_retry()
        progress.report({"stage": "Starting", "done": 1, "total": 1})
    update_ytdlp(home, app_dir)
    while True:
        # a progress tab that still polls redirects itself to the app; else (none shown, or it was closed during
        # setup) the launcher opens the browser itself
        page = shown and progress.page_open()
        stop()                                     # the app takes over this port
        proc = start_launcher(home, app_dir, port, no_browser=page)
        if wait_running(home, LAUNCH_WAIT):
            return 0
        log(home, "the launcher did not answer in time")
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        if not shown:
            return 1
        progress.report({"error": f"The app could not start \u2014 see {home / 'logs'}"})
        serve()
        wait_retry()
        progress.report({"stage": "Starting", "done": 1, "total": 1})


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        log(home_dir(), traceback.format_exc())
        sys.exit(1)
