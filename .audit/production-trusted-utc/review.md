# Production UTC adversarial verdict

## Intent

Research and prove Termux/Android UTC options without weakening #75's actual-at-
return clock contract or implementing production time. Preserve all cutoff,
writer, completion, restart and single-selection rules. Report unavailable
confidence honestly; retain versioned research/proof and a prerequisite decision
instead of a falsely ready clock implementation.

## Reviewers

All used the same packaged prompt, rubric and code-quality lens, with read-only
access. Available Codex models substituted for the skill's unavailable defaults.
The four reviewers ran in two waves under the concurrency limit.

- Reviewer A: gpt-6.1-sol, one initial finding.
- Reviewer B: gpt-6-astra, one initial finding.
- Reviewer C: gpt-5.6-sol, two initial findings.
- Reviewer D: gpt-6-luna, one initial finding.

## Act on

1. A and B: free-play claimed a causal commit bound when the token preceded the
   commit. Record exact commit identity/order and require a fresh later source
   challenge; otherwise the prototype teaches a false timing implication.
   Fixed on prototype commit `973da41`. Five reducer traces retain the positive
   causal case and reject source-before-commit/alternate-commit cases.
2. C: two incompatible schema-1 confidence examples omitted required provenance.
   Use one named confidence schema and extract that exact object from the proof
   bundle. Explicitly null unobservable refusal evidence; it cannot qualify.
   Fixed; bundle and refused document equality was verified.
3. C: one ambiguous counter-read error term could omit the second sample error.
   Define separate absolute error bounds `e0 + e1`, their units, and the research
   aggregate term. This is a genuine conditional arithmetic obligation even
   though no provider is approved. Fixed in design/research.
4. D: comparing two random nonces does not demonstrate replay verification.
   Feed the same authenticated response into a verifier with a deterministically
   distinct outstanding request nonce. Fixed; signature remains valid but exact
   nonce binding rejects the replay, and raw signed bytes remain independently
   verifiable. This is a synthetic protocol experiment, not a live-source test.

5. C, final re-review: the extracted confidence record had a bundle-relative
   reference that could not resolve by itself. Set the unrelated synthetic
   experiment binding to null, regenerate the proof/extraction, and verify the
   retained signature and exact source identity again. Fixed on `dc39cf9`.

These findings required prototype/document corrections only. None established
a viable source or a reason to relax the current clock contract.

## Consider

None.

## Noted

None.

## Dismissed

None.

## Agreement map

A and B independently found the same causal free-play defect. C identified record
shape and arithmetic ambiguities; D identified weak nonce evidence. The four
initial distinct findings were accepted and corrected. The source-time/return-time
distinction and production refusal were supported by the reviews.

Final re-review: A, B and D reported no remaining findings on `973da41`. C found
the standalone-reference defect, then reported no findings after its correction
on `dc39cf9`.
Five distinct findings were corrected. No finding supplied a production guarantee.
