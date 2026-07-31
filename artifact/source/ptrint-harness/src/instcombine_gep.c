#include <stdint.h>

// Baseline InstCombine can fold the redundant ptrtoint/inttoptr even though
// the IR uses integer math explicitly. CHERI must keep the casts because an
// inttoptr would produce an invalid capability.
int sum_slice(int32_t *buf, int start, int count) {
    uintptr_t raw = (uintptr_t)buf;
    raw += (uintptr_t)start * sizeof(int32_t);
    int32_t *p = (int32_t *)raw;

    int32_t acc = 0;
    for (int i = 0; i < count; ++i)
        acc += p[i];
    return acc;
}
