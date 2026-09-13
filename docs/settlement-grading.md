# T10 settlement grading

T10 grades the exact 37-preference v1 catalog from a local evidence pack. It is a
deterministic settlement boundary: it does not create predictions or revise a frozen
Matchweek recommendation.

## Grading rules

The source order is final official competition or league record, official federation record,
official club record, then Football-Data.co.uk. The first complete applicable record controls
each preference family. A lower source cannot replace a complete higher source because its
result is more favorable. All selected, overridden, and considered records remain in grade
provenance.

Only regulation time and ordinary stoppage time count. First-Half and Second-Half markets use
their respective half and stoppage. Extra time, shootouts, awarded scores, and unplayed
administrative results do not supply played facts. Corner markets require observed Home and
Away counts; T10 never infers either count.

Completed grades are `WIN`, `LOSS`, or the whole-goal Asian Handicap `PUSH`. `HALF_WIN` and
`HALF_LOSS` are not v1 outcomes. Unresolved evidence is `PENDING` until a grading attempt is
closed; a closed unresolved attempt is `VOID`. Postponed, cancelled, abandoned, and
uncompleted fixtures are `VOID`; forfeits and administrative awards are `VOID` when regulation
was not completed. If regulation did complete, the played regulation facts remain eligible for
grading. A resumable temporary suspension is pending and can later be graded from the completed
continuation.

## Recorded input

The CLI accepts a local JSON object. `evidence` is a non-empty list using the fields accepted by
`SettlementEvidence.from_mapping`; the shorthand names `HG`, `AG`, `H1G`, `A1G`, `HC`, and `AC`
are supported. A missing fixture status is unresolved and remains pending. Optional fields
preserve Matchweek and frozen recommendation references:

```json
{
  "fixture_id": "fixture-123",
  "matchweek_id": "2026-09-18",
  "recommendation_ids": {"match_winner_home": "recommendation-123"},
  "prediction_digests": {"match_winner_home": "sha256-of-frozen-prediction"},
  "withdrawn": false,
  "evidence": [
    {
      "source_level": "COMPETITION",
      "source_key": "league-official",
      "record_id": "league-record-123",
      "fixture_status": "COMPLETED",
      "HG": 2,
      "AG": 1,
      "H1G": 1,
      "A1G": 0,
      "HC": 6,
      "AC": 4
    }
  ]
}
```

Run `matchvet grade --input fixture-evidence.json --json`. Add `--finalize` when the
investigation is closed; missing or conflicting dependent facts then become `VOID` only for
the affected preference family.

Evidence Sets and Grades are append-only in the local store. Repeating an unchanged input is
idempotent. A correction creates a successor grade with a predecessor reference and the next
correction sequence; prior evidence, grades, and frozen prediction digests remain unchanged.
