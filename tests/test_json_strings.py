import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class JsonStringsTest(unittest.TestCase):
    def test_serialization_and_buffer_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "json_strings"
            subprocess.run(["c++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I", str(root / "src"),
                            str(root / "tests/json_strings.cpp"), "-o", str(binary)], check=True)
            output = subprocess.check_output([str(binary)], text=True)
        decoder = json.JSONDecoder()
        objects = []
        while output.strip():
            value, length = decoder.raw_decode(output.lstrip())
            objects.append(value)
            output = output.lstrip()[length:]
        controls = "".join(chr(i) for i in range(1, 32))
        self.assertEqual(objects[0], {"ordinary": 'garage "door" \\ UTF-8: é', "controls": controls})
        for value in objects[1:]:
            self.assertEqual(value["first"], "ok")
            if "controls" in value:
                self.assertEqual(value["controls"], controls)


if __name__ == "__main__":
    unittest.main()
