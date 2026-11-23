"""Free, offline embeddings (no API key). Anthropic has no embeddings API, so this replaces
OpenAIEmbeddings. Hashed bag-of-words + word-pieces: good for keyword-style search over the
leaflets/notes, but NOT truly semantic ("knee" will not match "joint pain")."""
import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

DIMS = 512
_WORD = re.compile(r"[a-z0-9]+")


def _features(text: str):
    words = _WORD.findall((text or "").lower())
    for w in words:
        yield w, 1.0
        if len(w) > 4:                      # word pieces help with plurals / word forms
            for i in range(len(w) - 3):
                yield "#" + w[i:i + 4], 0.3
    for a, b in zip(words, words[1:]):
        yield a + "_" + b, 0.5


def embed(text: str) -> list[float]:
    vec = [0.0] * DIMS
    for feat, weight in _features(text):
        h = int(hashlib.md5(feat.encode()).hexdigest(), 16)
        vec[h % DIMS] += weight if (h >> 9) & 1 else -weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class LocalEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [embed(t) for t in texts]

    def embed_query(self, text):
        return embed(text)


async def aembed_texts(texts: list[str]) -> list[list[float]]:
    """Used by langgraph.json for the server's Store index."""
    return [embed(t) for t in texts]
