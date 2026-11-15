# Roadmap

[한국어](roadmap.ko.md)

The current goal is **checking**: rebuild the physical state of a scene from prose and find continuity errors in movement, contact, and objects. This document sets the exit criteria for checking and the milestones after it.

Status: plan. Decisions 1 to 5 below are settled. Cost and size numbers marked "estimate" are not measured. The status of each exit criterion is from the set v3 runs. "proposed: met" means that the numbers in the source meet the target. The owner has not accepted it yet. Checking is not done: real writer-model errors are missing, and the false alarm limits fail in condition D.

## Where we are

Set v3: `data/scenes-v3-dev.json` (15 scenes, 61 items) and `data/scenes-v3-test.json` (25 scenes, 101 items). That is 40 scenes of 24 to 36 sentences and 162 items. Condition D gives the character list only, with no start state. The runs used effort `medium`, 2026-10-28 to 29.

Test part, one run with the prompts and the checker fixed at `3365c5a`. Cells are condition A / B / C / D:

| Model | Accuracy | Recall (76) | False alarm (25) | False alarms per 100 clean sentences |
|---|---|---|---|---|
| Claude Opus 5.5 | 0.99 / 0.98 / - / 0.75 | 0.99 / 0.97 / - / 0.88 | 0.00 / 0.00 / - / 0.64 | 0.00 / 0.00 / - / 4.12 |
| Claude Sonnet 5.5 | 0.87 / 0.83 / 0.73 / 0.74 | 0.95 / 0.93 / 0.89 / 0.91 | 0.36 / 0.48 / 0.76 / 0.76 | 1.24 / 1.65 / 5.77 / 6.46 |
| Gemini 4 Argon | 0.97 / 0.98 / 0.79 / 0.81 | 0.97 / 0.97 / 0.86 / 0.87 | 0.04 / 0.00 / 0.40 / 0.36 | 0.41 / 0.00 / 2.88 / 1.92 |

Sources: [README.md](../README.md#checking-set-v3), section "Checking set v3", and [README.ko.md](../README.ko.md#v3-세트-dev-와-test), section "v3 세트: dev 와 test". The per-sentence column, the dev results, the repeat runs, the Wilson intervals, and the cost are in README.ko.md only. The `results/` folder is not in git.

What this tells us:

- Gemini, the target model, has recall 0.87 in condition D (95% Wilson interval 0.77 to 0.93). This meets the limit of 0.8.
- Gemini D has a false alarm rate of 0.36 (95% Wilson interval 0.20 to 0.55). This is more than the limit of 0.1.
- Gemini B has 0 false alarms in 25 clean items, but the 95% Wilson upper bound is 0.13. The test part cannot show 0.1 or less yet.
- In long scenes, conditions C and D give many false alarms. One extraction error in a scene of more than 30 sentences makes the full clean item wrong.
- Opus C did not run on the test part, because of cost. Gemini has no repeat run yet.
- No error item comes from a real writer model yet.
- Claude calls for all of v3 cost about USD 88.

The v2 pilot results (11 scenes, 37 items) are in the README, section "Stage 1: v2 pilot scenes".

## Exit criteria for checking

### Set v3

The counts per rule and for contact and facing are not in a README. They come from the `errors[].rule` fields in `data/scenes-v3-dev.json` and `data/scenes-v3-test.json`.

| Item | Target | Set v3 | Status | Source |
|---|---|---|---|---|
| Scenes | 40 or more, 20 to 40 sentences each | 40 scenes, 24 to 36 sentences | proposed: met | README.md "Checking set v3" |
| Characters | 3 or more in at least half of the scenes | 37 of 40 scenes | proposed: met | README.ko.md "v3 세트: dev 와 test" |
| Clean items | 40 (about 1,000 clean sentences) | 40 (15 dev, 25 test); 1,170 sentences | proposed: met | README.md "Checking set v3" (false alarm 25), README.ko.md (false alarm 15); sentence count from the two data files |
| Error items | 100 or more | 122 | proposed: met | README.ko.md "v3 세트: dev 와 test" |
| Per rule | 6 or more error items for each rule except `not_held` | 8 to 17 for each of the 10 rules | proposed: met | `data/scenes-v3-dev.json`, `data/scenes-v3-test.json` |
| Difficulty | `implicit` 50% or more | 107 of 122 (88%) | proposed: met | README.ko.md "v3 세트: dev 와 test" |
| Memory distance | 20 or more errors whose cause is more than 15 sentences back | 35 | proposed: met | README.ko.md "v3 세트: dev 와 test" |
| Contact and facing | 30 or more errors | 33 (`contact_kept` 17, `facing_mismatch` 16) | proposed: met | `data/scenes-v3-dev.json`, `data/scenes-v3-test.json` |
| Real writer-model errors | 30 or more, rewritten (see "Data rules") | 0 | not met | README.ko.md "v3 세트: dev 와 test" |
| Split | dev 15 scenes, test 25 scenes. Prompt changes use dev only | dev 15, test 25. Dev fixes in `6b2b3bf` and `3365c5a`; test ran once at `3365c5a` | proposed: met | README.md "Checking set v3", README.ko.md "v3 세트: dev 와 test" |

### Condition D

Add condition D: the paragraph and the character list only, with no initial state. This is what Canon can give in real use. Report D next to the best of A, B, and C.

Status: proposed: met. Condition D ran on the dev and test parts for all three models. Source: README.md "Checking set v3".

### Metrics

Measure on the test part with the target model Gemini, in the best condition and in condition D. The best condition for Gemini is B (accuracy 0.98).

| Metric | Limit | Gemini B / D | Status | Source |
|---|---|---|---|---|
| Recall | 0.8 or more. With 100 error items, 0.79 gives a 95% lower bound of 0.70 | 0.97 / 0.87 | proposed: met | README.md "Checking set v3" |
| False alarm rate per clean item | 0.1 or less | 0.00 / 0.36 | not met (D) | README.md "Checking set v3" |
| False alarms per 100 clean sentences | 1 or less | 0.00 / 1.92 | not met (D) | README.ko.md "v3 세트: dev 와 test" |
| Localization | 0.9 or more | not reported | not measured | none |
| Recall per rule | 0.6 or more for each rule, so that no channel is blind | not reported for Gemini | not measured | README.ko.md gives Opus D only: lowest `contact_kept` 0.64, `facing_mismatch` 0.70 |
| Repeat stability | Accuracy changes by 0.03 or less between two runs of the same setup | Gemini has no repeat run | not measured | README.ko.md: dev repeat for Sonnet C 0.13 and D 0.09 |
| Cost | One episode check costs no more than one Canon review | not measured per episode | not measured | README.ko.md: about USD 88 for all Claude calls on v3 |

The per-sentence false alarm limit is necessary because an author sees warnings per episode, not per item. An estimate of 120 sentences per episode gives 1 or 2 false warnings per episode at the limit.

### Set validity

The set must separate models: Sonnet or gemma must score at least 0.1 below Gemini. This replaces the old stage 1 condition "the strongest model does not get a full score". A full score from Gemini on a realistic set means that checking works. It does not mean that the set is too easy.

Status: proposed: met. On the test part, Sonnet accuracy is 0.15 below Gemini in condition B (0.83 and 0.98) and 0.10 below in A (0.87 and 0.97). The gap is 0.06 in C and 0.07 in D. Source: README.md "Checking set v3".

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
