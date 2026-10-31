# WebServer upload allocation guard

Arduino ESP32 3.3.12 allocates `HTTPUpload` before accessing its fields. The
project-local override uses `new (std::nothrow)` and calls the existing
`_parseFormUploadAborted()` cleanup when allocation fails. That helper tolerates
a null upload object, clears collected multipart arguments, and returns false.
No upload callback receives a null object.

`pre:scripts/stage_webserver.py` checks the framework package version and all
73 WebServer library file hashes against `scripts/webserver-3.3.12.sha256.json`.
It stages a copy in `.pio/patched-libraries/RatgdoWebServer`. The only source
change is the allocation guard in `src/Parsing.cpp`. An added `library.json`
names the copy `RatgdoWebServer`, allowing `lib_ignore = WebServer` to exclude
the original while the dependency finder selects the copy through
`lib_extra_dirs`. The global framework package is never written.

Every build verifies the original inputs and staged bytes. An unchanged staged
copy is reused; a changed staged copy is rebuilt. A changed framework version
or library file stops the build so an SDK update cannot silently bypass the
guard. Updating these pins requires reviewing the new SDK source and checking
whether the override is still needed.

Run `python3 tests/test_webserver_override.py` for offline hash, cache, corruption,
and allocation checks. The allocation test compiles the exact guard fragment
with a host allocator stub and checks successful and null allocation. Firmware
build output must show `RatgdoWebServer` in the dependency graph and compile
its staged `Parsing.cpp`; these host tests alone do not verify library selection.
