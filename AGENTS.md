# Repository Guidelines

## Project Structure & Module Organization
HomeKit-ratgdo32 is a PlatformIO firmware project. Core device logic lives in `src/`, with feature modules split across files such as `homekit.cpp`, `ratgdo.cpp`, and helpers in `utilities.cpp`. Web assets that ship with the firmware live under `src/www` and are packed during build by `build_web_content.py`. Hardware-specific libraries are vendored in `lib/ratgdo` and `lib/secplus`, while user-facing documentation and release artifacts live in `docs/`. Platform configuration is defined in `platformio.ini`, and helper scripts (flashing, versioning, releases) sit at the repository root.

## Build, Test, and Development Commands
Install PlatformIO, then use either PlatformIO directly or the convenience wrapper. `pio run -e ratgdo_esp32dev` (or `./x.sh run`) compiles the firmware; add `-v` for verbose logs. `pio run -t upload -e ratgdo_esp32dev` or `./x.sh upload` flashes the connected board. Monitor serial output with `pio device monitor -e ratgdo_esp32dev` or `./x.sh monitor`. For scripted releases, `./x.sh release vX.Y.Z` tags the repo and copies built images into `docs/firmware/`.

## Coding Style & Naming Conventions
Match the existing Allman brace style with four-space indentation in C++ sources, and prefer descriptive snake_case identifiers (e.g., `vehicle_loop`, `free_heap`). Keep functions short and factor shared logic into the helpers under `utilities.*` or `lib/`. Guard logging with existing tag constants (see `log.cpp`), and avoid introducing new global state unless it is persisted in `config.*`. Python helper scripts follow PEP 8 spacing; keep shell scripts POSIX-compliant.

## Testing Guidelines
Run `pio test -e native` (or `./x.sh test`) before submitting changes; tests live in `lib/secplus/test/`. For hardware-facing changes, call out manual validation steps in your PR (e.g., garage door protocol exercised, web UI checked). Capture crash dumps via the serial monitor and attach when diagnosing failures.

## Commit & Pull Request Guidelines
Use concise, imperative commit subjects similar to the existing history (“Guard recovery counter from remote toggles”). Group related changes in single commits and document hardware impacts in the body. Pull requests should include a high-level summary, test evidence (`pio run`/`pio test` output), and links to any related issues. Attach screenshots or serial logs when UI or runtime behavior changes. Mention required provisioning steps whenever Wi-Fi or HomeKit flows are affected.
