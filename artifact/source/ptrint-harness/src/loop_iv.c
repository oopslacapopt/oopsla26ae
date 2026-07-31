#include <stdint.h>

extern int sum_stride(int *ptr, int n) {
    int total = 0;
    for (int i = 0; i < n; ++i)
        total += ptr[i];
    return total;
}
