# hand-check: 손 점유 모순 검출 기준 실험

소설 문단에서 "손 점유" 모순(양손이 찬 인물이 또 무언가를 집는 것 등)을 모델이 얼마나 잡는지 잰다.
첫 실험은 학습 없이 기존 모델과 규칙 코드만 쓴다.

## 파일

| 파일 | 역할 |
|---|---|
| `data/scenes.json` | 장면 데이터. 장면 하나가 정상판과 오류판 두 항목이 된다. |
| `rules.py` | 규칙 판정기. 시작 상태에 이벤트를 차례로 적용하고 규칙 위반을 찾는다. |
| `llm.py` | 프롬프트, 출력 스키마, 모델 백엔드(anthropic, ollama, gold, baseline). |
| `run.py` | 데이터 검증, 세 조건 실행, 채점, 결과 저장. |
| `results/` | 실행 결과(`run-*.json`)와 응답 캐시(`cache/`). |

## 세 조건

| 조건 | 모델 입력 | 판정 |
|---|---|---|
| A | 문단만 | 모델이 직접 판정 |
| B | 문단 + 장면 시작 상태 | 모델이 직접 판정 |
| C | 문단 + 장면 시작 상태 | 모델은 이벤트만 추출, `rules.py`가 판정 |

B와 C를 비교하면 "모델이 직접 판정"과 "모델은 추출, 코드가 판정" 중 어느 쪽이 나은지 알 수 있다.

## 실행

```bash
python3 run.py validate                      # 정답 이벤트와 정답 라벨이 맞는지 검사
python3 run.py run --backend gold            # 파이프라인 자체 점검: 모든 지표가 1.00이어야 한다
python3 run.py run --backend baseline        # "항상 오류 없음" 기준선
```

Claude로 돌리기. 처음 한 번 가상환경을 만들고 SDK를 설치한다:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python run.py run --backend anthropic --model claude-opus-5-5
.venv/bin/python run.py run --backend anthropic --model claude-sonnet-5-5
```

API 키는 `hand-check/.env`에 한 줄로 넣는다. `run.py`가 실행할 때 이 파일을 읽는다. `.env`는 `.gitignore`에 있어서 커밋되지 않는다.

```
ANTHROPIC_API_KEY=sk-ant-...
```

- 키를 명령줄에 직접 치지 않는다. 셸 기록에 남는다. 편집기로 파일을 만든 뒤 `chmod 600 .env`로 권한을 줄인다.
- 셸에 이미 설정된 환경 변수가 `.env`보다 우선한다.
- `.env`가 없으면 SDK가 `ANTHROPIC_API_KEY` 환경 변수나 `ant auth login` 프로필에서 읽는다.
`--limit 2`를 주면 앞의 장면 2개(4항목)만 돌린다. 처음에는 이것으로 비용과 출력 형식을 확인한다.

로컬 모델로 돌리기 (Ollama 설치와 모델 다운로드가 먼저 필요하다):

```bash
python3 run.py run --backend ollama --model <모델 이름>
```

같은 프롬프트와 같은 항목은 `results/cache/`에서 다시 읽는다. 프롬프트를 고치면 새로 호출한다.
다시 호출하려면 `results/cache/`를 지운다.

## 지표

| 지표 | 뜻 |
|---|---|
| accuracy | 오류 있음/없음 판정 정확도 |
| precision, recall | 오류판 기준 정밀도, 재현율 |
| false_alarm_rate | 정상판을 오류로 잘못 판정한 비율 |
| localization | 오류판에서 오류 문장 번호까지 맞힌 비율 |
| always_no_error_accuracy | "항상 오류 없음" 기준선의 정확도. accuracy가 이 값보다 높아야 의미가 있다 |
| extraction_free_hand_accuracy | 조건 C, 정상판에서 문장마다 인물의 빈손 수를 맞힌 비율 |
| by_difficulty, by_pattern | 오류판을 난이도와 오류 유형으로 나눈 재현율과 위치 정확도 |
| trap_false_alarm_rate | 함정(발, 어깨, 든 도구로 하는 행동 등)이 있는 정상판을 오류로 잘못 판정한 비율 |

## 데이터 구성 (장면 40개, 80항목)

| 구분 | 값 |
|---|---|
| 난이도 | explicit 20, implicit 20 |
| 오류 유형 | forgotten_object 10, grab_full 9, handoff 8, both_conflict 7, use_full 6 |
| 등장인물 수 | 1명 28, 2명 12 |
| 함정이 있는 장면 | 7 |

오류 유형:

- `grab_full`: 찬 손으로 또 집음
- `use_full`: 찬 손으로 손이 필요한 행동을 함
- `both_conflict`: 두 팔로 안은 채 한 손을 씀
- `handoff`: 건네받는 사람의 손이 참
- `forgotten_object`: 몇 문장 앞에서 든 물건을 잊음

백업:

- `data/scenes.v1-6scenes.json`: 장면 6개였던 첫 판
- `data/scenes.v2-before-review.json`: 40개로 늘린 직후, 독립 검토 반영 전 판

검토에서 정한 작성 원칙:

- 오류판의 물건은 같은 손에 함께 쥐기 어려운 것으로 고른다(뜨거운 컵, 물이 든 컵, 수박, 두 손 수레). 열쇠나 지갑처럼 작은 물건은 "한 손에 같이 쥘 수 있다"는 해석이 나온다.
- 끈이나 손목에 걸 수 있는 물건(접은 우산, 목줄, 끈 달린 카메라, 쇼핑백)은 잊은 물건으로 쓰지 않는다.
- 몸으로 하는 행동(팔 뻗기, 박수 등)은 빈손 판정에 쓰지 않는다. 손으로 잡는 행동을 쓴다.
- 정상판에만 "빈손으로" 같은 단서를 넣지 않는다. 문체만으로 두 판을 가를 수 있게 된다.

## 결과에 따른 다음 단계

| 결과 | 다음 단계 |
|---|---|
| B가 0.9 이상 | 학습하지 않는다. 상태 시트 도구와 검사 프롬프트를 만든다. |
| C가 B보다 높고 추출 정확도가 높음 | 판정은 코드에 맡기는 구조로 간다. |
| C가 낮고 추출 정확도가 낮음 | 추출이 병목이다. 추출기 학습(합성 데이터 + LoRA)을 검토한다. |
| 큰 모델은 높고 작은 모델은 낮음 | 큰 모델 출력으로 작은 모델을 증류한다. |

## 장면 추가하기

`data/scenes.json`에 장면을 추가한다.

- `initial_state`: 장면 시작 때 각 인물의 양손. 빈손은 `null`. 두 팔로 안은 물건은 양손에 같은 이름을 쓴다.
- `sentences`: 문장과 그 문장의 이벤트.
- `error`: 오류판에서 바꿀 문장 번호, 바꾼 문장, 그 문장의 이벤트.
- `difficulty`: `explicit`(오류 문장이 "든 채" 등으로 상태를 밝힘) 또는 `implicit`(독자가 앞 문장을 기억해야 보임).
- `pattern`: 오류 유형. 위 "데이터 구성"의 다섯 값 중 하나.
- `traps`(선택): 정상판에 넣은 함정 행동 목록.

오류판의 오류 문장 뒤 문장들은 오류판에서도 위반이 없어야 한다. 그래서 오류 문장은 이후 문장과 충돌하지 않는 자리에 둔다.

이벤트 형식:

```json
{"character": "지호", "type": "grab", "hand": "left", "object": "국그릇"}
{"character": "지호", "type": "release", "hand": "right", "object": "숟가락"}
{"character": "지호", "type": "use", "hand": "any", "object": null, "free_hands_needed": 1, "action": "문을 엶"}
```

- `type`: `grab`(쥠), `release`(놓음), `use`(손이 필요한 행동)
- `hand`: `left`, `right`, `both`(두 팔로 안음), `any`(문장이 손을 밝히지 않음)
- `free_hands_needed`: `use`에만 쓴다. 든 물건 자체를 쓰거나 몸으로 하는 행동은 0.

장면을 추가한 뒤 `python3 run.py validate`를 돌린다. 정상판에는 위반이 없어야 하고, 오류판에는 오류 문장에서만 위반이 나와야 한다.

## 비용 (대략적인 추산)

80항목 × 3조건 = 240회 호출이다. 호출당 입력 약 1,500토큰, 출력(생각 포함) 약 2,000토큰으로 가정하면
Claude Opus 5.5($4/$20 per 1M 토큰)에서 약 11달러다. 실제 값은 `--limit 2`로 먼저 재서 확인한다.

## 알려진 한계

- 손 점유만 본다. 자세, 접촉, 거리는 아직 없다.
- 장면 40개는 모두 직접 쓴 짧은 문장(3~5문장)이다. 실제 소설 문장 분포와 다를 수 있다.
- 오류 문장이 첫 문장인 경우는 없다. 오류 위치는 2·3번째 문장에 몰려 있다.
- 물건 이름 표기가 달라도 되도록 추출 정확도는 빈손 수로만 비교한다. 어느 손인지는 비교하지 않는다.
- 모델 호출이 실패한 항목은 "오류 없음"으로 채점하고 stderr에 기록한다.
