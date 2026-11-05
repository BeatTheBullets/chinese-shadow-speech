"""Windows launcher: `python -m shadow.launcher --port P --home DIR` runs the backend in a thread, opens the Library in the
default browser once the server answers, and shows a tray icon with Open and Quit. pystray and Pillow are imported only
inside `main()` / the icon factory, so tests and Linux work without them (the launcher then runs headless)."""
from __future__ import annotations
import argparse
import logging
import logging.handlers
import os
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

log = logging.getLogger("shadow.launcher")
TOOLTIP = "chinese-shadow-speech"


class ServerHandle:
    """A uvicorn server for `app` on 127.0.0.1:port, run in a daemon thread."""

    def __init__(self, app, port: int):
        import uvicorn
        self.port = port
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False,
                                                          timeout_graceful_shutdown=5))
        self.thread = threading.Thread(target=self.server.run, name="uvicorn", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def wait_ready(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < deadline:
            if self.thread.ident is not None and not self.thread.is_alive():
                return False                      # the server died (e.g. the port is taken)
            if self.thread.is_alive():
                try:
                    with urllib.request.urlopen(url, timeout=1) as r:
                        if r.status == 200:
                            return True
                except OSError:
                    pass
            time.sleep(0.1)
        return False

    def stop(self, timeout: float = 30) -> None:
        """Graceful: uvicorn runs the app's lifespan shutdown before the thread ends."""
        self.server.should_exit = True
        try:                                   # off the main thread uvicorn installs no signal handlers: tell SSE streams to end
            from sse_starlette.sse import AppStatus
            AppStatus.should_exit = True
        except Exception:  # noqa: BLE001
            pass
        if self.thread.ident is not None:
            self.thread.join(timeout)


def port_file(home: Path) -> Path:
    return Path(home) / "run" / "port"


def write_port_file(home: Path, port: int) -> None:
    path = port_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(str(port), encoding="utf-8")
    os.replace(tmp, path)


def remove_port_file(home: Path) -> None:
    try:
        port_file(home).unlink()
    except FileNotFoundError:
        pass


def make_quit(handle: ServerHandle, home: Path, stop_icon: Callable[[], None]) -> Callable[[], None]:
    def quit_() -> None:
        try:
            handle.stop()
        finally:
            remove_port_file(home)
            stop_icon()
    return quit_


def ensure_streams() -> None:
    """Under pythonw sys.stdout/stderr are None; tqdm and print would raise. Give them a null writer."""
    import sys
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def setup_logging(home: Path) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        logs = Path(home) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(logs / "launcher.log", maxBytes=256_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
    except OSError:
        pass
    if not any(isinstance(x, logging.Handler) for x in root.handlers):
        logging.basicConfig(level=logging.INFO)


def icon_path() -> Path | None:
    env = os.environ.get("SHADOW_ICON")
    candidates = [Path(env)] if env else []
    root = Path(__file__).resolve().parents[2]            # <app>/backend/shadow/launcher.py -> <app>
    candidates += [root / "icon.ico", root / "packaging" / "windows" / "icon.ico", root.parent / "packaging" / "windows" / "icon.ico"]
    return next((c for c in candidates if c.is_file()), None)


def load_icon_image():
    from PIL import Image
    path = icon_path()
    if path is not None:
        try:
            img = Image.open(path)
            img.load()
            return img
        except Exception:  # noqa: BLE001
            log.warning("icon %s unreadable, using a plain square", path, exc_info=True)
    return Image.new("RGB", (64, 64), (176, 48, 48))


def main(argv: list[str] | None = None) -> int:
    ensure_streams()
    ap = argparse.ArgumentParser(prog="shadow.launcher")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--home", type=Path, required=True)
    args = ap.parse_args(argv)
    home: Path = args.home
    setup_logging(home)
    remove_port_file(home)                                # a stale file from a crashed run
    from shadow.laptop import model_env
    for k, v in model_env(home).items():
        os.environ.setdefault(k, v)                       # explicit env wins; set before the app imports torch etc.
    os.environ.setdefault("SHADOW_CONFIG", str(home / "config.toml"))
    try:
        from shadow.main import create_app
        handle = ServerHandle(create_app(), args.port)
    except Exception:  # noqa: BLE001
        log.exception("could not build the app")
        return 1
    handle.start()
    url = f"http://127.0.0.1:{args.port}/"

    def after_ready() -> None:
        if handle.wait_ready(180) and not handle.server.should_exit:
            write_port_file(home, args.port)
            log.info("server ready on %s", url)
            webbrowser.open(url)
        else:
            log.error("server did not become ready")

    threading.Thread(target=after_ready, name="ready", daemon=True).start()

    user_quit = threading.Event()

    def headless() -> None:
        try:
            while handle.alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            user_quit.set()
        finally:
            handle.stop()
            remove_port_file(home)

    def result() -> int:
        if user_quit.is_set():
            return 0
        log.error("server stopped without a quit request")
        return 1

    try:
        import pystray
        image = load_icon_image()
    except Exception as e:  # noqa: BLE001
        log.warning("tray unavailable (%s: %s); running headless", type(e).__name__, e)
        headless()
        return result()

    holder: dict = {}
    stop_all = make_quit(handle, home, lambda: holder["icon"].stop())

    def quit_() -> None:
        user_quit.set()
        stop_all()

    menu = pystray.Menu(
        pystray.MenuItem("Open", lambda icon, item: webbrowser.open(url), default=True),
        pystray.MenuItem("Quit", lambda icon, item: threading.Thread(target=quit_, daemon=True).start()))
    icon = pystray.Icon("shadow", image, TOOLTIP, menu)
    holder["icon"] = icon

    def watch() -> None:                                   # the server died on its own: do not leave a dead tray icon
        while handle.alive():
            time.sleep(1)
        remove_port_file(home)
        icon.stop()

    threading.Thread(target=watch, name="watch", daemon=True).start()
    try:
        icon.run()
    except Exception:  # noqa: BLE001
        log.exception("tray failed; running headless")
        headless()
        return result()
    handle.stop()
    remove_port_file(home)
    return result()


if __name__ == "__main__":
    raise SystemExit(main())
