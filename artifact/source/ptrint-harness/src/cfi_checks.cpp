#include <cstdint>

struct Widget {
    virtual int mutate(int x) = 0;
    virtual ~Widget() = default;
};

struct Gadget final : Widget {
    int mutate(int x) override { return (x ^ 0x55aa55aa) + 7; }
};

struct Scrambler final : Widget {
    int mutate(int x) override { return x * 3 - 17; }
};

[[gnu::noinline]] static Widget *trusted_widget() {
    static Gadget trusted;
    return &trusted;
}

[[gnu::noinline]] static Widget *fallback_widget() {
    static Scrambler fallback;
    return &fallback;
}

extern "C" int cfi_verified_call(Widget *w, int value) {
    return w->mutate(value);
}

extern "C" int drive_cfi(int value, bool good) {
    Widget *w = good ? trusted_widget() : fallback_widget();
    return cfi_verified_call(w, value);
}
