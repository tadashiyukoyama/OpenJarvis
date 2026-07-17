"""Decorator-based registry for runtime discovery of pluggable components.

Adapted from IPW's ``src/ipw/core/registry.py``.  Each typed subclass gets its
own isolated storage so registrations in one registry never leak into another.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

if TYPE_CHECKING:
    from openjarvis.agents._stubs import BaseAgent
    from openjarvis.engine._stubs import InferenceEngine
    from openjarvis.memory.store import FactStore
    from openjarvis.tools.storage._stubs import MemoryBackend

T = TypeVar("T")
_MISSING = object()


class AgentExecutionMode(str, Enum):
    """Execution boundary selected for a registered agent."""

    ENGINE = "engine"
    EXTERNAL = "external"


@dataclass(frozen=True)
class AgentDescriptor:
    """Immutable execution metadata for one registered agent."""

    name: str
    execution_mode: AgentExecutionMode | str = AgentExecutionMode.ENGINE
    requires_engine: Optional[bool] = None
    requires_model: Optional[bool] = None
    external_runtime: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("AgentDescriptor.name must be nonempty")
        name = self.name.strip()
        try:
            mode = (
                self.execution_mode
                if isinstance(self.execution_mode, AgentExecutionMode)
                else AgentExecutionMode(str(self.execution_mode).lower())
            )
        except ValueError as exc:
            raise ValueError(
                f"Unsupported agent execution mode: {self.execution_mode!r}"
            ) from exc

        if mode is AgentExecutionMode.ENGINE:
            if self.requires_engine is not None and not self.requires_engine:
                raise ValueError("ENGINE agents require an engine")
            if self.external_runtime is not None:
                raise ValueError("ENGINE agents cannot declare external_runtime")
            requires_engine = True
            requires_model = (
                True if self.requires_model is None else self.requires_model
            )
        else:
            if self.requires_engine:
                raise ValueError("EXTERNAL agents cannot require an engine")
            if self.requires_model:
                raise ValueError("EXTERNAL agents cannot require a model")
            if (
                not isinstance(self.external_runtime, str)
                or not self.external_runtime.strip()
            ):
                raise ValueError("EXTERNAL agents require external_runtime")
            requires_engine = False
            requires_model = False

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "execution_mode", mode)
        object.__setattr__(self, "requires_engine", requires_engine)
        object.__setattr__(self, "requires_model", requires_model)
        if self.external_runtime is not None:
            object.__setattr__(self, "external_runtime", self.external_runtime.strip())


class RegistryBase(Generic[T]):
    """Generic registry base class with class-specific entry isolation."""

    @classmethod
    def _entries(cls) -> Dict[str, T]:
        attr_name = f"_registry_entries_{cls.__name__}"
        storage = getattr(cls, attr_name, None)
        if storage is None:
            storage: Dict[str, T] = {}
            setattr(cls, attr_name, storage)
        return storage

    @classmethod
    def register(cls, key: str) -> Callable[[T], T]:
        """Decorator that registers *entry* under *key*."""

        def decorator(entry: T) -> T:
            entries = cls._entries()
            if key in entries:
                raise ValueError(f"{cls.__name__} already has an entry for '{key}'")
            entries[key] = entry
            return entry

        return decorator

    @classmethod
    def register_value(cls, key: str, value: T) -> T:
        """Imperatively register a *value* under *key*."""
        entries = cls._entries()
        if key in entries:
            raise ValueError(f"{cls.__name__} already has an entry for '{key}'")
        entries[key] = value
        return value

    @classmethod
    def get(cls, key: str) -> T:
        """Retrieve the entry for *key*, raising ``KeyError`` if missing."""
        try:
            return cls._entries()[key]
        except KeyError as exc:
            raise KeyError(
                f"{cls.__name__} does not have an entry for '{key}'"
            ) from exc

    @classmethod
    def create(cls, key: str, *args: Any, **kwargs: Any) -> Any:
        """Look up *key* and instantiate it with the given arguments."""
        entry = cls.get(key)
        if not callable(entry):
            raise TypeError(
                f"{cls.__name__} entry '{key}' is not callable"
                " and cannot be instantiated"
            )
        return entry(*args, **kwargs)

    @classmethod
    def items(cls) -> Tuple[Tuple[str, T], ...]:
        """Return all ``(key, entry)`` pairs as a tuple."""
        return tuple(cls._entries().items())

    @classmethod
    def keys(cls) -> Tuple[str, ...]:
        """Return all registered keys as a tuple."""
        return tuple(cls._entries().keys())

    @classmethod
    def contains(cls, key: str) -> bool:
        """Check whether *key* is registered."""
        return key in cls._entries()

    @classmethod
    def clear(cls) -> None:
        """Remove all entries (useful in tests)."""
        cls._entries().clear()


# ---------------------------------------------------------------------------
# Typed subclass registries — one per primitive
# ---------------------------------------------------------------------------


class ModelRegistry(RegistryBase[Any]):
    """Registry for ``ModelSpec`` objects."""


class EngineRegistry(RegistryBase[Type["InferenceEngine"]]):
    """Registry for inference engine backends."""


class MemoryRegistry(RegistryBase[Type["MemoryBackend"]]):
    """Registry for memory / retrieval backends."""


class FactStoreRegistry(RegistryBase[Type["FactStore"]]):
    """Registry for automatic-memory fact store backends."""


class AgentRegistry(RegistryBase[Type["BaseAgent"]]):
    """Registry for agent implementations."""

    @classmethod
    def _descriptors(cls) -> Dict[str, AgentDescriptor]:
        attr_name = "_agent_descriptors"
        storage = getattr(cls, attr_name, None)
        if storage is None:
            storage: Dict[str, AgentDescriptor] = {}
            setattr(cls, attr_name, storage)
        return storage

    @classmethod
    def _make_descriptor(
        cls,
        key: str,
        *,
        execution_mode: AgentExecutionMode | str | None = None,
        requires_engine: Optional[bool] = None,
        requires_model: Optional[bool] = None,
        external_runtime: Optional[str] = None,
        descriptor: Optional[AgentDescriptor] = None,
    ) -> AgentDescriptor:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("AgentRegistry key must be nonempty")
        if key != key.strip():
            raise ValueError("AgentRegistry key cannot have surrounding whitespace")
        if descriptor is not None:
            if any(
                value is not None
                for value in (
                    execution_mode,
                    requires_engine,
                    requires_model,
                    external_runtime,
                )
            ):
                raise ValueError("descriptor cannot be combined with metadata")
            if descriptor.name != key:
                raise ValueError("AgentDescriptor.name must match registry key")
            return descriptor
        return AgentDescriptor(
            name=key,
            execution_mode=(
                execution_mode
                if execution_mode is not None
                else AgentExecutionMode.ENGINE
            ),
            requires_engine=requires_engine,
            requires_model=requires_model,
            external_runtime=external_runtime,
        )

    @classmethod
    def register(
        cls,
        key: str,
        *,
        execution_mode: AgentExecutionMode | str | None = None,
        requires_engine: Optional[bool] = None,
        requires_model: Optional[bool] = None,
        external_runtime: Optional[str] = None,
        descriptor: Optional[AgentDescriptor] = None,
    ) -> Callable[[Type["BaseAgent"]], Type["BaseAgent"]]:
        """Decorator that registers an agent and its execution metadata."""

        def decorator(entry: Type["BaseAgent"]) -> Type["BaseAgent"]:
            cls._register_agent(
                key,
                entry,
                execution_mode=execution_mode,
                requires_engine=requires_engine,
                requires_model=requires_model,
                external_runtime=external_runtime,
                descriptor=descriptor,
            )
            return entry

        return decorator

    @classmethod
    def register_value(
        cls,
        key: str,
        value: Type["BaseAgent"],
        *,
        execution_mode: AgentExecutionMode | str | None = None,
        requires_engine: Optional[bool] = None,
        requires_model: Optional[bool] = None,
        external_runtime: Optional[str] = None,
        descriptor: Optional[AgentDescriptor] = None,
    ) -> Type["BaseAgent"]:
        """Imperatively register an agent and its execution metadata."""

        cls._register_agent(
            key,
            value,
            execution_mode=execution_mode,
            requires_engine=requires_engine,
            requires_model=requires_model,
            external_runtime=external_runtime,
            descriptor=descriptor,
        )
        return value

    @classmethod
    def _register_agent(
        cls,
        key: str,
        entry: Type["BaseAgent"],
        *,
        execution_mode: AgentExecutionMode | str | None,
        requires_engine: Optional[bool],
        requires_model: Optional[bool],
        external_runtime: Optional[str],
        descriptor: Optional[AgentDescriptor],
    ) -> None:
        # Build and validate all metadata before touching either storage or the
        # class. Registration is one logical operation even though the two
        # stores remain deliberately simple process-local dictionaries.
        agent_descriptor = cls._make_descriptor(
            key,
            execution_mode=execution_mode,
            requires_engine=requires_engine,
            requires_model=requires_model,
            external_runtime=external_runtime,
            descriptor=descriptor,
        )
        entries = cls._entries()
        descriptors = cls._descriptors()
        entry_exists = key in entries
        descriptor_exists = key in descriptors
        if entry_exists or descriptor_exists:
            raise ValueError(
                f"{cls.__name__} already has an entry or descriptor for '{key}'"
            )

        entry_namespace = vars(entry)
        had_own_agent_id = "agent_id" in entry_namespace
        previous_agent_id = getattr(entry, "agent_id", _MISSING)
        agent_id_mutated = False

        try:
            if not getattr(entry, "agent_id", None):
                # Mark this before setattr so a descriptor/metaclass that
                # raises after mutating still enters the restoration path.
                agent_id_mutated = True
                setattr(entry, "agent_id", key)
            entries[key] = entry
            descriptors[key] = agent_descriptor
        except BaseException:
            # The key was absent from both stores before the transaction, so
            # removing it is safe and cannot overwrite pre-existing state.
            # Cleanup errors must never replace the original write failure.
            try:
                if key in descriptors:
                    del descriptors[key]
            except BaseException:
                pass
            try:
                if key in entries:
                    del entries[key]
            except BaseException:
                pass

            if agent_id_mutated:
                try:
                    if had_own_agent_id:
                        setattr(entry, "agent_id", previous_agent_id)
                    elif "agent_id" in vars(entry):
                        # Restore the inherited/absent shape, not just its
                        # value, when registration created the attribute.
                        delattr(entry, "agent_id")
                except BaseException:
                    pass
            raise

    @classmethod
    def descriptor(cls, key: str) -> AgentDescriptor:
        """Return immutable metadata for *key*."""

        try:
            return cls._descriptors()[key]
        except KeyError as exc:
            raise KeyError(
                f"{cls.__name__} does not have a descriptor for '{key}'"
            ) from exc

    @classmethod
    def descriptors(cls) -> Mapping[str, AgentDescriptor]:
        """Return a read-only snapshot of all agent descriptors."""

        return MappingProxyType(dict(cls._descriptors()))

    @classmethod
    def clear(cls) -> None:
        """Remove agent classes and their metadata."""

        super().clear()
        cls._descriptors().clear()


class ToolRegistry(RegistryBase[Any]):
    """Registry for tool specifications."""


class RouterPolicyRegistry(RegistryBase[Any]):
    """Registry for router policy implementations."""


class BenchmarkRegistry(RegistryBase[Any]):
    """Registry for benchmark implementations."""


class ChannelRegistry(RegistryBase[Any]):
    """Registry for channel implementations."""


class LearningRegistry(RegistryBase[Any]):
    """Registry for learning policies."""


class SkillRegistry(RegistryBase[Any]):
    """Registry for skill manifests."""


class SpeechRegistry(RegistryBase[Any]):
    """Registry for speech backend implementations."""


class CompressionRegistry(RegistryBase[Any]):
    """Registry for context compression strategies."""


class TTSRegistry(RegistryBase[Any]):
    """Registry for text-to-speech backend implementations."""


class ConnectorRegistry(RegistryBase[Any]):
    """Registry for data source connectors (Gmail, Slack, etc.)."""


class MinerRegistry(RegistryBase[Any]):
    """Registry for Pearl mining provider implementations.

    Each provider implements the ``MiningProvider`` ABC defined in
    ``openjarvis.mining._stubs``. Registry keys are short lowercase strings
    such as ``"vllm-pearl"`` (CUDA + Hopper) and (future) ``"mlx-pearl"``,
    ``"llamacpp-pearl-metal"``, ``"ollama-pearl"``.
    """


__all__ = [
    "AgentDescriptor",
    "AgentExecutionMode",
    "AgentRegistry",
    "BenchmarkRegistry",
    "ChannelRegistry",
    "CompressionRegistry",
    "ConnectorRegistry",
    "EngineRegistry",
    "FactStoreRegistry",
    "LearningRegistry",
    "MemoryRegistry",
    "MinerRegistry",
    "ModelRegistry",
    "RegistryBase",
    "RouterPolicyRegistry",
    "SkillRegistry",
    "SpeechRegistry",
    "TTSRegistry",
    "ToolRegistry",
]
