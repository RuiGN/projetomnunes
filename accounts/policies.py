"""Public authorization interface for the accounts domain."""

from core.policies import AuthorizationPolicy as AuthorizationPolicy
from core.policies import current_actor_is_active as current_actor_is_active

__all__ = ["AuthorizationPolicy", "current_actor_is_active"]
