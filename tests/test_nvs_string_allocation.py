"""Run the actual NVS read and authentication callback with allocation faults."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HARNESS = r"""
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_ERR_NVS_NOT_FOUND = 1;
constexpr int NVS_KEY_NAME_MAX_SIZE = 16;
int query_error = 0, read_error = 0, live_buffers = 0, reads = 0;
bool allocation_fails = false, object_fails = false, concat_fails = false;
int malformed = 0;
std::string stored_value = "secret";
void *tracked_malloc(size_t size) {
    if (allocation_fails) return nullptr;
    void *p = std::malloc(size);
    if (p) ++live_buffers;
    return p;
}
void tracked_free(void *p) {
    if (p) --live_buffers;
    std::free(p);
}
size_t strlcpy(char *out, const char *in, size_t capacity) {
    size_t n = std::strlen(in);
    if (capacity) { std::strncpy(out, in, capacity - 1); out[capacity - 1] = 0; }
    return n;
}
int nvs_get_str(int, const char *, char *out, size_t *length) {
    if (!out) {
        if (query_error) return query_error;
        *length = malformed == 1 ? 0 : stored_value.size() + 1;
        return ESP_OK;
    }
    ++reads;
    if (read_error) return read_error;
    std::memcpy(out, stored_value.c_str(), *length);
    if (malformed == 2) *length = 0;
    if (malformed == 3) ++*length;
    if (malformed == 4) out[*length - 1] = 'x';
    return ESP_OK;
}
class nvRamClass {
    int nvHandle = 0;
public:
    char *readAllocatedString(const char *, const char *);
};
int live_strings = 0;
struct String {
    std::string value;
    String() { ++live_strings; }
    ~String() { --live_strings; }
    static void *operator new(size_t n, const std::nothrow_t &) noexcept {
        return object_fails ? nullptr : std::malloc(n);
    }
    static void operator delete(void *p) { std::free(p); }
    // Arduino concat returns success for a non-null empty input.
    bool concat(const char *p) {
        if (!p) return false;
        if (!*p) return true;
        if (concat_fails) return false;
        value += p;
        return true;
    }
};
using HTTPAuthMethod = int;
nvRamClass instance;
nvRamClass *nvRam = &instance;
const char *nvram_ratgdo_pw = "password";
#define malloc tracked_malloc
#define free tracked_free
"""

CASES = r"""
#undef malloc
#undef free
int main() {
    auto direct = [&](const char *expected) {
        char *value = instance.readAllocatedString("password", "default");
        if (expected) { assert(value && std::strcmp(value, expected) == 0); }
        else assert(!value);
        tracked_free(value);
        assert(live_buffers == 0);
    };
    direct("secret");
    query_error = ESP_ERR_NVS_NOT_FOUND; direct("default");
    allocation_fails = true; direct(nullptr);
    query_error = ESP_OK; direct(nullptr);
    allocation_fails = false;
    query_error = 2; direct(nullptr); query_error = ESP_OK;
    read_error = 2; direct(nullptr); read_error = ESP_OK;
    for (malformed = 1; malformed <= 4; ++malformed) direct(nullptr);
    malformed = 0;
    stored_value = ""; direct(""); stored_value = "secret";
    auto authenticate = [&](const char *expected) {
        String *pw = ratgdoAuthenticate(0, String(), nullptr);
        if (expected) assert(pw && pw->value == expected);
        else assert(!pw);
        delete pw;
        assert(live_buffers == 0 && live_strings == 0);
    };
    authenticate("secret");
    query_error = ESP_ERR_NVS_NOT_FOUND; authenticate("password");
    query_error = 2; authenticate(nullptr); query_error = ESP_OK;
    read_error = 2; authenticate(nullptr); read_error = ESP_OK;
    allocation_fails = true; authenticate(nullptr); allocation_fails = false;
    object_fails = true; authenticate(nullptr); object_fails = false;
    concat_fails = true; authenticate(nullptr);
    stored_value = ""; authenticate("");
    concat_fails = false;
    assert(reads > 0);
}
"""


class NvsStringAllocationTest(unittest.TestCase):
    def test_read_and_authentication_failures(self):
        root = Path(__file__).resolve().parents[1]
        config = (root / "src/config.cpp").read_text()
        start = config.index("char *nvRamClass::readAllocatedString(")
        read = config[start:config.index("\nbool nvRamClass::write(", start)]
        web = (root / "src/web.cpp").read_text()
        start = web.index("String *ratgdoAuthenticate(")
        auth = web[start:web.index("\n#endif", start)]
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "allocation.cpp"
            binary = Path(temporary) / "allocation"
            source.write_text(HARNESS + read + auth + CASES)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-parameter", "-fsanitize=address,undefined",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
