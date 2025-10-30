#!/usr/bin/env python3
#
# Apply project-specific tweaks to PlatformIO dependencies.
#
import os
import subprocess

OLD_TOUCH_SNIPPET = """#if ESP_IDF_VERSION_MAJOR >= 5\n#include <driver/touch_pad.h>\nextern \"C\" inline void touchSetCycles(uint16_t measureCycles, uint16_t sleepCycles)\n{\n#if defined(touch_pad_set_measurement_clock_cycles)\n  touch_pad_set_measurement_clock_cycles(measureCycles);\n  touch_pad_set_measurement_interval(sleepCycles);\n#else\n  touch_pad_set_meas_time(sleepCycles, measureCycles);\n#endif\n}\n#endif\n\n"""

TOUCH_FUNC_SNIPPET = """#if ESP_IDF_VERSION_MAJOR >= 5 && !defined(TOUCHSETCYCLES_COMPAT_DEFINED)\n#define TOUCHSETCYCLES_COMPAT_DEFINED 1\n#include <driver/touch_pad.h>\nextern \"C\" inline void touchSetCycles(uint16_t measureCycles, uint16_t sleepCycles)\n{\n#if defined(touch_pad_set_measurement_clock_cycles)\n  touch_pad_set_measurement_clock_cycles(measureCycles);\n  touch_pad_set_measurement_interval(sleepCycles);\n#else\n  touch_pad_set_meas_time(sleepCycles, measureCycles);\n#endif\n}\n#endif\n\n"""


def apply_webserver_patch(home_dir: str) -> None:
    target = os.path.join(
        home_dir,
        ".platformio",
        "packages",
        "framework-arduinoespressif32",
        "libraries",
        "WebServer",
        "src",
        "WebServer.cpp",
    )
    if os.path.exists(target):
        subprocess.call(["patch", "-N", target, "url_not_found_log.patch"])


def ensure_homespan_compat() -> None:
    env_root = os.path.join(".pio", "libdeps", "ratgdo_esp32dev", "HomeSpan", "src")
    utils_path = os.path.join(env_root, "Utils.h")
    homespan_h_path = os.path.join(env_root, "HomeSpan.h")
    homespan_cpp_path = os.path.join(env_root, "HomeSpan.cpp")

    if os.path.exists(utils_path):
        with open(utils_path, "r", encoding="utf-8") as f:
            content = f.read()
        if OLD_TOUCH_SNIPPET in content:
            content = content.replace(OLD_TOUCH_SNIPPET, "")
        if "#include <esp_idf_version.h>" not in content:
            content = content.replace(
                "#include <Arduino.h>",
                "#include <Arduino.h>\n#include <esp_idf_version.h>",
                1,
            )
        if "TOUCHSETCYCLES_COMPAT_DEFINED" not in content and "#include \"PSRAM.h\"" in content:
            content = content.replace("#include \"PSRAM.h\"", TOUCH_FUNC_SNIPPET + "#include \"PSRAM.h\"", 1)
        with open(utils_path, "w", encoding="utf-8") as f:
            f.write(content)

    if os.path.exists(homespan_h_path):
        with open(homespan_h_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "dataSentCompat" not in content:
            needle = "  static void dataSent(const uint8_t *mac, esp_now_send_status_t status) {\n    xQueueOverwrite( statusQueue, &status );\n  }\n"
            if needle in content:
                content = content.replace(
                    needle,
                    needle
                    + """#if ESP_IDF_VERSION_MAJOR >= 5\n  static void dataSentCompat(const esp_now_send_info_t *info, esp_now_send_status_t status) {\n    dataSent(info ? info->des_addr : nullptr, status);\n  }\n#endif\n""",
                    1,
                )
                with open(homespan_h_path, "w", encoding="utf-8") as f:
                    f.write(content)

    if os.path.exists(homespan_cpp_path):
        with open(homespan_cpp_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "esp_now_register_send_cb(dataSentCompat)" not in content and "esp_now_register_send_cb(dataSent)" in content:
            needle = "  esp_now_register_send_cb(dataSent);       // set callback for sending data\n"
            replacement = """#if ESP_IDF_VERSION_MAJOR >= 5\n  esp_now_register_send_cb(dataSentCompat); // set callback for sending data\n#else\n  esp_now_register_send_cb(dataSent);       // set callback for sending data\n#endif\n"""
            content = content.replace(needle, replacement, 1)
            with open(homespan_cpp_path, "w", encoding="utf-8") as f:
                f.write(content)


def main() -> None:
    home_dir = os.environ.get("HOME") or os.environ.get("USERPROFILE") or ""
    if home_dir:
        apply_webserver_patch(home_dir)
    ensure_homespan_compat()


if __name__ == "__main__":
    main()
