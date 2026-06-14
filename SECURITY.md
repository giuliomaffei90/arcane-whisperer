# Security Policy

Arcane Whisperer is a local macOS desktop app. It does not expose a web server, does not authenticate users, and does not store account credentials. The OWASP Top 10 still helps guide hardening work, especially around configuration, supply chain, data integrity, logging, and exceptional conditions.

## Supported Build

Security fixes target the source on `main` and the latest GitHub Release build.

## Reporting a Vulnerability

Please open a private security advisory on GitHub if available, or contact the maintainers privately before publishing details.

## OWASP-Oriented Controls

- Broken Access Control: no remote API or multi-user authorization boundary is exposed.
- Security Misconfiguration: the app declares macOS microphone and speech recognition privacy descriptions, runs as a regular Dock app, and builds from a documented script.
- Software Supply Chain Failures: `requirements.lock.txt` pins the build environment used for the packaged app; compiled `.app` and `.zip` artifacts are distributed as Release assets instead of being committed.
- Cryptographic Failures: the app does not manage passwords, sessions, payment data, or encrypted user data. Release notarization is still recommended before wide distribution.
- Injection: spell data is parsed as JSON only; text is displayed as text in native controls, not executed. The loader bounds and sanitizes untrusted JSON fields.
- Insecure Design: microphone processing is local by default through Whisper, and the overlay can be closed from the app menu or status item.
- Authentication Failures: not applicable; the app has no login or account model.
- Software or Data Integrity Failures: bundled spell data is included at build time; untrusted replacement JSON is size-limited, type-checked, and sanitized.
- Security Logging & Alerting Failures: startup and operational events are logged to `~/Library/Logs/Arcane Whisperer/arcane_whisperer.log` with user-only permissions. Raw transcriptions are printed only in explicit debug mode and are not persisted to that log.
- Mishandling of Exceptional Conditions: invalid JSON, oversized spell files, missing models, unavailable speech locales, and audio backend failures produce controlled errors instead of uncaught crashes where practical.

## Distribution Notes

- Share `Arcane Whisperer.zip` from GitHub Releases, not from a Git commit.
- The current local build is ad-hoc signed. For broader distribution, use an Apple Developer ID certificate and notarize the app.
- Review third-party dependency updates before refreshing `requirements.lock.txt`.
