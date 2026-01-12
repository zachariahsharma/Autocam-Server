# Application Global Variables
# This module serves as a way to share variables across different
# modules (global variables).
import os
import re

_ADDIN_DIR = os.path.dirname(os.path.realpath(__file__))
_ENV_PATH = os.path.join(_ADDIN_DIR, ".env")

def _read_env_value(key: str) -> str:
    """Read a value from the .env file."""
    pattern = re.compile(rf"^\s*{key}\s*=\s*(?P<value>.*)\s*$")
    try:
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                match = pattern.match(line)
                if not match:
                    continue
                value = match.group("value").strip()
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                return value.strip()
    except FileNotFoundError:
        pass
    return ""

BASE_URL = _read_env_value("BASE_URL") or "http://localhost:3000"

with open(os.path.join(os.path.dirname(__file__), ".overridepath")) as f:
    OVERRIDE_PATH = f.read().strip()

TEMP_PATH = os.path.join(os.path.dirname(__file__), "temp")
INITIAL_PATH = os.path.join(TEMP_PATH, "initial")
FINAL_PATH = os.path.join(TEMP_PATH, "final")
TOOLS_PATH = os.path.join(TEMP_PATH, "tools")

# Flag that indicates to run in Debug mode or not. When running in Debug mode
# more information is written to the Text Command window. Generally, it's useful
# to set this to True while developing an add-in and set it to False when you
# are ready to distribute it.
DEBUG = True

# Gets the name of the add-in from the name of the folder the py file is in.
# This is used when defining unique internal names for various UI elements
# that need a unique name. It's also recommended to use a company name as
# part of the ID to better ensure the ID is unique.
ADDIN_NAME = os.path.basename(os.path.dirname(__file__))
COMPANY_NAME = "ACME"
# Palettes
sample_palette_id = f"{COMPANY_NAME}_{ADDIN_NAME}_palette_id"
