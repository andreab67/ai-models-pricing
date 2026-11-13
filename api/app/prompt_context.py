"""Immutable local prompt snapshots, shared schema 1; no SDK or registry calls."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptContext:
    _templates: tuple[tuple[str, str], ...] = field(repr=False)
    _metadata: str = field(repr=False)

    @classmethod
    def capture(
        cls,
        app_id: str,
        name: str,
        source_path: str,
        source_version: str | None,
        templates: dict[str, str],
    ) -> PromptContext:
        """Capture actual instruction bytes before input variables are rendered.

        LANGFUSE_PROJECT_ID is optional deployment-owned identity, verified by the
        operator against the ingestion key. Missing identity remains unknown.
        Git source versions are never represented as Langfuse registry versions.
        """
        if not all(
            isinstance(value, str) and value.strip() for value in (app_id, name, source_path)
        ):
            raise ValueError("Prompt context requires app, name and source")
        if source_version is not None and not isinstance(source_version, str):
            raise ValueError("Invalid source version")
        if (
            not isinstance(templates, dict)
            or not templates
            or any(
                not isinstance(k, str) or not k or not isinstance(v, str)
                for k, v in templates.items()
            )
        ):
            raise ValueError("Prompt context requires named text templates")
        captured = tuple(sorted(templates.items()))
        components = {
            key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in captured
        }
        template_hash = hashlib.sha256(
            json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        project_id = os.environ.get("LANGFUSE_PROJECT_ID", "").strip() or None
        prompt = {
            "name": name,
            "source": "git",
            "source_path": source_path,
            "source_version": source_version,
            "version": None,
            "sha256": template_hash,
            "components": components,
        }
        manifest = {
            "schema_version": 1,
            "app_id": app_id,
            "classification": "prompts_only",
            "project_id": project_id,
            "project_identity_source": "deployment_config" if project_id else "unverified",
            "prompts": [prompt],
        }
        release_id = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        metadata = {**manifest, "release_id": release_id, "release_kind": "local_prompt_snapshot"}
        return cls(captured, json.dumps(metadata, sort_keys=True, separators=(",", ":")))

    def text(self, name: str) -> str:
        for key, value in self._templates:
            if key == name:
                return value
        raise KeyError(name)

    def metadata(self) -> dict:
        """A fresh metadata copy; callers cannot mutate the operation snapshot."""
        return json.loads(self._metadata)
