/* Motivating example from the OOPSLA'26 paper, Listing 1.
 *
 * elementwise_copy executes two tight loops over fixed-size arrays and
 * ends with an additional volatile read to avoid dead-code elimination
 * and enable potential optimizations.  Under purecap CHERI compilation
 * this lowers to the capability-heavy sequence of paper Listing 3
 * (~143 core instructions); CapOpt's capability-walk rewrite recovers
 * the provenance-preserving pointer-increment loop (paper claim: 10x
 * static instruction reduction).
 */

void elementwise_copy(int argc, char **argv) {
    int a[64], b[64];
    for (int i = 0; i < 64; ++i) a[i] = i;
    for (int i = 0; i < 64; ++i) b[i] = a[i];
    volatile int sink = b[0];
    (void)sink;
    (void)argc;
    (void)argv;
    return;
}

#ifdef MOTIVATING_MAIN
int main(int argc, char **argv) {
    /* Repeat enough for a measurable runtime on the target. */
    for (int r = 0; r < 100000; ++r) {
        elementwise_copy(argc, argv);
    }
    return 0;
}
#endif
