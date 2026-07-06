# AutoCAM V2 Fusion Add-In

AutoCAM V2 is an Autodesk Fusion 360 add-in that connects Fusion CAM workflows to AutoCAM WebUI.

It polls the WebUI job queue, imports plate and tube jobs, creates CAM setups, applies templates, and reports completion status back to the server.

## Requirements

- Autodesk Fusion 360
- Python runtime provided by Fusion 360
- Network access to an AutoCAM WebUI deployment
- AutoCAM API key with runner permissions

## Installation

Place this folder in Fusion 360's add-in directory:

```text
~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/
```

Enable the add-in from Fusion 360's Scripts and Add-Ins dialog.

## Configuration

Copy `.env.example` to `.env` and provide deployment-specific values:

```bash
cp .env.example .env
```

`API_KEY` is stored locally in `.env`. The add-in can also prompt for the key on startup and write it to `.env`.

## Development Notes

- `test.py` is the Fusion add-in entry point.
- `commands/` contains UI commands.
- `workflows/` contains CAM job processing workflows.
- `templates/` contains Fusion CAM template files.

## License

MIT
