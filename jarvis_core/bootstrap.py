from __future__ import annotations

from dataclasses import dataclass

from jarvis_core.application import (
    JarvisApplication,
)


@dataclass(
    frozen=True,
    slots=True,
)
class JarvisCoreContext:
    """
    Trusted internal Core context.

    This object is for local Core/admin transports such as the technical
    terminal. It is deliberately separate from JarvisApplication so Web
    transports do not receive direct access to internal stores, registries,
    locks, skills or security implementation objects.
    """

    memory: object
    profiles: object
    agenda: object
    routines: object
    inventory: object
    integrations: object
    book_library: object
    cognition: object
    self_engine: object
    security: object
    apps: object
    cyber_range: object
    tools: object
    memory1_store: object
    research_engine: object
    skill_context: object
    skills: object
    hybrid_brain: object
    command_lock: object
    silence_latch: object


@dataclass(
    frozen=True,
    slots=True,
)
class ApplicationBootstrapResult:
    """
    Result of constructing one live JARVIS Core application.

    Public transports consume `application`. Trusted local/admin code may
    additionally consume `context`.
    """

    application: JarvisApplication
    context: JarvisCoreContext
