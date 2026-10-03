# LF14 final spec review

Reviewed the resolutions of the findings in `spec-review.md` against the current working tree and the recorded red/green results. No remaining finding in these reviewed paths.

Explicit status assertions now always enter their validator in `src/matchvet/matchweek_membership_integrity.py:219`. The validator requires an OBSERVED state, a non-null normalized string, a decoded string value, and membership-class coherence with the revision. Null and UNKNOWN explicit status facts can no longer bypass validation or suppress inference without a validated status fact.

The canonical decoder now enforces the policy boundary in `src/matchvet/matchweek_membership.py:673`. Policy 1 prohibits integrity snapshots and history-projection metadata. Policy 2 requires integrity on both evaluated and controlling revision snapshots. Policy-1 replay therefore retains its original semantics, and policy-2 replay cannot fall back to legacy checks. Optional fields remain omitted from historical encoding.

`red-11-review.txt` records all three former acceptance defects: injected policy-1 integrity, UNKNOWN explicit status, and null explicit status. `green-11-review.txt` records all three passing after the correction, 3 passed in 26.93 seconds.

New policy-1 creation also validates all selected conflict members in `src/matchvet/matchweek_membership_repository.py:987`. Its complete expected assertion-ID set must match each produced conflict snapshot. `red-12.txt` records the former policy-1 omission acceptance; `green-12.txt` records both policy versions rejecting that corruption, 2 passed in 14.41 seconds. Historical policy-1 replay remains separate.

Earlier findings concerning complete semantic conflict projection, required policy-2 integrity, and strict reference validation during new policy-1 creation remain resolved. This confirmation does not claim pending full-suite or live acceptance gates have completed. I inspected code and recorded test evidence without changing code or stores.
