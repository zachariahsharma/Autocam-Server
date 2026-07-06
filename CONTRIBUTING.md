# Contributing

## Development

This repository is a Fusion 360 add-in. Validate Python syntax before opening a pull request:

```bash
python3 -m compileall -q .
```

Test Fusion-specific behavior inside Fusion 360 because the `adsk` modules are only available in Fusion's runtime.

## Pull Requests

Include a concise summary, testing performed, and any Fusion 360 version details relevant to the change.
