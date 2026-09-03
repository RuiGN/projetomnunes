"""Selector contract for side-effect-free reads."""

from typing import Protocol, TypeVar

QueryT = TypeVar("QueryT", contravariant=True)
ResultT = TypeVar("ResultT", covariant=True)


class Selector(Protocol[QueryT, ResultT]):
    """Resolve one side-effect-free query."""

    def select(self, query: QueryT, /) -> ResultT:
        """Return the typed query result without changing domain state."""
        ...
