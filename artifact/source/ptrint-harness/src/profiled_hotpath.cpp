#include <cstdint>

extern "C" int collatz(int x) {
    while (x > 1) {
        if ((x & 1) == 0)
            x /= 2;
        else
            x = 3 * x + 1;
    }
    return x;
}
