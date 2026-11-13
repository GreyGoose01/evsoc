# Security

## Reporting a vulnerability

Please do **not** report security issues as public issues. Use "Report a vulnerability" in the *Security* tab of this repository instead.

Of particular interest:

- Ways around the read-only guard, i.e. getting a writing, clearing or coding command to the car (`evsoc/safety.py`).
- Access to the interfaces without the key or PIN (`evsoc gui`, `evsoc run`).

## What evsoc protects and what it does not

- evsoc checks every command before sending it. Only read services are allowed; the list is in [docs/adapters.md](docs/adapters.md).
- `evsoc gui` binds to `127.0.0.1` by default and requires a per-session key. `evsoc run` protects its setup with a PIN.
- Both interfaces use plain HTTP. They belong on your own network, not on the internet.
- Whoever may publish to `<topic>/cmd` over MQTT can have the car woken. The broker controls that; evsoc only limits the frequency and the minimum voltage.
