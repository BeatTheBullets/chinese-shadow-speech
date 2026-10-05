from __future__ import annotations
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Protocol, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class RectSentence(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    from_: int = Field(alias="from")
    to: int
    text: str


class RectifyOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sentences: list[RectSentence]


class TranslateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    translations: list[str]


# Folded into every cache key: bump it when a prompt changes so stale responses are not reused.
PROMPT_VERSION = "1"


class TranslationCountMismatch(ValueError):
    pass


class LLM(Protocol):
    def rectify(self, chunk_chars: list[str], context_chars: list[str]) -> RectifyOutput: ...
    def translate(self, sentences: list[str]) -> list[str]: ...


class FakeLLM:
    def __init__(self, rectify_fn: Callable[[list[str], list[str]], RectifyOutput],
                 translate_fn: Callable[[list[str]], list[str]]):
        self._r, self._t = rectify_fn, translate_fn

    def rectify(self, chunk_chars, context_chars):
        return self._r(chunk_chars, context_chars)

    def translate(self, sentences):
        return self._t(sentences)


RECTIFY_SYSTEM = (
    "You repair Mandarin ASR transcripts for shadowing practice. You receive characters with indices. "
    "Group them into natural, shadowable sentences or clauses of roughly {min_chars}-{max_chars} characters; "
    "prefer splitting long sentences at commas, 的时候, 但是, 所以. For each group return from/to (inclusive "
    "indices into the given chars, never into the context) and text: the corrected, punctuated simplified-Chinese "
    "text for exactly those characters. Fix homophone errors, punctuation and clearly wrong fillers only. Do not "
    "paraphrase, add or drop content. Ranges must be contiguous, non-overlapping and cover every index."
)


class AnthropicLLM:
    def __init__(self, model: str, effort: str, cache_dir: Path, min_chars: int = 6, max_chars: int = 25):
        import anthropic
        self._client = anthropic.Anthropic()
        self.model, self.effort, self.cache_dir = model, effort, cache_dir
        self.min_chars, self.max_chars = min_chars, max_chars

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(f"v{PROMPT_VERSION}:{key}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _cached(self, key: str, make: Callable[[], dict], parse: Callable[[dict], T]) -> T:
        """Return parse(response) for `key`. A response is cached only after `parse` accepts it, and the
        cache file is written atomically. An unreadable or invalid cache file counts as a miss."""
        p = self._cache_path(key)
        try:
            return parse(json.loads(p.read_text()))
        except Exception:
            pass
        data = make()
        result = parse(data)
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return result

    def _call(self, system: str, user: str, schema_model: type[BaseModel]) -> dict:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": schema_model.model_json_schema(by_alias=True)}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    def rectify(self, chunk_chars: list[str], context_chars: list[str]) -> RectifyOutput:
        payload = {
            "context_before": "".join(context_chars),
            "chars": [{"i": i, "c": c} for i, c in enumerate(chunk_chars)],
        }
        key = "rectify:" + self.model + ":" + "".join(chunk_chars)
        return self._cached(key, lambda: self._call(
            RECTIFY_SYSTEM.format(min_chars=self.min_chars, max_chars=self.max_chars),
            json.dumps(payload, ensure_ascii=False), RectifyOutput), RectifyOutput.model_validate)

    def translate(self, sentences: list[str]) -> list[str]:
        key = "translate:" + self.model + ":" + "\n".join(sentences)

        def parse(data: dict) -> list[str]:
            out = TranslateOutput.model_validate(data).translations
            if len(out) != len(sentences):
                raise TranslationCountMismatch(f"{len(out)} translations for {len(sentences)} sentences")
            return out

        try:
            return self._cached(key, lambda: self._call(
                "Translate each Mandarin sentence into natural English. Return exactly one translation per input, in order.",
                json.dumps({"sentences": sentences}, ensure_ascii=False), TranslateOutput), parse)
        except TranslationCountMismatch:
            return [""] * len(sentences)
