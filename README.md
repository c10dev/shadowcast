# shadowcast

한국어: [README.ko.md](README.ko.md)

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)

Prose is the shadow on the cave wall. shadowcast rebuilds the scene behind it and finds blocking, contact, and object continuity errors in fiction. It is a rule engine and a benchmark for LLM checkers.

The name comes from Plato's cave. The prisoners see only shadows on the wall and guess the real objects. A model also gets only the text. It must guess the scene behind the text: who faces which way, what each hand holds, and which clothes are on top of which. shadowcast rebuilds the objects from the shadows.

The scene data and the prompts are in Korean. The code, the rules, and the metrics do not depend on the language.

## Why it matters

Each sentence of AI-written prose can look correct. But the model does not keep a separate record of the body state, so the actions do not connect. Examples:

- Two characters hug face to face. In the next sentence, one of them leans back against the other.
- A character takes off a shirt but does not take off the backpack on top of it first.
- A person stands pressed against a character's chest. Then the character swings a backpack to the front, into the space between them.
- One arm holds up a person, and the other hand holds a strap. Then the character uses both hands to take off a coat.

A reader sees these errors at once. Language models often do not.

## How it works

shadowcast tracks five state channels for each character in one scene:

| Channel | Example |
|---|---|
| Hands | The left hand holds an umbrella. The right hand is free. |
| Facing | A shows the back to B. |
| Worn layers | Shirt, then jacket, then backpack on the torso. |
| Body front and back space | A person or a box is in front of the chest. |
| Object places | The key is in the inner pocket of the bag. |

The benchmark compares three conditions:

| Condition | Model input | Who judges |
|---|---|---|
| A | The text only | The model |
| B | The text and the start state of the scene | The model |
| C | The text, the start state, and the lists of characters and objects | The model extracts events. `shadowcast/rules.py` judges them. |

Each scene has a clean version and one or more error versions. Each error version changes one sentence. The rule engine then finds a violation such as `hand_full`, `layer_order`, `hidden_side`, or `contact_kept`. The event types, the rules, and the data format are in [docs/scene-format.md](docs/scene-format.md).

## Quick start

1. Make a virtual environment.

   ```bash
   python3 -m venv .venv
   ```

2. Install the model SDKs. The gold and baseline backends need only the standard library.

   ```bash
   .venv/bin/pip install -r hand-check/requirements.txt
   ```

3. Check the data. Clean versions must give no violation. Error versions must give a violation only in the error sentence.

   ```bash
   .venv/bin/python -m shadowcast validate data/*.json
   ```

4. Check the pipeline with the gold answers. All metrics must be 1.00.

   ```bash
   .venv/bin/python -m shadowcast run --backend gold
   ```

5. Run the tests.

   ```bash
   .venv/bin/python -m unittest discover -s tests
   ```

Model runs cost money. Start with `--limit 2` to see the cost and the output format.

```bash
.venv/bin/python -m shadowcast run --backend gemini --limit 2
```

```bash
.venv/bin/python -m shadowcast run --backend anthropic --model claude-sonnet-5-5
```

Put the keys in a `.env` file at the top of the repository. The runner reads it, and `.gitignore` keeps it out of git. Variables that the shell already sets win.

```
ANTHROPIC_API_KEY=...
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/service-account.json
GEMINI_API_KEY=...
```

- With a service account file, the Gemini backend uses Vertex AI. Without it, the backend uses `GEMINI_API_KEY`.
- Keep the key file outside the repository.
- Results go to `results/run-v2-*.json`. The response cache goes to `results/cache/`. The cache key includes the full prompt, so a prompt change makes new calls.

## Results

Cells are condition A / B / C. "Recall" is the part of error versions that the model found. "False alarm" is the part of clean versions that the model marked as an error.

### Stage 0: hand-check v1

40 short scenes, 80 items (40 clean, 40 error), hand occupancy only, 2026-10-27.

| Model | Accuracy | Recall | False alarm | C extraction |
|---|---|---|---|---|
| Claude Opus 5.5 | 1.00 / 1.00 / 0.975 | 1.00 / 1.00 / 1.00 | 0.00 / 0.00 / 0.05 | 0.967 |
| Gemini 4 Argon | 1.00 / 1.00 / 0.975 | 1.00 / 1.00 / 1.00 | 0.00 / 0.00 / 0.05 | 0.976 |
| Claude Sonnet 5.5 | 0.925 / 0.912 / 0.887 | 1.00 / 1.00 / 0.975 | 0.15 / 0.175 / 0.20 | 0.919 |
| Baseline "never an error" | 0.50 | 0.00 | 0.00 | |

These scenes were too easy. The target model scored the same as Opus, so the set could not separate the conditions.

### Stage 1: v2 pilot scenes

11 scenes, 37 items (11 clean, 26 error: 13 explicit, 13 implicit), all five channels, effort `medium`, 2026-10-27.

| Model | Accuracy | Recall (26) | False alarm (11) |
|---|---|---|---|
| Gemini 4 Argon | 0.973 / 0.973 / 1.00 | 1.00 / 1.00 / 1.00 | 0.091 / 0.091 / 0.00 |
| Claude Opus 5.5 | 0.973 / 1.00 / 0.919 | 0.962 / 1.00 / 0.962 | 0.00 / 0.00 / 0.182 |
| Claude Sonnet 5.5 | 0.919 / 0.946 / 0.865 | 0.923 / 0.962 / 0.923 | 0.091 / 0.091 / 0.273 |
| Baseline "never an error" | 0.297 | 0.00 | 0.00 |

Then two lines went into the extraction prompt, and condition C ran again. Cells are C before / after the change.

| Model | Accuracy | Recall (26) | False alarm (11) |
|---|---|---|---|
| Gemini 4 Argon | 1.00 / 0.973 | 1.00 / 1.00 | 0.00 / 0.091 |
| Claude Opus 5.5 | 0.919 / 1.00 | 0.962 / 1.00 | 0.182 / 0.00 |
| Claude Sonnet 5.5 | 0.865 / 0.730 | 0.923 / 0.808 | 0.273 / 0.455 |

- The conditions now give different results, but the direction changes with the model.
- The differences come from event extraction, not from the rules.
- The pilot scenes are still easy. Each model ran once per condition, so the run-to-run variance is not known yet.
- Token counts, costs, and the cause of each wrong item are in [README.ko.md](README.ko.md#지금까지) (in Korean).

## Roadmap

| Stage | Work | Done when |
|---|---|---|
| 0 | hand-check v1: hand occupancy only, 40 short scenes | Done |
| 1 | Benchmark v2: scene format v2, rule engine, pilot scenes, real fiction paragraphs, long texts (20 or more sentences) with 3 or more characters, real errors from writer models | The strongest model does not get a full score, and conditions A, B, and C give different results |
| 2 | Model ladder: three models × conditions A, B, and C | A table of recall, false alarm rate, and cost for each model and condition |
| 3 | Engine: choose from the stage 2 results. If C wins, extend the rule engine. If B wins, use a state table and a check prompt. | The target model meets the success criteria |
| 4 | Connection to [Canon](https://github.com/c10dev/canon), an AI fiction writing tool | The check finds more blocking errors than the current Canon review |

Proposed success criteria on real paragraphs with Gemini, the target model: recall 0.8 or more, false alarm rate 0.1 or less, and a check cost per chapter at or below one Canon review. These numbers are not final.

## Data principles

- This repository is public. It does not contain private manuscripts or text from other people's novels. It contains only paragraphs that we wrote or that are free to publish.
- It does not contain sexual content or characters who look like minors.
- A real error from a writer model goes in only as a rewritten sentence with the same type of error.
- API keys stay in `.env`, and git does not track it.

## Folders

| Folder | Contents |
|---|---|
| [shadowcast/](shadowcast/) | Engine: scene format v2 (`scenes.py`), rule engine (`rules.py`), judge and extraction prompts (`prompts.py`), model backends (`backends.py`), runner (`runner.py`) |
| [data/](data/) | v2 scene data: one format example (`scenes-v2-example.json`) and 11 pilot scenes (`scenes-v2-pilot.json`) |
| [docs/](docs/) | [Scene format v2](docs/scene-format.md) (in Korean) |
| [tests/](tests/) | Unit tests for the rules, prompts, scenes, and runner |
| [hand-check/](hand-check/) | Stage 0 experiment: hand occupancy errors in conditions A, B, and C |

## License

[Apache License 2.0](LICENSE)
