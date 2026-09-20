"""Immutable, code-defined asset-type contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SubjectKind = Literal["element", "content_node", "attachment", "none"]


@dataclass(frozen=True, slots=True)
class AssetType:
    code: str
    name: str
    media_kind: Literal["text", "image", "video", "audio", "data", "math", "vector"]
    subject_kind: SubjectKind
    storage: str
    operations: tuple[str, ...]
    # Business classification. It is intentionally independent from media_kind:
    # media_kind drives technical storage/model compatibility, tags drive routing,
    # discovery and filtering.
    tags: tuple[str, ...] = ()
    async_default: bool = False
    allows_variant: bool = False
    allows_version: bool = True
    target_ref_kind: SubjectKind | None = None
    target_content_kind: str | None = None
    context_bindings: tuple[tuple[str, str], ...] = ()
    target_scope_levels: tuple[tuple[str, str, bool], ...] = ()
