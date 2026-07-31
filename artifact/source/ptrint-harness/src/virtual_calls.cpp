#include <cstdint>

// Simple interface with many methods
struct ICompute {
    virtual int32_t compute1(int32_t x) = 0;
    virtual int32_t compute2(int32_t x) = 0;
    virtual int32_t compute3(int32_t x) = 0;
    virtual int32_t compute4(int32_t x) = 0;
    virtual int32_t compute5(int32_t x) = 0;
    virtual int32_t compute6(int32_t x) = 0;
    virtual int32_t compute7(int32_t x) = 0;
    virtual int32_t compute8(int32_t x) = 0;
    virtual int32_t compute9(int32_t x) = 0;
    virtual int32_t compute10(int32_t x) = 0;
    virtual ~ICompute() = default;
};

// Single implementation (WholeProgramDevirt should devirtualize everything)
struct SimpleCompute final : ICompute {
    int32_t compute1(int32_t x) override { return x + 1; }
    int32_t compute2(int32_t x) override { return x + 2; }
    int32_t compute3(int32_t x) override { return x + 3; }
    int32_t compute4(int32_t x) override { return x + 4; }
    int32_t compute5(int32_t x) override { return x + 5; }
    int32_t compute6(int32_t x) override { return x + 6; }
    int32_t compute7(int32_t x) override { return x + 7; }
    int32_t compute8(int32_t x) override { return x + 8; }
    int32_t compute9(int32_t x) override { return x + 9; }
    int32_t compute10(int32_t x) override { return x + 10; }
};

static SimpleCompute g_compute;

static ICompute* get_compute() {
    return &g_compute;
}

// Many call sites - each will be devirtualized and inlined in baseline but not in CHERI
static int32_t process1(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += c->compute1(arr[i]);
        sum += c->compute2(arr[i]);
        sum += c->compute3(arr[i]);
        sum += c->compute4(arr[i]);
        sum += c->compute5(arr[i]);
    }
    return sum;
}

static int32_t process2(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += c->compute6(arr[i]);
        sum += c->compute7(arr[i]);
        sum += c->compute8(arr[i]);
        sum += c->compute9(arr[i]);
        sum += c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process3(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum ^= c->compute1(arr[i]);
        sum ^= c->compute2(arr[i]);
        sum ^= c->compute3(arr[i]);
        sum ^= c->compute4(arr[i]);
        sum ^= c->compute5(arr[i]);
    }
    return sum;
}

static int32_t process4(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum ^= c->compute6(arr[i]);
        sum ^= c->compute7(arr[i]);
        sum ^= c->compute8(arr[i]);
        sum ^= c->compute9(arr[i]);
        sum ^= c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process5(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum *= c->compute1(arr[i]);
        sum *= c->compute2(arr[i]);
        sum *= c->compute3(arr[i]);
        sum *= c->compute4(arr[i]);
        sum *= c->compute5(arr[i]);
    }
    return sum;
}

static int32_t process6(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum *= c->compute6(arr[i]);
        sum *= c->compute7(arr[i]);
        sum *= c->compute8(arr[i]);
        sum *= c->compute9(arr[i]);
        sum *= c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process7(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum |= c->compute1(arr[i]);
        sum |= c->compute2(arr[i]);
        sum |= c->compute3(arr[i]);
        sum |= c->compute4(arr[i]);
        sum |= c->compute5(arr[i]);
    }
    return sum;
}

static int32_t process8(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum |= c->compute6(arr[i]);
        sum |= c->compute7(arr[i]);
        sum |= c->compute8(arr[i]);
        sum |= c->compute9(arr[i]);
        sum |= c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process9(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum &= c->compute1(arr[i]);
        sum &= c->compute2(arr[i]);
        sum &= c->compute3(arr[i]);
        sum &= c->compute4(arr[i]);
        sum &= c->compute5(arr[i]);
    }
    return sum;
}

static int32_t process10(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum &= c->compute6(arr[i]);
        sum &= c->compute7(arr[i]);
        sum &= c->compute8(arr[i]);
        sum &= c->compute9(arr[i]);
        sum &= c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process11(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum -= c->compute1(arr[i]);
        sum -= c->compute2(arr[i]);
        sum -= c->compute3(arr[i]);
        sum -= c->compute4(arr[i]);
        sum -= c->compute5(arr[i]);
    }
    return sum;
}

static int32_t process12(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum -= c->compute6(arr[i]);
        sum -= c->compute7(arr[i]);
        sum -= c->compute8(arr[i]);
        sum -= c->compute9(arr[i]);
        sum -= c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process13(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += c->compute1(arr[i]) + c->compute2(arr[i]);
        sum += c->compute3(arr[i]) + c->compute4(arr[i]);
        sum += c->compute5(arr[i]) + c->compute6(arr[i]);
        sum += c->compute7(arr[i]) + c->compute8(arr[i]);
        sum += c->compute9(arr[i]) + c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process14(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum ^= c->compute1(arr[i]) ^ c->compute2(arr[i]);
        sum ^= c->compute3(arr[i]) ^ c->compute4(arr[i]);
        sum ^= c->compute5(arr[i]) ^ c->compute6(arr[i]);
        sum ^= c->compute7(arr[i]) ^ c->compute8(arr[i]);
        sum ^= c->compute9(arr[i]) ^ c->compute10(arr[i]);
    }
    return sum;
}

static int32_t process15(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += c->compute1(c->compute2(arr[i]));
        sum += c->compute3(c->compute4(arr[i]));
        sum += c->compute5(c->compute6(arr[i]));
        sum += c->compute7(c->compute8(arr[i]));
        sum += c->compute9(c->compute10(arr[i]));
    }
    return sum;
}

static int32_t process16(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        sum ^= c->compute10(c->compute9(arr[i]));
        sum ^= c->compute8(c->compute7(arr[i]));
        sum ^= c->compute6(c->compute5(arr[i]));
        sum ^= c->compute4(c->compute3(arr[i]));
        sum ^= c->compute2(c->compute1(arr[i]));
    }
    return sum;
}

static int32_t process17(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        int32_t v = arr[i];
        v = c->compute1(v);
        v = c->compute2(v);
        v = c->compute3(v);
        v = c->compute4(v);
        v = c->compute5(v);
        sum += v;
    }
    return sum;
}

static int32_t process18(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        int32_t v = arr[i];
        v = c->compute6(v);
        v = c->compute7(v);
        v = c->compute8(v);
        v = c->compute9(v);
        v = c->compute10(v);
        sum += v;
    }
    return sum;
}

static int32_t process19(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        int32_t v = arr[i];
        v = c->compute10(v);
        v = c->compute9(v);
        v = c->compute8(v);
        v = c->compute7(v);
        v = c->compute6(v);
        sum += v;
    }
    return sum;
}

static int32_t process20(int32_t* arr, int n) {
    ICompute* c = get_compute();
    int32_t sum = 0;
    for (int i = 0; i < n; ++i) {
        int32_t v = arr[i];
        v = c->compute5(v);
        v = c->compute4(v);
        v = c->compute3(v);
        v = c->compute2(v);
        v = c->compute1(v);
        sum += v;
    }
    return sum;
}

// Main entry point calling all processors
extern "C" int32_t run_virtual_dispatch(int32_t* data, int len, int mode) {
    int32_t result = 0;
    
    result += process1(data, len);
    result ^= process2(data, len);
    result += process3(data, len);
    result ^= process4(data, len);
    result += process5(data, len);
    result ^= process6(data, len);
    result += process7(data, len);
    result ^= process8(data, len);
    result += process9(data, len);
    result ^= process10(data, len);
    result += process11(data, len);
    result ^= process12(data, len);
    result += process13(data, len);
    result ^= process14(data, len);
    result += process15(data, len);
    result ^= process16(data, len);
    result += process17(data, len);
    result ^= process18(data, len);
    result += process19(data, len);
    result ^= process20(data, len);
    
    return result + mode;
}
