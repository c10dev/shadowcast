"""Prompts and model backends.

Backends:
  anthropic  Claude API (needs `pip install anthropic` and credentials)
  ollama     local model through http://localhost:11434
  gold       returns the gold answer (pipeline self-test, no model)
  baseline   always answers "no error"
"""

import json
import urllib.request

JUDGE_SYSTEM = """너는 소설 원고의 물리 연속성 검사기다.
인물의 양손 점유만 검사한다: 각 손에 무엇을 들고 있는지, 그 상태에서 문장 속 행동이 가능한지.
- 손은 왼손과 오른손 둘뿐이다.
- 물건을 든 손으로 다른 물건을 집거나, 손이 필요한 다른 행동을 할 수 없다.
- 두 팔로 안은 물건은 두 손을 모두 차지한다.
- 든 물건 자체를 쓰는 행동(숟가락으로 떠먹기, 열쇠로 열기)은 빈손이 필요 없다.
- 어깨, 발, 몸으로 하는 행동은 빈손이 필요 없다.
- 문장이 내려놓는다고 쓰지 않았으면 물건은 계속 손에 있다.
손 점유와 관계없는 오류(시간, 성격, 자세 등)는 무시한다."""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "has_error": {"type": "boolean"},
        "sentences": {"type": "array", "items": {"type": "integer"}},
        "reason": {"type": "string"},
    },
    "required": ["has_error", "sentences", "reason"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = """너는 소설 문장에서 인물의 손 동작을 이벤트로 뽑는 추출기다.
판정은 하지 않는다. 문장에 쓰인 대로만 이벤트를 적는다.
이벤트 종류:
- grab: 물건을 손에 쥐거나 든다. 두 팔로 안으면 hand는 "both".
- release: 손에서 물건을 놓거나 내려놓거나 건넨다.
- use: 손이 필요한 행동. free_hands_needed에 그 행동에 필요한 빈손 수(0, 1, 2)를 적는다.
  든 물건 자체를 쓰는 행동, 어깨·발·몸으로 하는 행동은 0이다.
hand: 문장이 손을 밝히면 "left"/"right"/"both", 밝히지 않으면 "any".
object: 물건 이름. 없으면 빈 문자열.
action: 행동을 짧게 적는다.
이미 들고 있는 상태를 묘사만 하는 문장은 이벤트가 없다.
모든 문장(index 0부터)에 대해 항목을 하나씩 만든다."""

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "character": {"type": "string"},
        "type": {"type": "string", "enum": ["grab", "release", "use"]},
        "hand": {"type": "string", "enum": ["left", "right", "both", "any"]},
        "object": {"type": "string"},
        "free_hands_needed": {"type": "integer"},
        "action": {"type": "string"},
    },
    "required": ["character", "type", "hand", "object", "free_hands_needed", "action"],
    "additionalProperties": False,
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "events": {"type": "array", "items": EVENT_SCHEMA},
                },
                "required": ["index", "events"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}


def format_state(initial_state):
    lines = []
    for who, hands in initial_state.items():
        left = hands.get("left") or "빈손"
        right = hands.get("right") or "빈손"
        lines.append(f"- {who}: 왼손={left}, 오른손={right}")
    return "\n".join(lines)


def format_sentences(sentences):
    return "\n".join(f"[{i}] {s}" for i, s in enumerate(sentences))


def judge_prompt(item, with_state):
    parts = []
    if with_state:
        parts.append("장면 시작 상태:\n" + format_state(item["initial_state"]))
    parts.append("문단(문장 번호 포함):\n" + format_sentences(item["sentences"]))
    parts.append("손 점유 모순이 있으면 has_error=true, 모순이 처음 드러나는 문장 번호를 sentences에 적어라.")
    return "\n\n".join(parts)


def extract_prompt(item):
    return "\n\n".join([
        "장면 시작 상태:\n" + format_state(item["initial_state"]),
        "문단(문장 번호 포함):\n" + format_sentences(item["sentences"]),
        "각 문장의 손 이벤트를 뽑아라.",
    ])


class AnthropicBackend:
    # Claude Haiku 5.5 has no server-side fallback.
    NO_FALLBACK = ("claude-haiku-",)

    def __init__(self, model, effort):
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort

    def call(self, system, user, schema):
        kwargs = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        if not self.model.startswith(self.NO_FALLBACK):
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = "default"
            response = self.client.beta.messages.create(**kwargs)
        else:
            response = self.client.messages.create(**kwargs)
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise RuntimeError(f"refusal (category={category}, request={response._request_id})")
        if response.stop_reason == "max_tokens":
            raise RuntimeError(f"max_tokens reached (request={response._request_id})")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text), {"model": response.model, "request_id": response._request_id}


class OllamaBackend:
    def __init__(self, model, host="http://localhost:11434"):
        self.model = model
        self.host = host

    def call(self, system, user, schema):
        body = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())
        return json.loads(data["message"]["content"]), {"model": self.model}


def make_backend(name, model, effort):
    if name == "anthropic":
        return AnthropicBackend(model, effort)
    if name == "ollama":
        return OllamaBackend(model)
    return None  # gold and baseline need no model


def judge(backend_name, backend, item, with_state):
    if backend_name == "gold":
        err = item["error_sentence"]
        return {"has_error": err is not None, "sentences": [] if err is None else [err], "reason": "gold"}, {}
    if backend_name == "baseline":
        return {"has_error": False, "sentences": [], "reason": "baseline"}, {}
    return backend.call(JUDGE_SYSTEM, judge_prompt(item, with_state), JUDGE_SCHEMA)


def extract(backend_name, backend, item):
    if backend_name == "gold":
        return {"sentences": [{"index": i, "events": ev} for i, ev in enumerate(item["events"])]}, {}
    if backend_name == "baseline":
        # No events means no violations, which equals "no error".
        return {"sentences": [{"index": i, "events": []} for i in range(len(item["sentences"]))]}, {}
    return backend.call(EXTRACT_SYSTEM, extract_prompt(item), EXTRACT_SCHEMA)
