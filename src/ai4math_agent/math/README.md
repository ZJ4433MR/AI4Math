# Mathematical interfaces and evidence rules

The encoding convention is **bit i = 1 exactly when s[i] = −1**, with sequence
position 0 at the least significant bit. `evaluate(s)` returns a JSON-safe
record with `sequence,n,C,E,F_numerator,F_denominator,F,b,encoding,hash`.
The SHA-256 hash covers the ASCII JSON sequence with compact separators.
`F_numerator=n*n` and `F_denominator=2*E` retain an exact rational value;
`F` is a display number. Arithmetic never accumulates a dot product in int8.

`correlations(s)` is an int64 vector of length n−1;
`batch_correlations(sequences)` is a B × (n−1) int64 array.
`flip_delta(s,C,j)` and `pair_delta(s,C,i,j)` return changes to the correlation
vector, computed at the original state. `all_flip_deltas(s)` returns one row
for each flip. `energy_delta(C,dC)` returns the exact integer change in energy.
Apply a move only after scoring: `new_C=C+dC`, then change the symbols.

`exact_profile(n,max_states=None,wall_seconds=600)` visits representatives
with s[0]=+1 and computes energy by Python integer XOR/popcount. It reduces
only global inversion, which preserves energy and absolute imbalance. Every
full orbit has two members, so reported optimum counts multiply representative
counts by two. Alternating signs preserve energy but may change imbalance;
they are not used to merge classes. Interrupted profiles expose best-seen
values and never expose an exact global optimum or a certified optimum set.

`verification.reference.evaluate_reference` independently computes every
correlation using Python integer nested summation. `verify_sequence` compares
all evidence fields and checks correlation range, parity, correlation sum,
the parity energy bound, and energy modulo 4. `verify_exact_profile` compares
every stratum and its optimum count against a separate Gray-code enumeration
using Python integer updates. Its `checked_states` and `wall_seconds` must be
accounted separately from search and initial enumeration. Witness/metadata
checks alone (`exhaustive=False`) never certify complete coverage.

## Integer relaxation proof

For imbalance b, set A=(b²−n)/2 and ell_k=n−k. True correlations satisfy
sum C_k=A, |C_k|≤ell_k and C_k≡ell_k modulo 2. Relaxing realizability therefore
gives an objective L≤g_n(b). Initialization c_k=−ell_k uses sum −M where
M=n(n−1)/2. To reach A needs T=(A+M)/2 increments of size 2. This is an
integer for every feasible b; writing b=n−2r gives
A+M=(b²+n²−2n)/2, which is even because n(n−1) is even and b has n's parity.

An increment from c to c+2 costs (c+2)²−c²=4c+4. Consecutive costs on one
coordinate increase by 8. Thus the minimum-heap algorithm selects the T
smallest available marginal costs; selected increments form a prefix on
each coordinate because later costs are strictly larger than earlier costs.
Any feasible alternative also selects T such increments, so it cannot have
a smaller total marginal cost. This proves optimality of the relaxation.

The independently checked certificate is `n,b,A,c,L`. Feasibility and the
objective are checked directly. The largest selected marginal cost is
max_{c_k>−ell_k} 4(c_k−1); the smallest next marginal cost is
min_{c_k<ell_k} 4(c_k+1). Empty sides impose no restriction. The former must
not exceed the latter. Otherwise removing the last selected increment from
one coordinate and adding the next increment on another improves the
objective. Conversely, the ordered-prefix argument proves sufficiency.
An independent sum-index dynamic program checks the heap on small lengths.

Cauchy–Schwarz also gives E≥A²/(n−1); the implementation saves its exact
numerator and denominator and rounds upward in integer arithmetic. Every
odd-length correlation square is 1 modulo 4 and every even-length one is
0 modulo 4, giving E≡floor(n/2) modulo 4 and E≥floor(n/2). The combined simple
bound is adjusted upward to that congruence class.

A relaxation vector is not a binary sequence. Equality between a checked
certificate L and a checked witness energy E certifies that imbalance class.
Global certification requires equality with a valid global lower bound such
as min_b L_n(b), or completed global enumeration. None of these finite
certificates settles the asymptotic merit-factor problem.

## Controlled claim DSL

`check_small_claim(hypothesis,profiles,witnesses,certificates,max_n=22)`
supports explicit finite `domain={n_min,n_max}`, quantifier `for_all_n` or
`exists_n`, and `predicate={kind,b,threshold,comparison}`. Applicable kinds:

* `balanced_optimum_exists`: an optimum has b=n mod 2; optional b sets an
  allowed imbalance upper limit.
* `all_optima_balanced`: all optima obey that upper limit.
* `profile_monotone`: g(b)≤g(b+2) for every adjacent feasible b (comparison
  `ge` reverses the order).
* `bound_attainable`: g_n(b)=L_n(b); b=null tests all feasible classes.
* `profile_threshold`: g_n(b)≤T or ≥T; b=null selects n mod 2.

Result statuses are `finite_domain_verified`, `refuted`, `unresolved`, and
`unsupported`. The returned checks include the finite scope, actual evidence,
and counterexample/proof-of-absence basis. For `exists_n`, one true instance
suffices, while refutation requires false instances for the whole domain.
For `for_all_n`, one false instance suffices, while verification needs true
instances for the whole domain. Missing evidence stays unresolved.

Exact-set assertions require `profile['verification']` to contain a valid
independent complete-enumeration result bound to that profile's hash. The
checker never internally enumerates sequences. It may generate checked heap
bounds and reports their count. Supplied witnesses suffice to establish
g≤T or refute g≥T; unsuccessful search cannot refute g≤T or prove g≥T.
Signed-sum and other non-invariant predicates are unsupported, so the
global-inversion quotient cannot manufacture false universal conclusions.

The Littlewood identity follows by writing |P(e^{2πit})|²=n+
sum_{k=1}^{n−1} C_k(e^{2πikt}+e^{−2πikt}) and integrating its square:
orthogonality of distinct Fourier modes leaves n²+2 sum_k C_k²=n²+2E.
These are foundational tool lemmas, not claims of original research.
