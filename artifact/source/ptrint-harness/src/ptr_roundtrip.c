#include <stdint.h>

extern int *bump_pointer(int *ptr, int elems) {
    uintptr_t base = (uintptr_t)ptr;
    uintptr_t advanced = base + (uintptr_t)(elems * (int)sizeof(int));
    return (int *)advanced;
}
