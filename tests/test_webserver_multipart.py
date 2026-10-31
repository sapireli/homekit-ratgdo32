"""Exercise the actual installed SDK parser, including truncated multipart data."""
from pathlib import Path
import argparse
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDK_PARSER = Path.home() / ".platformio/packages/framework-arduinoespressif32/libraries/WebServer/src/Parsing.cpp"


def function(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise AssertionError("Unclosed SDK function")


def run_parser_checks(path):
    source = Path(path).read_text()
    start = source.index("enum class LineStatus")
    enum = source[start:source.index("};", start) + 2]
    declarations = ["static LineStatus readLineWithLimit(",
                    "void WebServer::_uploadWriteByte(",
                    "int WebServer::_uploadReadByte(",
                    "bool WebServer::_parseForm(",
                    "bool WebServer::_parseFormUploadAborted("]
    code = enum + "\n" + "\n".join(function(source, name) for name in declarations)
    fixture = (ROOT / "tests/webserver_multipart_test.cpp").read_text()
    fixture = fixture.replace("// SOURCE_PARSER", code)
    with tempfile.TemporaryDirectory() as directory:
        cpp, executable = Path(directory) / "parser.cpp", Path(directory) / "parser"
        cpp.write_text(fixture)
        # These two warnings already exist in the upstream SDK's GNU C++ code.
        subprocess.run(["c++", "-std=gnu++17", "-Wall", "-Wextra", "-Werror",
                        "-Wno-vla", "-Wno-sign-compare", "-fsanitize=address,undefined",
                        str(cpp), "-o", str(executable)], check=True)
        for case in ["header-stall", "field-stall", "trailer-stall", "payload-stall",
                     "valid-file", "empty-field", "multiline-field", "oversized-header",
                     "oversized-field", "unknown-lines", "empty-lines", "slow-header"]:
            subprocess.run([str(executable), case], check=True, timeout=3)


class WebServerMultipart(unittest.TestCase):
    @unittest.skipUnless(SDK_PARSER.is_file(), "SDK source is checked after the firmware build")
    def test_actual_installed_parser(self):
        run_parser_checks(SDK_PARSER)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.source:
        # CI invokes this explicitly after the build, so absent SDK source is a
        # failure rather than a skipped integration check.
        run_parser_checks(args.source)
    else:
        unittest.main()
