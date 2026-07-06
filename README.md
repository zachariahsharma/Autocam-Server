<div align="center">

<img src="AddInIcon.svg" alt="AutoCAM V2" width="128" />

# AutoCAM V2 · Fusion 360 Add-in

**The runner that turns AutoCAM job queues into real Fusion 360 CAM setups and G-code.**

🌐 Pairs with [cam.valor6800.com](https://cam.valor6800.com) · 🔗 [AutoCAM WebUI repo](https://github.com/zachariahsharma/AutoCAM)

<br />

[![License: MIT](https://img.shields.io/github/license/zachariahsharma/Autocam-Server?color=E6DD5E&labelColor=0d1117)](LICENSE)
[![Stars](https://img.shields.io/github/stars/zachariahsharma/Autocam-Server?color=E6DD5E&labelColor=0d1117&logo=github)](https://github.com/zachariahsharma/Autocam-Server/stargazers)
[![Forks](https://img.shields.io/github/forks/zachariahsharma/Autocam-Server?color=E6DD5E&labelColor=0d1117&logo=github)](https://github.com/zachariahsharma/Autocam-Server/network/members)
[![Issues](https://img.shields.io/github/issues/zachariahsharma/Autocam-Server?color=E6DD5E&labelColor=0d1117)](https://github.com/zachariahsharma/Autocam-Server/issues)
[![Last Commit](https://img.shields.io/github/last-commit/zachariahsharma/Autocam-Server?color=E6DD5E&labelColor=0d1117)](https://github.com/zachariahsharma/Autocam-Server/commits)

<br />

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Autodesk Fusion](https://img.shields.io/badge/Autodesk_Fusion_360-F16529?style=for-the-badge&logo=autodesk&logoColor=white)
![Requests](https://img.shields.io/badge/Requests-2C2C2C?style=for-the-badge&logo=python&logoColor=white)

<br />

[**How It Works**](#-how-it-works) · [**Installation**](#-installation) · [**Configuration**](#-configuration) · [**Project Structure**](#-project-structure) · [**Development**](#-development)

</div>

---

## Overview

**AutoCAM V2** is an Autodesk Fusion 360 add-in that acts as the CAM **runner** for the [AutoCAM WebUI](https://github.com/zachariahsharma/AutoCAM) platform. It polls the WebUI job queue, pulls down plate and tube jobs, builds Fusion CAM setups from templates, generates toolpaths, exports G-code, and reports completion back to the server.

Runners authenticate with a scoped **AutoCAM API key**, so a shop can point one or more Fusion machines at a single WebUI deployment and let jobs flow automatically from the browser to the machine.

## ⚙️ How It Works

```
AutoCAM WebUI  →  Job Polling  →  Job Queue  →  Router
                                                 ├─→ plate:cam       →  camPlate
                                                 ├─→ box_tube         →  camTube
                                                 └─→ plate:arrange    →  importPlate
```

The add-in runs a background polling thread that claims jobs from the queue, dispatches each `kind` to its workflow, and streams status/logs back to the WebUI. CAD files and tooling are downloaded per job, toolpaths are generated in Fusion, and the resulting G-code + screenshots are uploaded as the job result.

## ✨ Features

- 🔁 **Automatic job polling** — background thread claims queued jobs and dispatches by kind
- 🪧 **Plate CAM** — downloads STEP files, applies tool libraries, generates toolpaths and G-code
- 🧱 **Box-tube CAM** — the same flow adapted for tubular stock
- 🧩 **2D nesting** — auto-arranges parts onto plates with envelope screenshots
- 🧭 **Auto-orientation** — orients parts largest-face-up before setup
- 🗂️ **Template-driven setups** — reusable Fusion CAM templates for plates and box tubes
- 📡 **Status reporting** — completion, logs, and artifacts pushed back to the server

## 📋 Requirements

- **Autodesk Fusion 360** (macOS or Windows)
- Python runtime provided by Fusion 360 (the `adsk` modules only exist inside Fusion)
- Network access to an **AutoCAM WebUI** deployment
- An **AutoCAM API key** with runner permissions

> **Before you start:** stand up the [AutoCAM WebUI](https://github.com/zachariahsharma/AutoCAM#-getting-started) (or use the hosted app at [cam.valor6800.com](https://cam.valor6800.com)), create a team, and generate a **runner API key** with `jobs` scopes. You'll paste that key and the WebUI's `BASE_URL` into this add-in's `.env` below.

## 🚀 Installation

Place this folder in Fusion 360's add-in directory:

```text
# macOS
~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/

# Windows
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\
```

Then open Fusion 360 → **Utilities → Scripts and Add-Ins → Add-Ins**, select **test**, and click **Run** (enable *Run on Startup* to launch it automatically).

## 🔧 Configuration

Copy the example environment file and fill in your deployment values:

```bash
cp .env.example .env
```

| Variable | Purpose | Default |
| --- | --- | --- |
| `API_KEY` | AutoCAM runner API key | _(required)_ |
| `BASE_URL` | AutoCAM WebUI base URL | `http://localhost:3000` |

`API_KEY` is stored locally in `.env` (git-ignored). The add-in can also prompt for the key on startup and write it to `.env` for you.

## 🗂 Project Structure

| Path | Purpose |
| --- | --- |
| `test.py` | Add-in entry point — API auth, job polling, event dispatch |
| `config.py` | Global settings (paths, base URL, debug mode) |
| `commands/` | Fusion 360 UI commands / utility operations |
| `workflows/` | CAM job-processing pipelines |
| `templates/` | Fusion CAM template files (`Plates`, `boxtubes`) |
| `lib/` | Shared Fusion add-in utilities |

### Workflows (`workflows/`)

| Module | Role |
| --- | --- |
| `camPlate.py` | Plate CAM — STEP import, tool libraries, toolpaths, G-code |
| `camTube.py` | Box-tube CAM pipeline |
| `importPlate.py` | Part nesting / arrangement with screenshots |
| `job_status.py` | Reports job status back to the server |
| `setupTemp.py` | Setup + temp-file handling |
| `templateTools.py` | Applies tool libraries from templates |

### Commands (`commands/`)

| Module | Role |
| --- | --- |
| `AutoArrange.py` | 2D nesting solver |
| `SetupGenerator.py` | CAM setup creation |
| `NewNCProgram.py` | G-code export |
| `Orientation.py` | Auto-orient parts (largest face up) |
| `HandleTube.py` | Box-tube handling |
| `MultiImport.py` | Multi-part import |
| `DeleteToolpaths.py` | Clear existing toolpaths |
| `ScreenshotEnvelope.py` | Capture envelope screenshots |

## 🛠 Development

`adsk` modules are only available inside Fusion 360's runtime, so Fusion-specific behavior must be tested inside Fusion. Before opening a PR, validate Python syntax:

```bash
python3 -m compileall -q .
```

Toggle verbose logging to the Fusion **Text Command** window via `DEBUG = True` in `config.py`.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full pull-request checklist.

## 🔗 Related

- **[AutoCAM WebUI](https://github.com/zachariahsharma/AutoCAM)** — the multi-tenant web platform this add-in runs jobs for
- **Live app:** [cam.valor6800.com](https://cam.valor6800.com)

## 🛡️ Security

Please review the **[Security Policy](SECURITY.md)** and report vulnerabilities responsibly rather than opening a public issue.

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

<div align="center">
<br />
<sub>Part of the <b>AutoCAM</b> platform · Automated CAM toolpaths for manufacturing</sub>
</div>
