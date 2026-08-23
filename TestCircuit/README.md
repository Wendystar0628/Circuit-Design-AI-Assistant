# TestCircuit simulation corpus

The checked-in corpus contains 43 source netlists. Model dependencies are part
of each netlist's source contract: a circuit must define a model locally or use
an explicit `.include`/`.lib` card. The executor never searches the bundled
catalog or injects a same-named model implicitly.

- 29 discrete-device circuits explicitly include
  `resources/models/ngspice/testcircuit_discrete.lib`.
- The LM741 circuit explicitly includes the real bundled `LM741.lib` macro
  model.
- The other 13 circuits use only native primitives or locally defined
  subcircuits and need no external model file.

Four former demo netlists were removed: two LT1001 circuits, one LT6201
circuit, and one LTC6247 circuit. Their available vendor libraries use
LTspice-only OTA, `uplim`/`dnlim`, and `noiseless` constructs that the bundled
ngspice runtime cannot parse reliably. Replacing those devices with ideal
op-amps would change the circuit, so no compatibility substitute is retained.
The eight historical result bundles associated with those four demos were
also removed because they were produced through the retired implicit/fallback
model path and are not trustworthy evaluation evidence.

The checked-in history was audited again during the schema-v3 provenance
migration. This migration snapshot retains 22 bundles for 11 self-contained
circuits. Another 62 bundles were removed because their old
source decks depended on the retired hidden model injector, but neither the
effective injected netlist nor the injected library identity was recorded.
Reinterpreting those runs with today's newly explicit `.include` cards would
fabricate provenance. The 30 affected source circuits remain in the 43-file
corpus and must simply be run again to produce new closure-identified results.

Four additional historical NOISE bundles were removed during the integrated
noise audit. Their logs prove that ngspice produced a one-row totals plot, but
neither `result.json` nor any former sidecar preserved `onoise_total` and
`inoise_total`. Reintegrating the spectrum or rerunning the current source
would invent historical values, so those two circuits also need a fresh run.
Historical bundle statistics therefore describe the retained, verifiable
snapshot; current coverage and success rates come from the live 43-circuit
batch evaluation.

Evaluation scripts discover `.cir` sources dynamically, so the authoritative
sample count comes from this 43-file source tree rather than a stale constant.
