#!/usr/bin/env python3
"""DataPiler: extracts Elden Ring's data from the owner's own install through Smithbox, for EldenNet's research.

    python datapiler.py [--console] [--port N] [--no-browser] [--no-link]

--console: this console is the app's own (colours, the close event). --no-browser: the launcher opens the page.
--no-link: the owner answered N, so grpc is never imported.

Exit codes: 0 stopped; 1 a crash; 2 the page's port did not open; 3 already running; 75 update requested
(Install and restart: DataPiler.ps1 then runs the helper from the verified download, build plan 0.2 §4.8).

The start and stop sequence is build plan §4.11, with build plan 0.2 §3.4 and §4.8: the port of the page that asked
for an update, the install check, the clean-up and Detect at start once the page is up. `start_log`, `running_port`, the bind, nonce, hosts, origins and port
file of `main` and the crash catch at the bottom are adapted from LLM Jobrunner 1.2 (build plan §7.1)."""

from __future__ import annotations

import argparse
import http.client
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from datapiler import NAME, VERSION, env, events, fileio, install, logbook, paths, settings, winapi  # noqa: E402
from datapiler.api import Api, Live, set_masks  # noqa: E402
from datapiler.logbook import own  # noqa: E402
from datapiler.server import App, Server  # noqa: E402
from datapiler.status import Status  # noqa: E402

MUTEX = "Local\\DataPiler"
CLOSE_WAIT = 4.3
EXIT_UPDATE = 75            # Install and restart: the window swaps the files (design 0002 §2.5)

log = logbook.get("app")


# ---------------------------------------------------------------------------------------------------------- helpers


def start_log(root: Path, text: str) -> None:
    """datapiler-start.log, only when the page never came up: the time and the masked text."""
    try:
        with open(Path(root) / "datapiler-start.log", "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), logbook.mask(text)))
    except OSError:
        pass


def crash_text(e: BaseException, p: paths.Paths | None) -> str:
    tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
    lines = ["%s did not start: %s" % (NAME, logbook.why(e)), tb.rstrip(), str(env.python_info())]
    if p is not None:
        try:
            lines.append(str(env.venv_state(p)))
        except Exception:
            pass
    return "\n".join(lines)


def running_port(p: paths.Paths) -> int:
    """The port of a DataPiler already running from this folder, or 0: its port file, and its page answering as
    DataPiler's. Used only when the mutex is held by another."""
    try:
        port = int(fileio.read_limited(p.port_file, 16).decode("ascii").strip() or 0)
        if not 1 <= port <= 65535:
            return 0
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=1.5)
        try:
            c.request("GET", "/", headers={"Host": "127.0.0.1:%d" % port})
            r = c.getresponse()
            r.read()
        finally:
            c.close()
        return port if r.status == 200 and (r.getheader("Server") or "").startswith(NAME) else 0
    except (OSError, ValueError, http.client.HTTPException):
        return 0


def parse(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="datapiler.py",
                                 description="DataPiler: Elden Ring's data from your own install, through Smithbox.")
    ap.add_argument("--console", action="store_true", help="this console is the app's own (colours, the close event)")
    ap.add_argument("--port", type=int, help="the page's port (else Settings', else any free one)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the page (DataPiler.exe opens it)")
    ap.add_argument("--no-link", action="store_true", help="start without the server link (grpc is never imported)")
    a = ap.parse_args(argv)
    if a.port is not None and not (a.port == 0 or 1024 <= a.port <= 65535):
        ap.error("--port must be 0 or 1024 to 65535")
    return a


# ---------------------------------------------------------------------------------------------------------- parts


class RealParts:
    """Builds the real TextDB, Guard, Link, Runner and Inbox (JOBS's and LINK's modules)."""

    def store(self, live: Live):
        from datapiler import guard as guard_mod, textdb as textdb_mod
        tdb = textdb_mod.TextDB(live.paths.textdb)
        b = winapi.backend()

        def owner_words() -> list[str]:
            return [w for w in (b.user_name(), b.pc_name()) if w]

        return tdb, guard_mod.Guard(tdb, owner_words)

    def port_answers(self, game: Callable) -> bool | None:
        from datapiler import link as link_mod
        return link_mod.port_answers(game)

    def link(self, status: Status, no_link: bool):
        from datapiler import link as link_mod
        libs = (not no_link) and bool(link_mod.available()[0])
        return link_mod.Link(status.game_running, libs=libs), libs

    def runner(self, live: Live, link, textdb, guard, status: Status):
        from datapiler import runner as runner_mod
        # the current Paths at each write: Settings can move the workspace and the share folder
        return runner_mod.Runner(lambda: live.paths, link, textdb, guard, status.provenance, status.game_running,
                                 lambda: live.settings.language, map_opengl=lambda: live.settings.map_opengl)

    def inbox(self, live: Live, textdb):
        from datapiler import catalogue, inbox as inbox_mod

        def expected() -> set[str]:
            return {c for row in catalogue.ROWS for c in row.containers}

        return inbox_mod.Inbox(lambda: live.paths, textdb, lambda: live.settings.language, expected)

    def catalogue(self):
        from datapiler import catalogue
        return catalogue

    def folders(self, live: Live):
        from datapiler import detect
        return detect.Folders(live)

    def updater(self, run: "Run"):
        # The one network module (S27): built here, reached only through POST /api/update.
        from datapiler import update
        return update.Updater(root=run.root, version=VERSION, port=lambda: run.port, busy=run.runner.busy,
                              request_exit=run.request_update_exit)


# ---------------------------------------------------------------------------------------------------------- the run


class Run:
    """One start of DataPiler, from the mutex to the stop."""

    def __init__(self, root: Path, args: argparse.Namespace, parts: object):
        self.root = root
        self.args = args
        self.parts = parts
        self.paths: paths.Paths | None = None
        self.holder = None
        self.httpd: Server | None = None
        self.port = 0
        self.textdb = self.guard = self.link = self.runner = self.inbox = None
        self.status: Status | None = None
        self.api: Api | None = None
        self.folders = self.updates = None
        self.pending: install.Pending | None = None
        self.exit_code = 0
        self.page_up = False
        self._stop_lock = threading.Lock()
        self._stopping = False
        self._done = threading.Event()
        self._window = False

    # -------------------------------------------------------------------------------------------- start

    def start(self) -> int:
        # 1. the root, the settings, the paths
        cfg, problems = settings.load(self.root / "settings.json", root=self.root)
        p = self.paths = paths.resolve(self.root, cfg.workspace_dir, cfg.share_dir)
        # 2. one DataPiler a folder
        self.holder = winapi.backend().hold_mutex(MUTEX, p.mutex_file)
        if self.holder is None:
            port = running_port(p)
            print("%s is running already: http://127.0.0.1:%d/" % (NAME, port) if port
                  else "%s is running already" % NAME, flush=True)
            return 3
        # 3. a port file left by a killed run
        try:
            p.port_file.unlink()
        except FileNotFoundError:
            pass
        # 4. the folders, the log, its masks, the environment
        paths.ensure(p)
        logbook.setup(p.logs, max_bytes=cfg.log_max_mb * 1024 * 1024, keep=cfg.log_keep, console=self.args.console)
        live = Live(root=self.root, settings=cfg, paths=p, session=settings.Session())
        set_masks(live)
        log.info("%s %s starting", own(NAME), own(VERSION))
        for problem in problems:
            log.warn("%s", problem)
        # an update's request, written at Install by the version before (any age; checked field by field)
        pending = self.pending = install.read_pending(self.root)
        try:
            remote = winapi.backend().drive_is_remote(str(p.workspace))
        except Exception:
            remote = False
        if remote:      # DataPiler's own folder on a network drive, with the workspace in it (settings.check)
            log.warn("the workspace is on a network drive, but the game's text stays on this PC - set a workspace "
                     "folder on this PC in Settings")
        self._env_lines(p)
        # 5. the parts
        parts = self.parts
        self.textdb, self.guard = parts.store(live)
        found = []
        try:
            found = list(self.guard.check_labels())
        except Exception as e:
            logbook.get("guard").warn("the labels could not be checked: %s", logbook.why(e))
        if found:
            logbook.get("guard").warn("%s of DataPiler's labels occur in the text database (S6): they are to be "
                                      "renamed", logbook.n(len(found)))
        self.status = status = Status(lambda: live.settings, lambda: self.link,
                                      lambda: parts.port_answers(status.game_running))
        self.link, libs = parts.link(status, self.args.no_link)
        self.runner = parts.runner(live, self.link, self.textdb, self.guard, status)
        self.runner.load_folder()
        self.inbox = parts.inbox(live, self.textdb)
        self.inbox.start()
        self._smithbox_line(live)
        # FOLDERS's Detect and UPDATE's Updater; a part list without them (older tests' fakes) gives None
        self.folders = parts.folders(live) if hasattr(parts, "folders") else None
        self.updates = parts.updater(self) if hasattr(parts, "updater") else None
        self.api = Api(live=live, status=status, link=self.link, runner=self.runner, textdb=self.textdb,
                       guard=self.guard, inbox=self.inbox, catalogue=parts.catalogue(), stop=self.request_stop,
                       libs=libs, updates=self.updates, folders=self.folders)
        # 6. the page's port: --port, else the port of the page that asked for the update, else Settings', else any
        reloads = False
        if self.args.port is not None:
            port = self.args.port
        elif pending is not None and pending.port:
            port, reloads = pending.port, True
        else:
            port = cfg.port
        app = App(self.api)
        try:
            try:
                self.httpd = Server(port, app)
            except OSError:
                if not reloads:
                    raise
                reloads = False
                log.warn("the page's port before the update was taken - a new tab opens")
                port = cfg.port if cfg.port != pending.port else 0
                self.httpd = Server(port, app)
        except OSError as e:
            start_log(self.root, "the page's port %d did not open: %s" % (port, logbook.why(e)))
            log.error("the page's port %s did not open: %s - set another in Settings or use --port",
                      logbook.n(port), logbook.why(e))
            print("the page's port %d did not open (%s): another program has it - set another in Settings or use "
                  "--port" % (port, logbook.why(e)), file=sys.stderr, flush=True)
            self.stop()
            return 2
        # 7. the port file, the page's line
        self.port = self.httpd.port
        fileio.write_atomic(p.port_file, str(self.port).encode("ascii"))
        self.page_up = True
        url = "http://127.0.0.1:%d/" % self.port
        if reloads:
            log.info("Page: http://127.0.0.1:%s/ (the open page reloads)", self.port)
        else:
            log.info("Page: http://127.0.0.1:%s/ (the browser opens it)", self.port)
        if not self.args.console:
            print("%s %s - %s (Quit on the page, or Ctrl+C here, stops it)" % (NAME, VERSION, url), flush=True)
        if not self.args.no_browser and not reloads:
            import webbrowser
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        self._after_page_up(pending)
        # 8. the close event, then the page until Quit
        if self.args.console:
            winapi.backend().on_console_close(self.window_closed)
        try:
            self.httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            log.info("Ctrl+C - stopping")
        finally:
            self.stop()
        return self.exit_code

    def _after_page_up(self, pending: install.Pending | None) -> None:
        """Once the page is up (build plan 0.2 §4.8): the install check, an update's result kept for the page,
        update/pending.json removed, the clean-up of update/, then Detect for the folders still to find."""
        try:
            check = install.install_check(self.root)
            install.check_line(check)
            if self.updates is not None:
                self.updates.came_back(pending, check)
        except Exception as e:
            log.warn("the install check failed: %s", logbook.why(e))
        install.remove_pending(self.root)
        try:
            install.cleanup(self.root)
        except Exception as e:
            log.warn("the clean-up of update/ failed: %s", logbook.why(e))
        if self.folders is not None:
            try:
                self.folders.at_start()
            except Exception as e:
                logbook.get("folders").warn("Detect at start failed: %s", logbook.why(e))

    def _env_lines(self, p: paths.Paths) -> None:
        e = logbook.get("env")
        e.info("%s", env.python_info())
        e.info("venv: %s", env.venv_state(p))
        if self.args.no_link:
            e.info("the server link is off for this run (--no-link): grpcio and protobuf are not loaded")
            return
        v = env.library_versions()
        e.info("grpcio %s, protobuf %s", v.get("grpcio") or own("not installed"),
               v.get("protobuf") or own("not installed"))

    def _smithbox_line(self, live: Live) -> None:
        from datapiler import smithbox
        sb = logbook.get("smithbox")
        s = live.settings
        try:
            if not s.smithbox_dir:
                sb.info("the Smithbox folder is not set - set it in Settings")
                return
            if not smithbox.installed(s.smithbox_dir):
                sb.warn("no Smithbox exe (Smithbox*.exe) is in <SMITHBOX> - check the folder in Settings")
                return
            run = smithbox.running(s.smithbox_dir)
            sw = smithbox.read_switch(smithbox.startup_json())
            sb.info("found in <SMITHBOX> - %s, server %s",
                    own("running" if run else ("not known if running" if run is None else "not running")),
                    own("on" if sw is True else ("off" if sw is False else "switch not read")))
        except Exception as e:
            sb.warn("the status reads failed: %s", logbook.why(e))

    # -------------------------------------------------------------------------------------------- stop

    def request_stop(self) -> None:
        """Quit on the page: the server stops after the answer, then the stop sequence runs."""
        httpd = self.httpd
        if httpd is not None:
            httpd.shutdown()

    def request_update_exit(self) -> None:
        """Install and restart, after its answer: the stop as Quit does it, then exit code 75, on which
        DataPiler.ps1 runs the helper (update.py logs the update requested line)."""
        self.exit_code = EXIT_UPDATE
        self.request_stop()

    def window_closed(self) -> None:
        """The console's close, logoff or shutdown event: stop, and wait for it (Windows allows about 5 s)."""
        self._window = True
        threading.Thread(target=self.request_stop, name="window-close", daemon=True).start()
        self._done.wait(CLOSE_WAIT)

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopping:
                return
            self._stopping = True
        try:
            if self._window:
                log.info("window closed - stopping")
            events.emit("app.stopping")
            for what, fn in (
                    ("link", lambda: self.link.close(own("DataPiler is stopping")) if self.link else None),
                    ("runner", lambda: self.runner.stop(cancel=True) if self.runner else None),
                    ("inbox", lambda: self.inbox.stop() if self.inbox else None),
                    ("guard", lambda: self.guard.close() if self.guard is not None and hasattr(self.guard, "close")
                     else None),
                    ("textdb", lambda: self.textdb.close() if self.textdb else None),
                    ("status", lambda: self.status.close() if self.status else None),
                    ("api", lambda: self.api.close() if self.api else None)):
                try:
                    fn()
                except Exception as e:
                    log.error("stopping the %s failed: %s", own(what), logbook.why(e))
            if self.httpd is not None:
                try:
                    self.httpd.server_close()
                except OSError:
                    pass
            self._remove_port_file()
            log.info("stopped")
            logbook.shutdown()
        finally:
            if self.holder is not None:
                try:
                    self.holder.release()
                except Exception:
                    pass
            self._done.set()

    def _remove_port_file(self) -> None:
        if self.paths is None or not self.port:
            return
        try:
            mine = fileio.read_limited(self.paths.port_file, 16).decode("ascii").strip() == str(self.port)
            if mine:
                os.remove(self.paths.port_file)
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None, *, root: Path | None = None, parts: object | None = None) -> int:
    """The command line's run; root and parts are for tests (a temp folder, fakes of JOBS's and LINK's parts)."""
    args = parse(argv)
    root = Path(root).resolve() if root is not None else HERE
    b = winapi.backend()
    try:
        logbook.set_masks(folders={"<DATAPILER>": str(root)}, home=b.home(), user=b.user_name(), pc=b.pc_name())
    except Exception:
        pass
    # An exception no thread catches is logged by its type, never printed with its traceback to the window.
    restore_hooks = logbook.install_excepthooks()
    run = Run(root, args, parts if parts is not None else RealParts())
    try:
        return run.start()
    except BaseException as e:
        if isinstance(e, SystemExit):
            raise
        if not run.page_up:
            start_log(root, crash_text(e, run.paths))
        try:
            log.error("crashed: %s", logbook.why(e))
        except Exception:
            pass
        if run.holder is not None:
            run.stop()
        if isinstance(e, KeyboardInterrupt):
            return 0
        return 1
    finally:
        restore_hooks()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:                # a crash before main's own catch
        start_log(HERE, crash_text(exc, None))
        sys.exit(1)
