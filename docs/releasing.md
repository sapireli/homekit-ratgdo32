# GRGDO1 releases

The next Gelidus release is `v1.4.0`. Its source includes
[`ratgdo/homekit-ratgdo32` commit `5ab633c166a367fd48303eca37bc9e086d2bfb6d`](https://github.com/ratgdo/homekit-ratgdo32/commit/5ab633c166a367fd48303eca37bc9e086d2bfb6d)
from October 18, 2026, plus the Gelidus `v1.3.1` release history. That upstream
commit includes the fixes following `v3.5.5`; upstream calls it the unreleased
`v3.5.6` development version.

`VERSION` sets the firmware version. The installer manifests describe the last
published binaries, so they stay at `v1.3.1` until the release workflow publishes
the new artifacts.

## Build and review

Install PlatformIO Core 6.2.0 with Python 3.12, then run:

```sh
git submodule update --init --recursive
python -m unittest discover -s tests -v
node --test tests/firmware-selection.test.cjs
c++ -std=c++17 -Wall -Wextra -Isrc tests/json_float.cpp -o /tmp/json-test
/tmp/json-test
pio run -e ratgdo_esp32dev
pio run -e ratgdo_esp32dev_rev1
```

The Firmware workflow runs the checks and builds both revisions for pull
requests. It uploads the firmware, bootloader, partition table, OTA initialization
image, ELF, MD5 checksum, SHA256 checksums, dependency list, and source commit.

Before publishing, test both physical board revisions: Security+ door commands,
obstruction detection, HomeKit pairing and existing accessory identities,
VL53L1X detection and vehicle states, configured DHT22 readings, settings after
reboot, and OTA with password protection enabled. Build success does not verify
those device behaviors.

Rev2 uses GPIO26/25 for I2C; Rev1 uses GPIO3/1. The default GRGDO1 builds disable
upstream status outputs because their default pins overlap Rev2 I2C. They also
disable the ratgdo32-disco laser output because GPIO23 is the GRGDO1 obstruction
input. Custom hardware can provide separate `STATUS_DOOR_GPIO`,
`STATUS_OBST_GPIO`, and `LASER_GPIO` build flags after verifying its wiring.
Wall-panel disconnect is unavailable without a door status output.
Encoder support uses the existing open/close inputs and stays off by default.
The DHT22 accessory retains ID 10; the new stop switch uses ID 12.

## Publish

1. Merge the integration PR into Gelidus `main` after review and device testing.
2. Confirm `VERSION` and the Gelidus changelog entry match the intended tag.
3. Create and push `v1.4.0` on the reviewed commit in the Gelidus repository.

The tag triggers builds of that exact commit. Publishing runs only in
`GelidusResearch/homekit-ratgdo32`, after both builds pass. It checks artifact
hashes and commit identities, requires the release commit to be in the default
branch, and rejects a tag that differs from that branch's `VERSION`. It copies
the same binaries into `docs/firmware`, updates all three installer manifests,
pushes a normal documentation commit, and publishes the GitHub release with the
Gelidus changelog entry. Branch protection must allow that documentation commit.
No force push is used.

To rebuild an existing tag, use **Run workflow**, enter the tag, and leave
**publish** unchecked. Check **publish** only to retry publication of the current
release. A repeated run can update the same release without creating a new tag.
