#include <stdint.h>

// Simple memory-walking kernel that triggers AddressSanitizer shadow checks
// when the baseline build enables -fsanitize=address. CHERI's capability ABI
// cannot safely reconstitute pointers from integers, so the CHERI build skips
// ASan instrumentation and leaves this function untouched.
int asan_shadow_sum(int32_t *buf, int length) {
    int32_t acc = 0;
    for (int i = 0; i < length; ++i)
        acc += buf[i];
    return acc;
}
