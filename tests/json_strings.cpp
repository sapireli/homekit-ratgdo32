#include "json.h"
#include <cassert>
#include <cstdio>
#include <cstring>

int main()
{
    const char ordinary[] = "garage \"door\" \\ UTF-8: \xc3\xa9";
    char controls[32];
    for (int i = 1; i < 32; ++i)
        controls[i - 1] = (char)i;
    controls[31] = 0;
    char full[512] = {};
    char *end = full + sizeof(full);
    char *cursor = start_json(full, end);
    cursor = add_str(cursor, end, "ordinary", ordinary);
    cursor = add_str(cursor, end, "controls", controls);
    end_json(cursor, end);
    std::puts(full); // The Python runner also checks round-trip JSON parsing.
    assert(std::strstr(full, "\\u0009"));
    assert(std::strstr(full, "\\u000a"));
    assert(std::strstr(full, "\\u001f"));

    // Sweep every capacity around a control-heavy field's encoded size.
    // Failed insertion must leave the previous complete field untouched.
    bool saw_omitted = false, saw_included = false;
    for (size_t capacity = 40; capacity <= sizeof(full); ++capacity)
    {
        unsigned char guarded[514];
        std::memset(guarded, 0xa5, sizeof(guarded));
        char *buffer = (char *)guarded + 1;
        end = buffer + capacity;
        cursor = start_json(buffer, end);
        cursor = add_str(cursor, end, "first", "ok");
        char snapshot[512];
        std::strcpy(snapshot, buffer);
        char *before = cursor;
        cursor = add_str(cursor, end, "controls", controls);
        if (cursor == before)
        {
            saw_omitted = true;
            assert(std::strcmp(buffer, snapshot) == 0);
        }
        else
        {
            saw_included = true;
            assert(std::strstr(buffer, "\\u001f\",\n"));
        }
        end_json(cursor, end);
        assert(guarded[0] == 0xa5);
        for (size_t i = capacity + 1; i < sizeof(guarded); ++i)
            assert(guarded[i] == 0xa5);
        assert(std::strlen(buffer) < capacity);
        std::puts(buffer);
    }
    assert(saw_omitted && saw_included);

    // Ordinary values now use their exact size, without a 2x overestimate.
    char tight[32] = {};
    end = tight + sizeof(tight);
    cursor = start_json(tight, end);
    char *before = cursor;
    cursor = add_str(cursor, end, "v", "123456789012345");
    assert(cursor != before);
    end_json(cursor, end);
}
