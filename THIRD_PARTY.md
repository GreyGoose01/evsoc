# Licences of included data

The evsoc code is under the [MIT licence](LICENSE). Some of the vehicle profiles come from other projects and keep their licence. The MIT licence does **not** apply to these folders.

| Folder | Source | Licence |
|---|---|---|
| `evsoc/profiles/generated/obdb/` | [OBDb](https://github.com/OBDb), one repository per model or make | [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `evsoc/profiles/generated/wican/` | [meatpiHQ/wican-fw](https://github.com/meatpiHQ/wican-fw), `vehicle_profiles` | [GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html) |
| `evsoc/profiles/generated/abrp/` | [iternio/ev-obd-pids](https://github.com/iternio/ev-obd-pids) | [Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0) |

The files there are converted automatically into the evsoc format (`evsoc update`), so they are modified versions of the originals. Every file names its source in the field `source`, every folder in `SOURCE.md`. Whoever redistributes these folders must follow the respective licence: attribution and the same licence for OBDb, distribution under GPL-3.0 for WiCAN.

To distribute evsoc without these conditions, leave out `evsoc/profiles/generated/`. Users then fetch the profiles themselves with `evsoc update`.

## Own profiles

The profiles in `evsoc/profiles/own/` are own work under the MIT licence. The identifiers and formulas in them are facts, compiled among others from:

- [OVMS](https://github.com/openvehicles/Open-Vehicle-Monitoring-System-3) (MIT)
- [comma.ai opendbc](https://github.com/commaai/opendbc) (MIT)
- [PSA-RE](https://github.com/prototux/PSA-RE) (Apache-2.0)
- [bmwGxx / G-Diag](https://github.com/unblonded/bmwGxx) (MIT): BMW control unit names and the HSFZ alive check

The origin of every single profile is listed in [docs/sources.md](docs/sources.md).

## Trademarks

BMW, Mini, Volkswagen, Opel, Peugeot, Tesla and all other names mentioned are trademarks of their owners. evsoc is an independent project and not affiliated with any manufacturer.
