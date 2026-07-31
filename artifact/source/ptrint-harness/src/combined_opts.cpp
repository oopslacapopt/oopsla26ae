#include <cstdint>

// Virtual dispatch component
struct IHandler {
    virtual int32_t handle(int32_t x) = 0;
    virtual ~IHandler() = default;
};

struct Handler1 final : IHandler {
    int32_t handle(int32_t x) override { return x + 1; }
};

struct Handler2 final : IHandler {
    int32_t handle(int32_t x) override { return x * 2; }
};

struct Handler3 final : IHandler {
    int32_t handle(int32_t x) override { return x ^ 0x55; }
};

static Handler1 h1;
static Handler2 h2;
static Handler3 h3;

// Function pointer table (for rel-lookup-table-converter)
using ProcessFn = int32_t(*)(int32_t);

static int32_t process_add(int32_t x) { return x + 10; }
static int32_t process_sub(int32_t x) { return x - 10; }
static int32_t process_mul(int32_t x) { return x * 3; }
static int32_t process_div(int32_t x) { return x / 2; }
static int32_t process_xor(int32_t x) { return x ^ 0xAA; }
static int32_t process_and(int32_t x) { return x & 0xFF; }
static int32_t process_or(int32_t x) { return x | 0x100; }
static int32_t process_shl(int32_t x) { return x << 2; }

static ProcessFn function_table[] = {
    process_add, process_sub, process_mul, process_div,
    process_xor, process_and, process_or, process_shl
};

// Large switch for simplifycfg optimizations
[[gnu::noinline]]
static int32_t dispatch_by_type(int type, int32_t value) {
    switch (type) {
        case 0: return value + 1;
        case 1: return value + 2;
        case 2: return value + 3;
        case 3: return value + 4;
        case 4: return value + 5;
        case 5: return value + 6;
        case 6: return value + 7;
        case 7: return value + 8;
        case 8: return value * 2;
        case 9: return value * 3;
        case 10: return value * 4;
        case 11: return value * 5;
        case 12: return value ^ 0x11;
        case 13: return value ^ 0x22;
        case 14: return value ^ 0x33;
        case 15: return value ^ 0x44;
        case 16: return value & 0xFF;
        case 17: return value & 0xFFFF;
        case 18: return value | 0x100;
        case 19: return value | 0x200;
        case 20: return value << 1;
        case 21: return value << 2;
        case 22: return value >> 1;
        case 23: return value >> 2;
        case 24: return -value;
        case 25: return ~value;
        case 26: return value + 100;
        case 27: return value - 100;
        case 28: return value * 10;
        case 29: return value / 10;
        case 30: return value % 10;
        case 31: return value ^ value;
        default: return 0;
    }
}

// Another large switch
[[gnu::noinline]]
static int32_t classify_range(int32_t value) {
    if (value < -1000) return -10;
    if (value < -500) return -5;
    if (value < -100) return -2;
    if (value < 0) return -1;
    if (value == 0) return 0;
    if (value < 100) return 1;
    if (value < 500) return 2;
    if (value < 1000) return 5;
    return 10;
}

// Virtual dispatch loops
[[gnu::noinline]]
static int32_t process_virtual_batch(int32_t* data, int len, int selector) {
    IHandler* handlers[] = { &h1, &h2, &h3 };
    IHandler* h = handlers[selector % 3];
    
    int32_t result = 0;
    for (int i = 0; i < len; ++i) {
        result += h->handle(data[i]);
        result ^= h->handle(result);
        result += h->handle(data[i] + i);
        result ^= h->handle(result - i);
    }
    return result;
}

// Function table dispatch
[[gnu::noinline]]
static int32_t process_function_table(int32_t* data, int len) {
    int32_t result = 0;
    for (int i = 0; i < len; ++i) {
        int idx = (i * 7) % 8;
        result += function_table[idx](data[i]);
        result ^= function_table[(idx + 1) % 8](result);
        result += function_table[(idx + 2) % 8](data[i] + i);
    }
    return result;
}

// Switch-based dispatch
[[gnu::noinline]]
static int32_t process_switch_batch(int32_t* data, int len) {
    int32_t result = 0;
    for (int i = 0; i < len; ++i) {
        int type = (data[i] >> 8) & 0x1F;
        result += dispatch_by_type(type, data[i]);
        result ^= classify_range(result);
        result += dispatch_by_type((type + 1) & 0x1F, data[i] + i);
    }
    return result;
}

// Complex nested dispatch
[[gnu::noinline]]
static int32_t complex_dispatch(int32_t* data, int len, int mode) {
    int32_t result = 0;
    
    for (int i = 0; i < len; ++i) {
        int val = data[i];
        
        // Virtual dispatch
        IHandler* h = (mode & 1) ? (IHandler*)&h1 : (IHandler*)&h2;
        val = h->handle(val);
        
        // Function table
        int fidx = (val >> 4) & 7;
        val = function_table[fidx](val);
        
        // Switch
        int type = (val >> 2) & 0x1F;
        val = dispatch_by_type(type, val);
        
        // Classification
        val += classify_range(val);
        
        result ^= val;
    }
    
    return result;
}

// Main entry point
extern "C" int32_t run_combined_opts(int32_t* data, int len, int mode) {
    int32_t result = 0;
    
    result += process_virtual_batch(data, len, mode);
    result ^= process_function_table(data, len);
    result += process_switch_batch(data, len);
    result ^= complex_dispatch(data, len, mode);
    
    // Additional virtual calls
    IHandler* h = (mode & 2) ? (IHandler*)&h2 : (IHandler*)&h3;
    for (int i = 0; i < len; ++i) {
        result ^= h->handle(data[i]);
    }
    
    // Additional function table calls
    for (int i = 0; i < 8; ++i) {
        result += function_table[i](result + i);
    }
    
    // Additional switch calls
    for (int i = 0; i < 32; ++i) {
        result ^= dispatch_by_type(i, result);
    }
    
    return result;
}
