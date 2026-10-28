# 장면 형식 v2

장면 하나는 JSON 객체 하나다. 파일 하나에 장면 목록을 담는다. 문장마다 사건 목록이 있고, 규칙 판정기(`shadowcast/rules.py`)가 시작 상태에 사건을 차례로 적용하며 위반을 찾는다. 판정기는 글을 읽지 않는다. 사건은 사람(정답 데이터)이나 모델(조건 C 추출)이 적는다.

v1(hand-check)은 손 두 칸만 있었다. v2 는 인물마다 다섯 칸과 물건 자리를 둔다. v1 장면은 읽을 때 v2 로 바뀌고, v1 의 80항목은 v2 판정기에서도 그대로 통과한다.

## 검사

```bash
python3 -m shadowcast validate data/scenes-v2-example.json hand-check/data/scenes.json
python3 -m unittest discover -s tests
```

`validate` 는 정답 사건과 정답 라벨이 맞는지 본다.

- 정상판에는 위반이 없어야 한다.
- 오류판에는 오류 문장에서만 위반이 나와야 한다. 그 뒤 문장들에는 위반이 없어야 한다.
- 오류에 `rule` 이 있으면 오류 문장의 첫 위반이 그 규칙이어야 한다. 같은 문장에서 앞 사건이 실패해 뒤 사건이 따라 실패하는 것은 괜찮다(엉뚱한 곳에서 꺼내기가 실패하고, 이어서 건네기가 실패함).
- 모르는 사건 종류, 빠진 칸, 범위 밖 문장 번호도 잡는다.

## 장면 칸

| 칸 | 뜻 |
|---|---|
| `id`, `title` | 이름 |
| `source` | 글의 출처. `original`(직접 씀), `hand-check v1` 등 |
| `patterns` | 장면에 든 오류 종류 (자유 표기) |
| `traps` | 정상판에서 오류처럼 보이지만 오류가 아닌 행동 |
| `characters` | `{이름: {"height_cm": 숫자}}`. 높이 규칙(뒤 단계)을 위해 받아 둔다 |
| `aliases` | `{다른 이름: 물건 이름}`. 예: `{"껍데기": "달걀"}` |
| `initial_state` | `{이름: 몸}`. 아래 "상태" |
| `items` | `{물건: 자리}`. 손이나 몸에 없는 물건의 처음 자리 |
| `sentences` | `[{"text", "events"}]` |
| `errors` | `[{"sentence", "text", "events", "rule", "difficulty", "note"}]`. 오류 하나가 오류판 하나가 된다. 정상판에서 그 문장만 바꾼다. `difficulty` 는 `explicit`(오류 문장 하나만 보고 어긋남이 보임) 또는 `implicit`(앞 문장을 기억해야 보임)이다. 한 장면 안에서도 오류판마다 다를 수 있어서 오류마다 단다. v1 장면은 장면의 난이도가 그 하나뿐인 오류로 옮겨 간다. `cause` 는 독자가 기억해야 하는 상태를 정한 앞 문장 번호다(있으면 오류 문장보다 앞이어야 한다). 실행기는 오류 문장과 `cause` 의 거리로 재현율을 나눈다 |

장면 하나에 오류를 여럿 둘 수 있다. 긴 장면 하나가 정상판 1개와 오류판 여러 개가 된다. 항목 이름은 오류가 하나면 `<id>-error`, 여럿이면 `<id>-error1`, `<id>-error2` … 다.

## 상태

인물마다 다섯 칸을 둔다. 적지 않은 칸은 "모름"이다. 모름은 위반이 아니고, 처음 쓰이는 순간 값이 정해진다.

| 칸 | 값 | 예 |
|---|---|---|
| `hands` | `{"left", "right"}`. 물건 이름, `"@이름"`(그 사람을 잡음), `null`(빈손), 적지 않으면 모름 | `{"left": "손잡이", "right": null}` |
| `facing` | `{다른 인물: "front" \| "back" \| "side"}`. `front` 는 이 몸의 앞이 그 사람을 향함, `back` 은 등이 그 사람을 향함 | `{"유나": "front"}` |
| `worn` | `{부위: [안쪽, …, 바깥쪽]}` | `{"torso": ["셔츠", "백팩"]}` |
| `front`, `back` | 몸 앞 · 뒤를 차지한 것(`"@이름"` 이나 물건). `[]` 는 비었음 | `["@유나"]` |

물건 자리(`items`)는 손이나 몸에 없는 물건만 적는다. 물건을 쥐면 목록에서 빠지고, 놓을 때 `to` 를 주면 그 자리로 들어간다.

## 사건

모든 사건에 `type` 과 `character` 가 있다. `hand` 는 `left`, `right`, `both`(두 팔), `any`(문장이 밝히지 않음) 중 하나이고, 비우면 `any` 다.

| 사건 | 칸 | 하는 일 |
|---|---|---|
| `grab` | `hand`, `object`, `from`? | 물건을 쥔다. 다른 사람 손에 있던 물건이면 그 손이 빈다(건네받기). 그 손(`any` 면 어느 손이든, `both` 면 두 손 모두)에 이미 쥔 물건이면 아무것도 바꾸지 않는다 |
| `release` | `hand`, `object`, `to`? | 물건을 놓는다. `object` 가 `"@이름"` 이면 그 사람을 잡은 손만 놓고, 몸의 접촉(기대기 등)은 그대로 둔다. `untouch` 로 이미 접촉을 끝낸 사람을 놓으면 아무 일도 없다 |
| `give` | `to`, `object`, `hand`?, `to_hand`? | 물건을 다른 사람에게 건넨다 |
| `use` | `hand`, `free_hands_needed`, `action`?, `with`? | 손이 필요한 행동. `with` 는 쥐고 있어야 하는 도구 |
| `turn` | `toward` \| `away_from` \| `side_to` | 한 사람을 향해 몸을 돌린다 |
| `wear` | `item`, `zone`, `side`? | 입거나 멘다. `side` 가 `front` · `back` 이면 그 공간을 차지한다. 이미 멘 것이면 옮겨 멘다 |
| `take_off` | `item`, `free_hands_needed`?, `to`? | 벗거나 내린다. `to` 가 있으면 벗은 것이 그 자리로 간다. 벗은 것은 쥐거나 입기 전까지 "손에 있을 수도 있음"이다. 손을 차지하지 않고, 쥐지 않고도 놓거나 건네거나 도구로 쓸 수 있다. 그래서 "벗은 옷을 든 채 두 손이 필요한 행동"은 잡지 못한다 |
| `touch` | `target`, `kind`, `hand`?, `target_hand`? | 접촉을 시작한다. 종류는 아래 표 |
| `untouch` | `target` | 두 사람 사이의 접촉을 모두 끝낸다 |
| `move` | `away_from`? \| `to`? | 몸을 옮긴다 |
| `state` | `facing`?, `holds`?, `wears`?, `front`?, `back`? | 문장이 상태를 묘사한다. 상태를 바꾸지 않고 견준다 |
| `see` | `target`, `part`? | 대상의 얼굴이나 앞모습을 본다 |

접촉 종류:

| `kind` | 쓰는 손(하는 쪽 / 받는 쪽) | 차지하는 공간 | 향한 쪽(하는 쪽 → 받는 쪽 / 받는 쪽 → 하는 쪽) |
|---|---|---|---|
| `grip` | 1 / 0 | 없음 | 그대로 |
| `hold_hands` | 1 / 1 | 없음 | 그대로 |
| `hug` | 2 / 0 | 앞 / 앞 | front / front |
| `back_hug` | 2 / 0 | 앞 / 뒤 | front / back |
| `carry_back` | 2 / 0 | 뒤 / 앞 | back / front |
| `lean` | 0 / 0 | 앞 / 뒤 | front / back |
| `press` | 0 / 0 | 앞 / 앞 | front / front |

- 손으로 잡은 접촉(`grip`, `hold_hands`, `hug`, `back_hug`, `carry_back`)은 `untouch` 없이 `move away_from` 하면 위반이다.
- 손 없는 접촉(`lean`, `press`)은 멀어지면 저절로 끝난다.
- 앞 · 뒤로 맞닿은 사람에게서 몸을 돌리면, 손으로 잡고 있으면 위반이다. 손이 없으면 접촉이 끝난다.

## 위반 규칙

| `rule` | 뜻 | 예 |
|---|---|---|
| `hand_full` | 손이 필요한데 빈손이 모자람 | 손잡이를 쥔 채 두 손으로 지퍼를 엶 |
| `not_held` | 쥐지 않은 물건을 놓거나 건넴 | |
| `tool_missing` | `with` 로 밝힌 도구를 쥐고 있지 않음 | 내려놓은 볼펜으로 송장을 씀 |
| `facing_mismatch` | 묘사한 향한 쪽이 상태와 다름 | 마주 보고 섰는데 다음 문장에서 등을 보이고 섬 |
| `hidden_side` | 등을 보인 사람의 얼굴 · 앞모습을 봄 | 등 돌린 인물의 표정이 보임 |
| `layer_order` | 바깥 것을 벗지 않고 안쪽 것을 벗음 | 백팩을 멘 채 셔츠를 벗음 |
| `not_worn` | 입지 않은 것을 벗음 | |
| `space_full` | 이미 찬 앞 · 뒤 공간에 물건이나 사람을 둠 | 바짝 붙은 사람 쪽으로 백팩을 앞으로 멤 |
| `contact_kept` | 잡은 채 멀어지거나 돌아섬 | 손목을 잡힌 채 열차에서 내림 |
| `item_location` | 물건이 없는 자리에서 꺼냄 | 코트 주머니에 넣은 열쇠를 가방에서 꺼냄 |
| `state_mismatch` | 묘사한 쥔 것 · 입은 것 · 앞뒤가 상태와 다름 | 탁자에 내려놓은 컵을 쥐고 있다고 씀 |

위반이 난 사건은 상태를 바꾸지 않는다. 그 사건의 물건(또는 사람)은 "모름"이 된다. 그래서 뒤에서 그 물건을 놓거나 건네거나 벗거나 도구로 쓰는 사건은 위반을 다시 내지 않는다. 그 물건을 나중에 쥐거나 입으면 다시 판정한다. v1 의 다섯 오류 유형(`grab_full`, `use_full`, `both_conflict`, `handoff`, `forgotten_object`)은 모두 `hand_full` 이다.

## v1 에서 바뀐 판정

hand-check v1 의 조건 C 헛경보 세 가지를 고쳤다.

| 장면 | v1 | v2 |
|---|---|---|
| `s27` 바통 넘기기 | 받는 사람만 쓰인 문장에서 준 사람의 손이 비지 않음 | `grab` 한 물건이 다른 사람 손에 있으면 그 손을 비운다 |
| `s39` 우체국 송장 | 시작 상태에 없는 인물이 물건을 내밀면 위반 | 시작 상태 밖 인물의 칸은 모름이다 |
| `s28` 달걀 프라이 | 달걀을 쥐고 껍데기를 버리면 위반 | 장면의 `aliases` 로 이름을 잇는다. v1 데이터에는 `aliases` 가 아직 없다 |

## 시범 장면

`data/scenes-v2-pilot.json` 에 규칙마다 짧은 장면 11개(정상판 11, 오류판 26, 모두 직접 씀, 인물은 모두 성인이거나 나이를 밝히지 않음)가 있다. 형식 예시(`scenes-v2-example.json`)까지 합한 오류판 수는 아래와 같다.

| 규칙 | 오류판 | 장면 |
|---|---|---|
| `hand_full` | 8 | p02 생수병, p03 캐리어, p05 우유갑, p07 업은 채 휴대폰, p09 상자, p10 마늘, p11 어깨를 붙든 채 백팩, x01 지퍼 |
| `facing_mismatch` | 4 | p01 망토, p06 뒤에서 안김, p11 등을 기댔는데 얼굴을 묻음, x01 지하철 |
| `layer_order` | 4 | p02 배낭과 바람막이, p08 장갑과 반지, p11 백팩과 재킷, x01 백팩과 셔츠 |
| `state_mismatch` | 3 | p03 내려놓은 꽃다발, p07 건넨 우산, p10 건넨 칼 |
| `hidden_side` | 2 | p01 망토, p06 뒤에서 안김 |
| `space_full` | 3 | p09 상자를 안은 채 맞닿음, p11 기댄 사람 쪽으로 백팩, x01 백팩을 앞으로 멤 |
| `contact_kept` | 2 | p04 손목, p06 안은 채 등을 돌림 |
| `item_location` | 2 | p03 꽃다발, p05 열쇠 |
| `tool_missing` | 1 | p05 내려놓은 열쇠 |
| `not_worn` | 1 | p08 목도리 |

`not_held` 는 글보다 사건 목록에서 나는 실수라서 시범 장면에 따로 두지 않았다. p11 만원 버스는 한 장면에 향한 쪽 · 손 · 몸 앞 공간 · 겹침 순서가 함께 얽힌 경우다. 장면은 4~7문장, 인물은 1~2명이다. 긴 본문과 여러 인물은 5단계에서 쓴다.

## 모델로 돌리기

`shadowcast/runner.py` 가 v2 장면으로 조건 A · B · C · D 를 돌린다. A · B · C 는 hand-check 와 같다.

| 조건 | 모델 입력 | 판정 |
|---|---|---|
| A | 문단만 | 모델이 직접 판정하고 규칙 이름도 고른다 |
| B | 문단 + 장면 시작 상태(손 · 향한 쪽 · 착용 · 몸 앞뒤 · 물건 자리 · 다른 이름) | 모델이 직접 판정 |
| C | 문단 + 시작 상태 + 인물 · 물건 목록 | 모델은 사건만 뽑고 `rules.py` 가 판정 |
| D | 문단 + 인물 목록(`characters` 와 시작 상태의 이름) | 모델은 사건만 뽑고 `rules.py` 가 "모름" 상태에서 판정 |

D 는 Canon 이 실제로 줄 수 있는 입력이다. 시작 상태에만 원인이 있는 오류는 D 에서 원래 보이지 않는다. 그래서 gold 백엔드도 D 에서 재현율이 1.00 이 아니다(시범 장면 0.69). gold D 의 재현율이 그 세트에서 D 가 낼 수 있는 상한이다. 정상판에서 gold D 가 헛경보를 내면 판정기가 "모름"을 잘못 다루는 것이다.

```bash
python3 -m shadowcast run --backend gold                # 파이프라인 점검: 모든 지표가 1.00 이어야 한다
python3 -m shadowcast run --backend baseline            # "항상 오류 없음" 기준선
python3 -m shadowcast run --backend gemini --limit 2    # 앞의 장면 2개만. 비용과 출력 형식부터 본다
python3 -m shadowcast run --backend gemini
python3 -m shadowcast run --backend anthropic --model claude-sonnet-5-5
python3 -m shadowcast run --backend gemini --conditions A,B,C,D --trial 2   # 같은 설정을 다시 부른다(반복 안정성)
```

- `--trial` 이 2 이상이면 캐시 키에 반복 번호가 들어가 새로 부른다. 1 은 예전 캐시 키를 그대로 쓴다. 결과 파일 이름 끝에 `-trial2` 가 붙는다.
- 데이터는 기본이 `data/scenes-v2-pilot.json` 이다. `--data` 로 여러 파일을 줄 수 있다(예: v1 `hand-check/data/scenes.json`).
- 백엔드는 `shadowcast/backends.py` 에 있다(anthropic, gemini, ollama). Gemini 인증은 hand-check 와 같다. 키는 저장소 맨 위 `.env`, 없으면 `hand-check/.env` 에서 읽는다.
- 결과는 `results/run-v2-*.json`, 응답 캐시는 `results/cache/` 다. 캐시 키는 전체 프롬프트라서 프롬프트나 데이터를 고치면 새로 부른다.
- 추출 스키마는 평평하다. 모든 사건이 모든 칸을 갖고, 쓰지 않는 칸은 빈 문자열이다. `prompts.normalize` 가 판정기 형식으로 되돌린다. 모델이 사람 이름을 `@` 없이 쓰면 장면 인물 이름일 때 `@` 를 붙인다.
- 부위(`zone`)는 `torso · legs · feet · head · neck · hands` 중에서 고르게 한다. 모델마다 부위 이름이 달라 겹침 순서를 놓치지 않게 하려는 것이다.
- 조건 C 에서 칸이 빠진 사건(`bad_event`)은 찾은 모순으로 세지 않는다. 추출이 실패한 것이지 본문의 모순이 아니다. 행의 `bad_events` 에 따로 남긴다.
- 자리 이름은 한쪽이 다른 쪽을 품거나, 흔한 낱말(주머니, 위, 안 등)이 아닌 낱말을 함께 가지면 같은 자리로 본다(`rules.same_place`). 모델이 "바지 주머니"라고 쓰고 데이터가 "민준 바지 앞주머니"라고 써도 맞는다.

지표:

| 지표 | 뜻 |
|---|---|
| accuracy, precision, recall, false_alarm_rate, localization | hand-check 와 같다 |
| rule_accuracy | 오류를 맞는 문장에서 찾은 것 가운데 규칙 이름까지 맞힌 비율. C 는 첫 위반의 규칙 |
| by_difficulty, by_rule, by_distance | 오류판을 난이도, 규칙, `cause` 거리(`near` 15문장 이하, `far` 15문장 넘음, `-` 없음)로 나눈 재현율, 재현율의 95% 구간, 위치 |
| recall_ci, false_alarm_ci | 재현율과 헛경보율의 Wilson 95% 구간 `[아래, 위]` |
| false_alarms_per_100_clean_sentences | 정상판 문장 100개당 헛경보. 정상판에서 짚은 문장마다 1로 센다. 문장 없이 오류라고만 하면 1로 센다. `clean_sentences` 는 분모 |
| extraction (C, D) | 정상판에서 문장마다 정답 상태와 견준 칸별 정확도: `hands`(빈손 수), `facing`, `worn`(부위마다 맨 바깥), `space`(몸 앞뒤) |
| trap_false_alarm_rate | 함정이 있는 정상판을 오류로 잘못 판정한 비율 |

## 아직 없는 것

- 높이 규칙: `characters.height_cm` 만 받아 둔다.
- 백팩을 옆구리로 메는 자리: 지금은 같은 부위에 다시 멘 것으로 보고 상태를 바꾸지 않는다.
