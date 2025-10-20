#!/usr/bin/env python3
#
# This script runs patch command on specified files.
#
# Copyright (c) 2023 David Kerr, https://github.com/dkerr64
#
import os
from pathlib import Path

try:
    PROJECT_DIR = Path(__file__).resolve().parent
except NameError:
    PROJECT_DIR = Path.cwd()

home_dir = os.environ.get('HOME') or os.environ.get('USERPROFILE')
webserver_path = Path(home_dir) / ".platformio" / "packages" / "framework-arduinoespressif32" / "libraries" / "WebServer" / "src" / "WebServer.cpp"

if webserver_path.exists():
    os.system(f"patch -N {webserver_path} url_not_found_log.patch || true")

homespan_src = PROJECT_DIR / ".pio" / "libdeps" / "ratgdo_esp32dev" / "HomeSpan" / "src"

utils_path = homespan_src / "Utils.h"
if utils_path.exists():
    utils_text = utils_path.read_text()
    include_snippet = "#include <esp32-hal-touch.h>\n"
    if include_snippet not in utils_text:
        sentinel = "#include <Arduino.h>\n"
        if sentinel in utils_text:
            utils_text = utils_text.replace(sentinel, sentinel + include_snippet)
            utils_path.write_text(utils_text)
    decl_snippet = "extern \"C\" void touchSetCycles(uint16_t, uint16_t);\n"
    if decl_snippet not in utils_text:
        insert_after = include_snippet
        if include_snippet in utils_text:
            utils_text = utils_text.replace(include_snippet, include_snippet + decl_snippet)
            utils_path.write_text(utils_text)

homespan_header = homespan_src / "HomeSpan.h"
if homespan_header.exists():
    header_text = homespan_header.read_text()
    version_block = (
        "#if __has_include(<esp_idf_version.h>)\n"
        "#include <esp_idf_version.h>\n"
        "#endif\n"
        "#ifndef ESP_IDF_VERSION_VAL\n"
        "#define ESP_IDF_VERSION_VAL(MAJOR, MINOR, PATCH) 0\n"
        "#endif\n"
        "#ifndef ESP_IDF_VERSION\n"
        "#define ESP_IDF_VERSION 0\n"
        "#endif\n"
    )
    if version_block not in header_text:
        sentinel = "#include <esp_now.h>\n"
        if sentinel in header_text:
            header_text = header_text.replace(sentinel, sentinel + version_block)

    legacy_block = "  static void dataSent(const uint8_t *mac, esp_now_send_status_t status) {\n    xQueueOverwrite( statusQueue, &status );\n  }"
    if legacy_block in header_text:
        replacement = (
            "#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 3, 0)\n"
            "  static void dataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {\n"
            "    (void)info;\n"
            "    xQueueOverwrite( statusQueue, &status );\n"
            "  }\n"
            "#else\n"
            "  static void dataSent(const uint8_t *mac, esp_now_send_status_t status) {\n"
            "    (void)mac;\n"
            "    xQueueOverwrite( statusQueue, &status );\n"
            "  }\n"
            "#endif"
        )
        header_text = header_text.replace(legacy_block, replacement)
    homespan_header.write_text(header_text)
