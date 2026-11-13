# Contributing

What helps most is **data from real cars**. evsoc has almost only been tested against simulated vehicles.

## Providing test data

1. Run a test drive at the car with the values you read off the dashboard: `evsoc probe -a … --notiz soc=54`, or in the interface under "Test drive" ([docs/test-drive.md](docs/test-drive.md)).
2. Attach the report `evsoc-probe-….json` to an issue, together with model, model year and adapter.

**Before uploading:** the report contains the vehicle identification number (VIN) and serial numbers of control units. If you do not want to publish them, replace the last six characters of the VIN and the serial numbers in the file.

## Reporting bugs

Please include: evsoc version, operating system, adapter, vehicle, the exact command and its output. For connection problems the file from `--log` helps.

## Changing code

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[all,dev]"
.venv/bin/pytest && .venv/bin/ruff check .
```

- Tests run without a car. New features need a test, new vehicles an entry in `evsoc/mock.py`.
- **evsoc stays read only.** Changes that let writing, clearing or coding commands through are not accepted (`evsoc/safety.py`).
- New profiles: [docs/own-profiles.md](docs/own-profiles.md). Source and verification status belong in the profile (`source`, `verified`). After changing profiles run `evsoc models --markdown > docs/vehicles.md`.
- Code, comments and commit messages are in English. User-facing texts are written in German and translated through `evsoc/lang/en.txt`; a new message needs an entry there (`tests/test_i18n.py` checks the catalogue).

Contributions are under the [MIT licence](LICENSE). Data from other projects only with its source and a compatible licence ([THIRD_PARTY.md](THIRD_PARTY.md)).
