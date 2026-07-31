/* Capability-walk form of the motivating example (paper Section 2).
 *
 * This is the provenance-preserving rewrite CapOpt's capability-walk
 * optimization targets: `end` is computed once and src/dst advance via
 * capability-offset increments (CIncOffset on CHERI), eliminating the
 * per-iteration address reconstruction of the naive purecap lowering
 * (paper Listing 3).  Unrolling is disabled so the emitted code keeps
 * the tight rolled-loop shape of the paper's optimized listing.
 */

void elementwise_copy(int argc, char **argv) {
    int a[64], b[64];
    int *p = a;
    int * const end_a = a + 64;
    int v = 0;
#pragma clang loop unroll(disable) vectorize(disable)
    while (p != end_a) {
        *p++ = v++;
    }
    const int *s = a;
    int *d = b;
#pragma clang loop unroll(disable) vectorize(disable)
    while (s != end_a) {
        *d++ = *s++;
    }
    volatile int sink = b[0];
    (void)sink;
    (void)argc;
    (void)argv;
    return;
}

#ifdef MOTIVATING_MAIN
int main(int argc, char **argv) {
    for (int r = 0; r < 100000; ++r) {
        elementwise_copy(argc, argv);
    }
    return 0;
}
#endif
