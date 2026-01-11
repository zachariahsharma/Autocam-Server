import adsk.core, adsk.fusion, adsk.cam, traceback
import os
import queue
import re
import sys
import threading
import time
from typing import List, Optional
from .workflows import importPlate as importPlate
from .workflows import camPlate as camPlate
from .workflows import camTube as camTube
from .workflows import setupTemp as setupTemp
from .config import *
import requests

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
_ENV_PATH = os.path.join(_ADDIN_DIR, ".env")
_API_KEY_LINE_RE = re.compile(r"^\s*API_KEY\s*=\s*(?P<value>.*)\s*$")


_app = adsk.core.Application.cast(None)
_ui = adsk.core.UserInterface.cast(None)
_server_thread = None  # type: Optional[threading.Thread]
_stop_event = None  # type: Optional[threading.Event]
session = None  # type: Optional[requests.Session]
_custom_event = None  # type: Optional[adsk.core.CustomEvent]
_handlers = []  # type: List[adsk.core.EventHandler]
_job_queue = queue.Queue()  # type: queue.Queue
_log_queue = queue.Queue()  # type: queue.Queue
_job_processing = threading.Event()

_JOB_QUEUE_EVENT_ID = f"{ADDIN_NAME}_job_queue_event"


def _drain_queue(q: "queue.Queue") -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break
        try:
            q.task_done()
        except Exception:
            pass


def _queue_log(message: str) -> None:
    try:
        _log_queue.put_nowait(message)
        _fire_job_queue_event()
    except Exception:
        pass


def _fire_job_queue_event() -> None:
    try:
        if _app:
            _app.fireCustomEvent(_JOB_QUEUE_EVENT_ID, "")
    except Exception:
        pass


def _process_job(job: dict, session: requests.Session) -> None:
    kind = job.get("kind")
    _app.log(str(job))
    if kind == "plate:cam":
        camPlate.start(job, session)
    elif kind == "box_tube":
        camTube.start(job, session)
    elif kind == "plate:arrange":
        importPlate.start(job, session)
    else:
        raise ValueError(f"Unknown job type: {kind!r}")


class _JobQueueEventHandler(adsk.core.CustomEventHandler):
    def __init__(self, session: requests.Session):
        super().__init__()
        self.session = session

    def notify(self, args: "adsk.core.CustomEventArgs") -> None:
        try:
            while True:
                try:
                    message = _log_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if _app:
                        _app.log(str(message))
                finally:
                    _log_queue.task_done()

            if _job_processing.is_set():
                return

            while True:
                try:
                    job = _job_queue.get_nowait()
                except queue.Empty:
                    break

                _job_processing.set()
                try:
                    _process_job(job, session=self.session)
                except Exception:
                    if _app:
                        _app.log(
                            "Error processing job:\n{}".format(traceback.format_exc())
                        )
                finally:
                    _job_processing.clear()
                    _job_queue.task_done()
        except Exception:
            if _app:
                _app.log(
                    "Error in job queue event handler:\n{}".format(
                        traceback.format_exc()
                    )
                )


def _mask_api_key(api_key: Optional[str]) -> str:
    if not api_key:
        return "<not set>"
    api_key = api_key.strip()
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}…{api_key[-4:]}"


def _read_api_key_from_env_file(env_path: str) -> Optional[str]:
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                match = _API_KEY_LINE_RE.match(line)
                if not match:
                    continue
                value = match.group("value").strip()
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                value = value.strip()
                return value or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _write_api_key_to_env_file(env_path: str, api_key: str) -> None:
    api_key = api_key.strip()
    safe_value = api_key.replace("\\", "\\\\").replace('"', '\\"')
    api_key_line = f'API_KEY="{safe_value}"\n'

    lines = []  # type: List[str]
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    replaced = False
    new_lines = []  # type: List[str]
    for line in lines:
        if _API_KEY_LINE_RE.match(line):
            new_lines.append(api_key_line)
            replaced = True
        else:
            new_lines.append(line)

    if not replaced:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"
        new_lines.append(api_key_line)

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def _prompt_for_api_key(
    ui: adsk.core.UserInterface, existing_key: Optional[str]
) -> Optional[str]:
    default_value = (existing_key or "").strip()
    while True:
        value, cancelled = ui.inputBox(
            "Enter your API key (stored locally in this add-in's .env file).",
            "API Key",
            default_value,
        )
        if cancelled:
            return None
        value = (value or "").strip()
        if value:
            return value
        ui.messageBox("API key cannot be empty.")


def _startup_key_gate(
    ui: adsk.core.UserInterface, api_key: Optional[str], timeout_s: int = 10
) -> Optional[str]:
    if not api_key:
        new_key = _prompt_for_api_key(ui, existing_key=None)
        if not new_key:
            return None
        _write_api_key_to_env_file(_ENV_PATH, new_key)
        os.environ["API_KEY"] = new_key
        return new_key

    progress = ui.createProgressDialog()
    progress.isCancelButtonShown = True
    progress.show(
        "Starting Add-In",
        "",
        0,
        max(timeout_s, 1),
        1,
    )

    start_time = time.monotonic()
    last_shown_remaining = None
    while True:
        elapsed = time.monotonic() - start_time
        remaining = max(0, int(timeout_s - elapsed))
        if remaining != last_shown_remaining:
            progress.message = (
                f"API key {_mask_api_key(api_key)} loaded.\n"
                f"Starting in {remaining} seconds...\n\n"
                "Click Cancel to edit the API key."
            )
            progress.progressValue = int(elapsed)
            last_shown_remaining = remaining

        adsk.doEvents()

        if progress.wasCancelled:
            progress.hide()
            new_key = _prompt_for_api_key(ui, existing_key=api_key)
            if new_key:
                _write_api_key_to_env_file(_ENV_PATH, new_key)
                os.environ["API_KEY"] = new_key
                return new_key
            return api_key

        if elapsed >= timeout_s:
            break

        time.sleep(0.1)

    progress.hide()
    os.environ["API_KEY"] = api_key
    return api_key


def handleServer(temp_dir: str, stop_event: threading.Event):
    while not stop_event.is_set():
        # for i in range(1):
        try:
            time.sleep(5)
            if _job_processing.is_set() or not _job_queue.empty():
                stop_event.wait(0.2)
                continue
            if session is None:
                raise RuntimeError("HTTP session not initialized.")
            response = session.post(
                "http://localhost:3000/api/jobs/request",
                # json={"kind": "plate:cam"},
                timeout=30,
            )
            if stop_event.is_set():
                break
            if response.status_code == 204:
                stop_event.wait(0.5)
                continue
            data = response.json()
            if not isinstance(data, dict):
                raise TypeError(f"Unexpected job payload type: {type(data)}")
            payload = data.get("payload")
            if not isinstance(payload, dict):
                payload = {}
                data["payload"] = payload
            try:
                if isinstance(payload, dict) and payload.get("assignments"):
                    setupTemp.downloadFiles(temp_dir, data, session)
            except Exception:
                _queue_log(
                    "Error downloading files:\n{}".format(traceback.format_exc())
                )

            if stop_event.is_set():
                break
            _job_queue.put(data)
            _fire_job_queue_event()
        except Exception:
            _queue_log("Error handling job:\n{}".format(traceback.format_exc()))
            stop_event.wait(1)


def run(_context):
    ui = None
    fusion_app = None
    try:
        fusion_app = adsk.core.Application.get()
        ui = fusion_app.userInterface
        global _app, _ui, _server_thread, _stop_event, session, _custom_event, _handlers
        _app, _ui = fusion_app, ui

        api_key = _startup_key_gate(
            ui, _read_api_key_from_env_file(_ENV_PATH), timeout_s=1
        )
        if not api_key:
            ui.messageBox("Add-in not started (no API key set).")
            return

        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {api_key}"})

        _job_processing.clear()
        _drain_queue(_job_queue)
        _drain_queue(_log_queue)

        try:
            _app.unregisterCustomEvent(_JOB_QUEUE_EVENT_ID)
        except Exception:
            pass

        _custom_event = _app.registerCustomEvent(_JOB_QUEUE_EVENT_ID)
        handler = _JobQueueEventHandler(session)
        _custom_event.add(handler)
        _handlers.append(handler)

        temp = setupTemp.setupTempDir()
        _stop_event = threading.Event()
        _server_thread = threading.Thread(
            target=handleServer,
            args=(temp, _stop_event),
            daemon=True,
        )
        _server_thread.start()

    except:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
            fusion_app.log("Failed:\n{}".format(traceback.format_exc()))


def stop(context):
    try:
        global _stop_event, _server_thread, _custom_event, _handlers, session
        if _stop_event:
            _stop_event.set()
        if _server_thread and _server_thread.is_alive():
            _server_thread.join(timeout=2)
        try:
            if _app:
                _app.unregisterCustomEvent(_JOB_QUEUE_EVENT_ID)
        except Exception:
            pass
        _custom_event = None
        _handlers = []
        if session:
            try:
                session.close()
            except Exception:
                pass
        session = None
        _job_processing.clear()
        _drain_queue(_job_queue)
        _drain_queue(_log_queue)
        _stop_event = None
        _server_thread = None

    except:
        if _ui:
            _ui.messageBox("Failed stop:\n{}".format(traceback.format_exc()))
            _app.log("Failed:\n{}".format(traceback.format_exc()))
