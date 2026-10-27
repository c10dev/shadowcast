# Roadmap

[한국어](roadmap.ko.md)

The current goal is **checking**: rebuild the physical state of a scene from prose and find continuity errors in movement, contact, and objects. This document sets the exit criteria for checking and the milestones after it.

Status: plan. Decisions 1 to 5 below are settled. Cost and size numbers marked "estimate" are not measured.

## Where we are

Pilot set v2: `data/scenes-v2-pilot.json`, 11 scenes, 37 items (11 clean, 26 error), 4 to 7 sentences, 1 or 2 characters. Accuracy per condition (A / B / C):

| Model | A | B | C before the prompt change | C after `e136682` |
|---|---|---|---|---|
| Gemini 4 Argon | 0.973 | 0.973 | 1.00 | not run |
| Claude Opus 5.5 | 0.973 | 1.00 | 0.919 | 1.00 |
| Claude Sonnet 5.5 | 0.919 | 0.946 | 0.865 | 0.730 (false alarm rate 0.455) |

Sources: `results/run-v2-20261027-1718*` (A, B, and C before the change), `results/run-v2-20261027-173035-*` and `results/run-v2-20261027-173516-*` (C after the change).

What this tells us:

- The pilot set cannot test the proposed false alarm limit of 0.1. With 0 false alarms in 11 clean items, the 95% Wilson upper bound is 0.26.
- Conditions B and C give the model the gold initial state. Real use in Canon has no gold initial state.
- Two prompt lines moved Opus up and Sonnet down on the same 37 items. Prompt changes tuned on the scored items can overfit. The next set needs a dev part and a test part.

## Exit criteria for checking

### Set v3

| Item | Target |
|---|---|
| Scenes | 40 or more, 20 to 40 sentences each |
| Characters | 3 or more in at least half of the scenes |
| Clean items | 40 (about 1,000 clean sentences) |
| Error items | 100 or more |
| Per rule | 6 or more error items for each rule except `not_held` |
| Difficulty | `implicit` 50% or more |
| Memory distance | 20 or more errors whose cause is more than 15 sentences back |
| Contact and facing | 30 or more errors |
| Real writer-model errors | 30 or more, rewritten (see "Data rules") |
| Split | dev 15 scenes, test 25 scenes. Prompt changes use dev only |

### Condition D

Add condition D: the paragraph and the character list only, with no initial state. This is what Canon can give in real use. Report D next to the best of A, B, and C.

### Metrics

Measure on the test part with the target model Gemini, in the best condition and in condition D.

| Metric | Limit |
|---|---|
| Recall | 0.8 or more. With 100 error items, 0.79 gives a 95% lower bound of 0.70 |
| False alarm rate per clean item | 0.1 or less |
| False alarms per 100 clean sentences | 1 or less |
| Localization | 0.9 or more |
| Recall per rule | 0.6 or more for each rule, so that no channel is blind |
| Repeat stability | Accuracy changes by 0.03 or less between two runs of the same setup |
| Cost | One episode check costs no more than one Canon review |

The per-sentence false alarm limit is necessary because an author sees warnings per episode, not per item. An estimate of 120 sentences per episode gives 1 or 2 false warnings per episode at the limit.

### Set validity

The set must separate models: Sonnet or gemma must score at least 0.1 below Gemini. This replaces the old stage 1 condition "the strongest model does not get a full score". A full score from Gemini on a realistic set means that checking works. It does not mean that the set is too easy.

## Milestones

| Order | Milestone | Done when | Depends on | Cost (estimate) |
|---|---|---|---|---|
| M1 | Canon connection, shadow mode | Finds more movement errors than the current Canon review, and 1 or fewer false alarms per 100 sentences on 20 real episodes | Checking done | About 100 Gemini calls, USD 1 to 3; 2 to 3 hours of review by hand |
| M2 | Fix suggestions with a check loop | 0.9 or more of the suggestions pass the engine check again; 0.8 or more natural in a hand sample of 30 | Checking done; the Canon screen needs M1 | About 360 calls, about USD 1; 1 hour by hand |
| M3 | More state channels | Out-of-channel errors in the M1 inbox fall to half or less; v3 scores drop by 0.02 or less | M1 inbox | Half a day to one day per channel; few calls |
| M4 | State before writing (prevention) | On the same 30 plots, 30% fewer errors per 100 sentences; no loss in style metrics | M1, M3 | About 180 calls, USD 5 to 15; half a day by hand |
| M5 | Cheap extractor (gemma, then LoRA) | gemma in condition C gets 90% of Gemini recall with a false alarm rate of 0.1 or less | Checking done; start only on condition | Synthetic data USD 10 to 30; some GPU hours |
| M6 | Public benchmark (English optional) | Frozen version, private test part, results for 3 outside models, data card | M3 format freeze | Much hand work; few calls |

### M1. Canon connection, shadow mode

- Goal: run the checker on real Canon episodes beside the current review. Collect warnings and the author's verdict on each warning.
- Output:
  - Split an episode into scenes. Clear the state at each scene boundary.
  - Initial state from Canon `CharacterState.attire`. Fields that Canon does not have stay unknown.
  - A `shadow` mode in the Canon research screen (`TRIAL_MODES`), then an optional mode in the Canon review path.
  - An inbox of warnings with the author's verdict (correct or false alarm).
- First measure the current Canon review per error kind (body, contact, object). No baseline by kind exists yet.
- Data: Canon test works only (decision 3). Real errors go into the public set only after a rewrite.
- The connection code lives in the Canon repository.

### M2. Fix suggestions

- Goal: for each violation, suggest 1 or 2 rewrites. The engine extracts and checks each suggestion again. The author sees only suggestions with no violation left and no new violation.
- Scope (decision 4): change the error sentence, and optionally add one sentence just before it. Many `hand_full` fixes need a release first.
- Output: a fix prompt and the check loop in shadowcast; a link to the Canon passage edit tool.
- Also measure the edit size: the median changed part of a sentence.

### M3. More state channels

- Candidates: posture (stand, sit, lie), side slots (a bag carried on the side), gaze, height.
- Add a channel only when it holds 15% or more of the out-of-channel errors in the M1 inbox. Without M1 data, start with posture.
- Each channel gets events, rules, and 8 or more error items. The scene format moves to v3.
- Two prompt lines moved Sonnet from 0.865 to 0.730. Check each channel for regressions on dev and test.

### M4. State before writing

- Goal: give the writer model the scene state and measure whether errors go down.
- The checker is the measuring tool here. Start only after its false alarm rate is known to be low.
- In Canon, put the state block after the fixed blocks, so that the prompt cache still matches.
- Decision 5: turn it on by default in Canon only after the measurement.

### M5. Cheap extractor

- Start only if the M1 cost per episode goes over the limit, or if the cost of automatic writing becomes a problem (decision 5).
- First measure gemma on v3. If it is not enough, train with synthetic data: the engine makes events, a model writes sentences, and the engine labels them.

### M6. Public benchmark

- Keep the test part private, so that it does not leak into training data.
- An English set needs new text, not a translation. Korean subject drop and particles are part of what makes extraction hard.
- Decide public release and the English set later (decision 5).

## Merged or moved candidates

- Long scenes and real writer-model errors are part of the checking exit criteria, not separate milestones.
- State across episodes stays out of the engine scope (see the scope table in the [README](../README.md)). M1 reads the initial state from Canon. M4 can propose the end state back to Canon. Canon stores it.

## Decisions

| # | Decision | Settled |
|---|---|---|
| 1 | Set validity | Realism requirements and model separation (Sonnet or gemma 0.1 or more below Gemini) |
| 2 | False alarm unit | Both: 0.1 or less per clean item, and 1 or less per 100 clean sentences |
| 3 | Data for M1 | Canon test works only. The public set takes rewritten errors only |
| 4 | M2 edit scope | Change the error sentence, and optionally add one sentence before it |
| 5 | Later choices | M4 default after measurement; M5 after the M1 cost; M6 release and the English set later |

## Data rules

- No real manuscripts, no sexual content, and no characters who look like minors.
- Errors from real writer-model output are rewritten. Only the error type moves into the set.
- API keys stay in `.env`, which git ignores.
