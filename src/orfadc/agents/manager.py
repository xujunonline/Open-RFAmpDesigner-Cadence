from __future__ import annotations

from ..schemas import Candidate, Spec
from .searcher import Searcher


class Manager:
    def __init__(self, searcher: Searcher | None = None) -> None:
        self.searcher = searcher or Searcher()
        self.queue: list[Candidate] = []

    def search_candidates(self, spec: Spec, seed: int = 0) -> list[Candidate]:
        candidates = self.searcher.search(spec, seed)
        self.queue.extend(candidates)
        return candidates

    def next_action(self) -> str:
        return "RefineCandidate" if self.queue else "SearchCandidates"

