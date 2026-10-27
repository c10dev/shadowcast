"""Model backends. Each backend has call(system, user, schema) -> (output dict, meta dict).

  anthropic  Claude API (needs `pip install anthropic` and ANTHROPIC_API_KEY)
  gemini     Vertex AI with a service account key file, or an API key (needs `pip install google-genai`)
  ollama     local model through http://localhost:11434

The same classes are in hand-check/llm.py. hand-check is a closed experiment, so it keeps its copy.
"""

import json
import os
import urllib.request


class AnthropicBackend:
    # Claude Haiku 5.5 has no server-side fallback.
    NO_FALLBACK = ("claude-haiku-",)
    DEFAULT_MODEL = "claude-opus-5-5"

    def __init__(self, model, effort="medium"):
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model or self.DEFAULT_MODEL
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
        u = response.usage
        usage = {"input": u.input_tokens, "output": u.output_tokens} if u else {}
        return json.loads(text), {"model": response.model, "request_id": response._request_id, "usage": usage}


class GeminiBackend:
    """Gemini with a service account key file (Vertex AI) or an API key.

    GOOGLE_APPLICATION_CREDENTIALS  path to a service account key file (Vertex AI)
    GOOGLE_CLOUD_PROJECT            project ID; default is project_id in the key file
    GOOGLE_CLOUD_LOCATION           default "global"
    GEMINI_API_KEY                  used when no key file is set
    The effort option is not sent to Gemini. It only goes into the cache key.
    """

    DEFAULT_MODEL = "gemini-4-argon"

    def __init__(self, model, effort="medium"):
        from google import genai

        self.model = model or self.DEFAULT_MODEL
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if path:
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                path, scopes=["https://www.googleapis.com/auth/cloud-platform"])
            project = os.environ.get("GOOGLE_CLOUD_PROJECT") or creds.project_id
            if not project:
                raise RuntimeError("no project ID: set GOOGLE_CLOUD_PROJECT")
            location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
            self.client = genai.Client(vertexai=True, project=project, location=location, credentials=creds)
            self.via = "vertex"
        elif key:
            self.client = genai.Client(api_key=key)
            self.via = "api_key"
        else:
            raise RuntimeError("set GOOGLE_APPLICATION_CREDENTIALS or GEMINI_API_KEY")

    def call(self, system, user, schema):
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=without_key(schema, "additionalProperties"),
            ),
        )
        if not response.text:
            reason = response.candidates[0].finish_reason if response.candidates else None
            raise RuntimeError(f"empty response (finish_reason={reason})")
        u = response.usage_metadata
        usage = {"input": u.prompt_token_count, "output": u.candidates_token_count,
                 "thinking": u.thoughts_token_count} if u else {}
        return json.loads(response.text), {"model": response.model_version or self.model, "via": self.via,
                                           "usage": usage}


class OllamaBackend:
    def __init__(self, model, effort="medium", host="http://localhost:11434"):
        if not model:
            raise RuntimeError("--model is required for ollama")
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


def without_key(schema, name):
    """Copy a JSON schema without one keyword. Gemini accepts a subset of JSON Schema,
    and the runner ignores extra fields, so dropping "additionalProperties" is safe."""
    if isinstance(schema, dict):
        return {k: without_key(v, name) for k, v in schema.items() if k != name}
    if isinstance(schema, list):
        return [without_key(v, name) for v in schema]
    return schema


BACKENDS = {"anthropic": AnthropicBackend, "gemini": GeminiBackend, "ollama": OllamaBackend}


def make_backend(name, model, effort="medium"):
    """Return a backend, or None for gold and baseline (they need no model)."""
    cls = BACKENDS.get(name)
    return cls(model, effort) if cls else None
