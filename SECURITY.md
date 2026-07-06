# Security Policy

Please report security issues privately instead of opening a public issue.

## Secret Handling

- Do not commit `.env` or real API keys.
- Rotate any API key that may have been exposed.
- The add-in stores `API_KEY` locally in `.env`; keep that file out of source control.
