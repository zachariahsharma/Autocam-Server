import json
from typing import Optional

import adsk.core
import sys

from ..config import BASE_URL, OVERRIDE_PATH
sys.path.append(OVERRIDE_PATH)
import requests


def _log(message: str) -> None:
    """Write a message to the Fusion log window if available."""
    try:
        app = adsk.core.Application.get()
        if app:
            app.log(message)
    except Exception:
        pass


def send_job_error(session: requests.Session, error_message: str) -> None:
    """Notify the API that the job has failed."""
    _log('Failure Occurred: ' + error_message)
    message = (error_message or "").strip() or "Unknown job failure"
    payload = json.dumps({
        "error": message[:2000],
        "excess_parts": []
    })
    try:
        session.post(
            f"{BASE_URL}/api/jobs/complete",
            files={
                "data": (
                    None,
                    payload,
                    "application/json",
                )
            },
            timeout=30,
        )
    except Exception as exc:
        _log(f"Failed to send job error: {exc}")


def ensure_completion_response(
    session: requests.Session, response: Optional[requests.Response], context: str
) -> None:
    """Send an error request when the completion response is missing or not successful."""
    if response is None:
        send_job_error(session, f"{context} (no response received)")
        return

    if response.ok:
        return

    try:
        detail = response.text.strip()
    except Exception:
        detail = ""

    message = f"{context} failed with status {response.status_code} {response.reason}"
    if detail:
        message = f"{message}: {detail}"
    send_job_error(session, message)
