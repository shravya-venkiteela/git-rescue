from __future__ import annotations
import re

IDK = "I don't know."
MIN_OVERLAP = 2  #shared words needed before an answer is given
STOPWORDS = {"the", "you", "your", "did", "was", "were", "what", "which", "where", "how",
             "and", "for", "are", "any", "them", "this", "that", "with", "have", "has",
             "want", "should", "would", "could", "can", "does", "then", "there", "put",
             "not", "get", "got", "just", "into", "from", "when", "why", "who", "yes", "run"}


def _stem(word: str) -> str:
    for suffix in ("ping", "ning", "ting", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    found = re.findall(r"[a-z]+", text.lower())
    return {_stem(w) for w in found if len(w) >= 3 and w not in STOPWORDS}


class SimulatedUser:
    def __init__(self, clarifications: dict[str, str] | None, max_questions: int = 5):
        self.clarifications = clarifications or {}
        self.max_questions = max_questions
        self.asked = 0
        self.unanswered: list[str] = []

    def answer(self, question: str) -> str:
        self.asked += 1
        if self.asked > self.max_questions:
            return "Please just fix it, I've answered enough questions."
        q = _words(question)
        best, best_score = None, MIN_OVERLAP - 1
        for key in sorted(self.clarifications):
            score = len(q & _words(key.replace("_", " ")))
            if score > best_score:
                best, best_score = key, score
        if best is None:
            self.unanswered.append(question)
            return IDK
        return self.clarifications[best]