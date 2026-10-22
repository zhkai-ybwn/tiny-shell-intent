"""Abstract base class for all intent matchers."""

from abc import ABC, abstractmethod
from typing import List
from ..schema import Candidate


class BaseMatcher(ABC):
    """Abstract interface for query matching algorithms."""

    @abstractmethod
    def match(self, query: str, top_k: int = 3) -> List[Candidate]:
        """Match an input query string to Top-K command candidates.

        Args:
            query: The user input query string.
            top_k: Number of candidate commands to return.

        Returns:
            List of Candidate objects, sorted by score descending.
        """
        pass
