# Motivation: PtrToInt/IntToPtr-Sensitive LLVM Passes

Optimizations that convert pointers to integers (and back) are routine on conventional architectures, but they destroy capability metadata on CHERI. Whenever LLVM introduces `ptrtoint`/`inttoptr`, the resulting pointer becomes untagged and is no longer dereferenceable. To keep CapOpt sound we need a focused program that activates every LLVM pass that still relies on these casts so that we can observe, test, and eventually replace them.

## How we locate the passes

Run `utils/filter_llvm_passes.py` to scan the Morello LLVM checkout for source files that create or match `IntToPtr/PtrToInt`:

```bash
python3 utils/filter_llvm_passes.py
```

The script prefers `~/cheri/build/llvm-project-build/bin/opt --print-passes` when mapping pipeline tokens, so the report already aligns with the toolchain we ship. The current hits relevant to CHERI are summarized below.

## Pass inventory (from `filter_llvm_passes.py`)

| Pass token | Source file(s) (relative to LLVM root) | Why it touches `ptrtoint`/`inttoptr` | How to trigger it in the harness |
|------------|-----------------------------------------|--------------------------------------|----------------------------------|
| `instcombine` | `llvm/lib/Transforms/InstCombine/InstCombine*.cpp` | Matches `m_PtrToInt/m_IntToPtr` to fold round-trips, sometimes materializes integer compares against pointer addresses. | Build any `.cpp` at `-O2`/`-O3`. |
| `wholeprogramdevirt` | `llvm/lib/Transforms/IPO/WholeProgramDevirt.cpp` | Devirtualization compares vtable addresses, creates jump tables, and emits pointer bitsets via integer math. | `-flto -fwhole-program-vtables -fvirtual-function-elimination`. |
| `lowertypetests` | `llvm/lib/Transforms/IPO/LowerTypeTests.cpp` | Converts `llvm.type.test` into bitset lookups by subtracting vtable base pointers (`ptrtoint`) and reconstituting them (`inttoptr`). | `-fsanitize=cfi-vcall -flto`. |
| `infer-address-spaces` | `llvm/lib/Transforms/Scalar/InferAddressSpaces.cpp` | Rehomes “generic” pointers to a concrete address space, often via integer conversions when no direct cast exists. | GPU/OpenCL build, e.g. `clang --target=amdgcn-amd-amdhsa`. |
| `instrprof` | `llvm/lib/Transforms/Instrumentation/InstrProfiling.cpp` | Computes counter addresses using biased pointer arithmetic (`ptrtoint + bias -> inttoptr`). | `-fprofile-generate` or `-fcs-profile-generate`. |
| `rel-lookup-table-converter` | `llvm/lib/Transforms/Utils/RelLookupTableConverter.cpp` | Replaces absolute pointer tables with relative offsets: `ptrtoint(base) + offset` → `inttoptr` before indirect call. | `-fPIC -mllvm -rel-lookup-table-converter`. |
| `scalar-evolution` | `llvm/lib/Transforms/Utils/ScalarEvolutionExpander.cpp` | Loop-strength reduction can materialize pointer induction variables as raw integers. | `-O2 -mllvm -enable-iv-rewrite`. |
| `simplifycfg` / `local` | `llvm/lib/Transforms/Utils/SimplifyCFG.cpp`, `llvm/lib/Transforms/Utils/Local.cpp` | Canonicalizes switch dispatches and stack promotions; emits integer comparisons against pointer constants. | Enabled by default at `-O2`. |
| Sanitizers (`asan`, `hwasan`, `msan`) | `llvm/lib/Transforms/Instrumentation/*Sanitizer*.cpp` | Shadow memory bookkeeping uses pointer base addresses as integers. | Build with `-fsanitize=address`, `-fsanitize=hwaddress`, `-fsanitize=memory`. |

Re-running the script after LLVM rebases keeps this table up to date; any newly flagged source should get a row here and a corresponding test in the harness.

## Reference harness program

Create a small multi-file program (`ptrint-harness/`) where each translation unit is crafted to trigger one of the passes above. The files are intentionally simple so we can compile them to LLVM bitcode, run individual passes with `opt`, and inspect the surviving `ptrtoint`/`inttoptr` instructions.

```
ptrint-harness/
  CMakeLists.txt (or simple Makefile)
  src/
    virtual_calls.cpp          # WholeProgramDevirt + InstCombine
    cfi_checks.cpp             # LowerTypeTests
    profiled_hotpath.cpp       # InstrProfiling
    lookup_table.cpp           # RelLookupTableConverter
    loop_iv.cpp                # ScalarEvolutionExpander
    ptr_roundtrip.cpp          # InstCombine simplification focus
    addrspace_kernel.cl        # InferAddressSpaces (GPU/OpenCL)
```

### 1. Virtual dispatch driver (WholeProgramDevirt + InstCombine)

```c++
// src/virtual_calls.cpp
#include <memory>

struct Base {
    virtual int foo(int v) { return v + 1; }
    virtual ~Base() = default;
};

struct Derived final : Base {
    int foo(int v) override { return v * 4; }
};

static Derived global_d;

Base *pick_impl(bool flag) {
    return flag ? &global_d : &global_d;
}

int run_devirt(int x) {
    Base *b = pick_impl(x & 1);
    return b->foo(x);
}
```

Build (bitcode + embedded ThinLTO summaries) so `wholeprogramdevirt` fires:

```bash
clang++ -O2 -flto -fwhole-program-vtables -fvirtual-function-elimination \
  -std=c++17 -c src/virtual_calls.cpp -emit-llvm -o build/virtual_calls.bc
~/cheri/build/llvm-project-build/bin/opt -passes="wholeprogramdevirt,instcombine" \
  build/virtual_calls.bc -o build/virtual_calls.opt.bc
```

Inspect `build/virtual_calls.opt.ll` for vtable comparisons that manifest as `ptrtoint`.

### 2. CFI type-test lowering (LowerTypeTests)

```c++
// src/cfi_checks.cpp
struct Widget {
    virtual void apply(int &x) { x += 1; }
    virtual ~Widget() = default;
};

struct Gadget final : Widget {
    void apply(int &x) override { x ^= 0x55aa55aa; }
};

extern "C" void call_widget(Widget *w, int &x) {
    w->apply(x);
}
```

Compile with CFI so `llvm.type.test` intrinsics are emitted and `LowerTypeTests` materializes bitsets:

```bash
clang++ -O2 -flto -fsanitize=cfi-vcall -fvisibility=hidden \
  -std=c++17 -c src/cfi_checks.cpp -emit-llvm -o build/cfi_checks.bc
~/cheri/.../opt -passes="lowertypetests" build/cfi_checks.bc -o build/cfi_checks.opt.bc
```

`rg "ptrtoint" build/cfi_checks.opt.ll` should show the subtraction of vtable bases.

### 3. Instrumented hot path (InstrProfiling)

```c++
// src/profiled_hotpath.cpp
#include <stdint.h>

int collatz(int x) {
    while (x > 1) {
        if ((x & 1) == 0)
            x /= 2;
        else
            x = 3 * x + 1;
    }
    return x;
}
```

Compile with PGO instrumentation:

```bash
clang++ -O2 -fprofile-generate -std=c++17 -c src/profiled_hotpath.cpp \
  -emit-llvm -o build/profiled_hotpath.bc
~/cheri/.../opt -passes="instrprof" build/profiled_hotpath.bc \
  -o build/profiled_hotpath.opt.bc
```

The pass will insert counter updates using `ptrtoint` + bias + `inttoptr`.

### 4. Relative lookup table converter

```c++
// src/lookup_table.cpp
#include <stdint.h>

using Fn = int(*)(int);

static int inc(int v) { return v + 1; }
static int dec(int v) { return v - 1; }

Fn table[] = { inc, dec };

int dispatch(int idx, int v) {
    if (idx < 0 || idx >= 2) return -999;
    return table[idx](v);
}
```

Build as PIC and ask LLVM to run the converter:

```bash
clang++ -O2 -fPIC -std=c++17 -c src/lookup_table.cpp -emit-llvm \
  -o build/lookup_table.bc
~/cheri/.../opt -passes="rel-lookup-table-converter" build/lookup_table.bc \
  -o build/lookup_table.opt.bc
```

Expect to see the table rewritten into offsets plus an `inttoptr` just before the indirect call.

### 5. Loop induction stress test (ScalarEvolutionExpander)

```c++
// src/loop_iv.cpp
#include <stdint.h>

int sum_stride(int *ptr, int n) {
    int total = 0;
    for (int i = 0; i < n; ++i) {
        total += ptr[i];
    }
    return total;
}
```

Compile with LSR enabled and dump the SCEV expansion:

```bash
clang -O2 -std=c17 -c src/loop_iv.cpp -emit-llvm -o build/loop_iv.bc
~/cheri/.../opt -passes="loop-reduce,scalar-evolution" build/loop_iv.bc \
  -o build/loop_iv.opt.bc
```

Depending on the backend, LLVM may keep a raw integer version of the pointer induction variable (`ptrtoint` → `add` → `inttoptr`).

### 6. Pointer round-trip canonicalization (InstCombine focus)

```c++
// src/ptr_roundtrip.cpp
#include <stdint.h>

int *bump_pointer(int *ptr, int elems) {
    uintptr_t base = (uintptr_t)ptr;
    uintptr_t advanced = base + (uintptr_t)(elems * sizeof(int));
    return (int *)advanced;
}
```

This artificial round-trip lets InstCombine match the `ptrtoint`/`inttoptr` pair. Run:

```bash
clang -O2 -std=c17 -c src/ptr_roundtrip.cpp -emit-llvm -o build/ptr_roundtrip.bc
~/cheri/.../opt -passes="instcombine" build/ptr_roundtrip.bc \
  -o build/ptr_roundtrip.opt.bc
```

If InstCombine cannot safely remove the conversion on CHERI, the IR will keep the raw casts, highlighting why capability-aware replacements are needed.

### 7. Address-space inference module (GPU/OpenCL)

```c
// src/addrspace_kernel.cl
__attribute__((address_space(3))) int shared_buf[64];

kernel void use_shared(global int *out) {
    int lid = get_local_id(0);
    shared_buf[lid] = lid * 2;
    out[lid] = shared_buf[lid];
}
```

Compile for an AMDGPU target so the InferAddressSpaces pass rewrites the generic pointers:

```bash
clang --target=amdgcn-amd-amdhsa -mcpu=gfx900 -x cl -O2 -emit-llvm -c \
  src/addrspace_kernel.cl -o build/addrspace_kernel.bc
~/cheri/.../opt -passes="infer-address-spaces" build/addrspace_kernel.bc \
  -o build/addrspace_kernel.opt.bc
```

The pass changes loads/stores to addrspace(3) and may temporarily re-interpret the pointer as an integer to build the specialized address.

## Workflow recap

1. **Build each translation unit to LLVM bitcode** (`.bc`) with the flags shown above so the relevant pass is eligible to run.
2. **Run the pass (or pass pipeline) explicitly** using `~/cheri/build/llvm-project-build/bin/opt -passes="..."`.
3. **Dump the optimized IR** (`opt -S`) and `rg "ptrtoint"` / `rg "inttoptr"` to confirm where the conversions originate.
4. **Capture diffs** between the baseline IR and the pass output to document the precise pattern that needs CHERI-safe replacements.
5. **Re-run `python3 utils/filter_llvm_passes.py`** whenever LLVM is updated to keep the pass inventory and harness coverage synchronized.

This harness gives us a reproducible way to observe every optimizer that still depends on pointer–integer casts. Once the behavior is captured we can either disable the pass for CHERI, teach it about capabilities, or introduce an equivalent CapOpt transformation that avoids invalid pointer fabrication.
