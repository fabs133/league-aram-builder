# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in ARAM Oracle, please report it responsibly:

1. **Do NOT open a public issue** for security vulnerabilities
2. Open a GitHub issue with the `security` label and include only a brief, non-exploitable summary
3. Alternatively, contact the maintainer directly via GitHub

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We aim to acknowledge reports within 48 hours and provide a fix within 7 days for critical issues.

## Scope

The following are in scope for security reports:

- Path traversal or file access vulnerabilities in the API
- Injection vulnerabilities (command injection, XSS in the overlay)
- Authentication/authorization bypasses
- Information disclosure beyond intended scope

The following are **not** in scope:

- Issues that require physical access to the machine
- Denial of service against the local server (it's a local-only tool)
- Vulnerabilities in third-party dependencies (report those upstream)

## Anti-Cheat Compliance

ARAM Oracle is designed to comply with Riot Games' terms of service:

- We **only** read data from the officially sanctioned [Live Client Data API](https://developer.riotgames.com/docs/lol#game-client-api) on `127.0.0.1:2999`
- We do **not** inject code, modify game memory, or interact with the game process
- We do **not** bypass or interfere with Vanguard anti-cheat
- OCR screen reading is a passive observation method that does not modify the game

If you believe any part of this project could violate Riot's ToS, please report it so we can address it immediately.
