#include <cstdint>

using Fn = int(*)(int);

namespace {

static int inc(int v) { return v + 1; }
static int dec(int v) { return v - 1; }

alignas(16) static const Fn dispatch_table[] = { inc, dec };

} // namespace

extern "C" int dispatch(int idx, int value) {
    if (idx < 0 || idx >= 2)
        return -999;
    Fn target = dispatch_table[idx];
    return target(value);
}
