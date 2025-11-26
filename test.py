import adsk.core, adsk.fusion, adsk.cam, traceback
import threading, sys, time
from .workflows import importPlate as importPlate
from .workflows import camPlate as camPlate
from .workflows import camTube as camTube
import queue, json
from .config import *

sys.path.append(OVERRIDE_PATH)
from flask import Flask, request
from werkzeug.serving import make_server  # <-- add this


_app = adsk.core.Application.cast(None)
_ui = adsk.core.UserInterface.cast(None)

_jobs = queue.Queue()
CUSTOM_EVENT_ID = "test.webhook.import"

_handler = None

_flask_app = Flask(__name__)

# --- HTTP server + thread holders ---
_http_server = None  # will hold make_server(...)
_flask_thread = None  # thread that calls serve_forever()


# --- Custom event handler and dispatcher ---
class WebhookHandler(adsk.core.CustomEventHandler):
    def notify(self, args: adsk.core.CustomEventArgs):
        try:
            while not _jobs.empty():
                job = _jobs.get_nowait()
                task = (job or {}).get("__task", "importPlate")
                if task == "autocam":
                    camPlate.start(job)
                elif task == "boxtube":
                    camTube.start(job)
                else:
                    importPlate.start(job)
        except Exception:
            if _ui:
                _ui.messageBox("Job error:\n{}".format(traceback.format_exc()))


@_flask_app.route("/breakdown", methods=["POST"])
def home():
    fusion_app = adsk.core.Application.get()
    fusion_app.log("Flask endpoint /breakdown was called")
    body = request.get_data(cache=True, as_text=True)
    json_payload = request.get_json(silent=True)

    fusion_app.log(f"Method: {request.method}")
    fusion_app.log(f"Path: {request.path}")
    fusion_app.log(f"Headers: {dict(request.headers)}")
    fusion_app.log(f"Body: {body!r}")
    fusion_app.log(f"JSON: {type(json_payload)}")

    job = json_payload or {}
    job["__task"] = "importPlate"
    _jobs.put(job)
    fusion_app.fireCustomEvent(CUSTOM_EVENT_ID, json.dumps({"path": request.path}))
    return "OK", 200


@_flask_app.route("/autocam", methods=["POST"])
def autocam():
    fusion_app = adsk.core.Application.get()
    fusion_app.log("Flask endpoint /autocam was called")
    body = request.get_data(cache=True, as_text=True)
    json_payload = request.get_json(silent=True)

    fusion_app.log(f"Method: {request.method}")
    fusion_app.log(f"Path: {request.path}")
    fusion_app.log(f"Headers: {dict(request.headers)}")
    fusion_app.log(f"Body: {body!r}")
    fusion_app.log(f"JSON: {type(json_payload)}")

    job = json_payload or {}
    job["__task"] = "autocam"
    _jobs.put(job)
    fusion_app.fireCustomEvent(CUSTOM_EVENT_ID, json.dumps({"path": request.path}))
    return "OK", 200


@_flask_app.route("/boxtube", methods=["POST"])
def boxtube():
    fusion_app = adsk.core.Application.get()
    fusion_app.log("Flask endpoint /boxtube was called")
    body = request.get_data(cache=True, as_text=True)
    json_payload = request.get_json(silent=True)

    fusion_app.log(f"Method: {request.method}")
    fusion_app.log(f"Path: {request.path}")
    fusion_app.log(f"Headers: {dict(request.headers)}")
    fusion_app.log(f"Body: {body!r}")
    fusion_app.log(f"JSON: {type(json_payload)}")

    job = json_payload or {}
    job["__task"] = "boxtube"
    _jobs.put(job)
    fusion_app.fireCustomEvent(CUSTOM_EVENT_ID, json.dumps({"path": request.path}))
    return "OK", 200


def _start_http_server():
    """
    Start a controllable WSGI server so we can shut it down in stop().
    """
    global _http_server
    # Bind to localhost; fixed port
    _http_server = make_server("127.0.0.1", 51234, _flask_app)

    # (Optional) push an app context if your routes use `current_app`, etc.
    # ctx = _flask_app.app_context()
    # ctx.push()

    # This blocks until shutdown() is called:
    _http_server.serve_forever()


def run(context):
    ui = None
    try:
        fusion_app = adsk.core.Application.get()
        ui = fusion_app.userInterface
        global _app, _ui, _handler, _flask_thread
        _app, _ui = fusion_app, ui

        # Register custom event & attach handler (Fusion API pattern)
        # Note: registerCustomEvent returns None; add the handler via the event object:
        if _handler is None:
            _handler = WebhookHandler()
            fusion_app.registerCustomEvent(CUSTOM_EVENT_ID).add(_handler)
            # Attach the handler to the named custom event:

        ui.messageBox("Starting Flask…")

        if _flask_thread is None or not _flask_thread.is_alive():
            _flask_thread = threading.Thread(target=_start_http_server, daemon=True)
            _flask_thread.start()

        time.sleep(0.4)  # let the server spin up
        ui.messageBox("Flask is running on http://127.0.0.1:51234")

    except:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))


def stop(context):
    """
    Clean up: remove the event handler, unregister the custom event,
    and shutdown the Flask WSGI server thread cleanly.
    """
    try:
        # 1) Detach handler and unregister the event (ignore failures)
        if _app:
            try:
                if _handler:
                    _app.customEvent(CUSTOM_EVENT_ID).remove(_handler)
            except:
                pass
            try:
                _app.unregisterCustomEvent(CUSTOM_EVENT_ID)
            except:
                pass

        # 2) Shutdown HTTP server and join the thread
        global _http_server, _flask_thread
        if _http_server is not None:
            try:
                _http_server.shutdown()  # tells serve_forever() to exit
            except Exception:
                if _ui:
                    _ui.messageBox(
                        "HTTP server shutdown error:\n{}".format(traceback.format_exc())
                    )
            finally:
                _http_server = None

        if _flask_thread is not None and _flask_thread.is_alive():
            # Give it a moment to unwind
            _flask_thread.join(timeout=2.0)
            _flask_thread = None

    except:
        if _ui:
            _ui.messageBox("Failed stop:\n{}".format(traceback.format_exc()))
