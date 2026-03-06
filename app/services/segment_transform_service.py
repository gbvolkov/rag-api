from __future__ import annotations

from typing import Any

from app.core.capabilities import require_feature, require_module
from app.core.config import settings
from app.core.errors import api_error
from app.models import RaptorRun
from app.models import SegmentItem
from app.services.segment_service import SegmentService
from app.storage.object_store import object_store


class SegmentTransformService:
    def __init__(self, segment_service: SegmentService):
        self.segment_service = segment_service
        self.session = segment_service.session

    async def enrich(
        self,
        segment_set_id: str,
        *,
        llm_provider: str | None,
        llm_model: str | None,
        llm_temperature: float | None,
        params: dict[str, Any],
    ):
        require_feature(
            settings.feature_enable_llm,
            "llm",
            hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.",
        )
        base_set = await self.segment_service.get_segment_set(segment_set_id)
        rows = await self.segment_service.list_items(segment_set_id)
        if not rows:
            raise api_error(400, "empty_segment_set", "Segment set has no items", {"segment_set_version_id": segment_set_id})

        segments = self._rows_to_segments(rows)
        llm = self._get_llm(llm_provider, llm_model, llm_temperature)

        from rag_lib.processors.enricher import SegmentEnricher

        enriched = SegmentEnricher(llm=llm).enrich(segments)
        return await self.segment_service.create_derived_from_segments(
            project_id=base_set.project_id,
            document_version_id=base_set.document_version_id,
            parent_segment_set_version_id=base_set.segment_set_version_id,
            segments=enriched,
            params={**(base_set.params_json or {}), "transform": "enrich", "enrich_params": params},
            input_refs={"parent_segment_set_version_id": base_set.segment_set_version_id},
        )

    async def raptor(
        self,
        segment_set_id: str,
        *,
        max_levels: int,
        llm_provider: str | None,
        llm_model: str | None,
        llm_temperature: float | None,
        embedding_provider: str,
        embedding_model_name: str | None,
        params: dict[str, Any],
    ):
        require_feature(
            settings.feature_enable_raptor,
            "raptor",
            hint="Set FEATURE_ENABLE_RAPTOR=true to enable RAPTOR processing.",
        )
        require_feature(
            settings.feature_enable_llm,
            "llm",
            hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.",
        )
        require_module("umap", "raptor", install_hint="Install optional dependency 'umap-learn'.")

        base_set = await self.segment_service.get_segment_set(segment_set_id)
        rows = await self.segment_service.list_items(segment_set_id)
        if not rows:
            raise api_error(400, "empty_segment_set", "Segment set has no items", {"segment_set_version_id": segment_set_id})

        segments = self._rows_to_segments(rows)
        llm = self._get_llm(llm_provider, llm_model, llm_temperature)
        from rag_lib.processors.raptor import RaptorProcessor

        embeddings = self._get_embeddings(embedding_provider, embedding_model_name)
        processor = RaptorProcessor(llm=llm, embeddings=embeddings, max_levels=max_levels)
        transformed = processor.process_segments(segments)
        output = await self.segment_service.create_derived_from_segments(
            project_id=base_set.project_id,
            document_version_id=base_set.document_version_id,
            parent_segment_set_version_id=base_set.segment_set_version_id,
            segments=transformed,
            params={
                **(base_set.params_json or {}),
                "transform": "raptor",
                "raptor_params": {
                    "max_levels": max_levels,
                    "embedding_provider": embedding_provider,
                    "embedding_model_name": embedding_model_name,
                    **params,
                },
            },
            input_refs={"parent_segment_set_version_id": base_set.segment_set_version_id},
        )
        manifest = {
            "project_id": base_set.project_id,
            "source_segment_set_version_id": base_set.segment_set_version_id,
            "output_segment_set_version_id": output.segment_set_version_id,
            "max_levels": max_levels,
            "embedding_provider": embedding_provider,
            "embedding_model_name": embedding_model_name,
            "items_count": len(transformed),
        }
        key = f"projects/{base_set.project_id}/raptor_runs/{output.segment_set_version_id}/manifest.json"
        uri = object_store.put_json(key, manifest)
        run = RaptorRun(
            project_id=base_set.project_id,
            source_segment_set_version_id=base_set.segment_set_version_id,
            output_segment_set_version_id=output.segment_set_version_id,
            params_json=manifest,
            result_json={"segment_set_version_id": output.segment_set_version_id},
            artifact_uri=uri,
            status="succeeded",
        )
        self.session.add(run)
        await self.session.commit()
        return output

    def _rows_to_segments(self, rows: list[SegmentItem]) -> list:
        from rag_lib.core.domain import Segment, SegmentType

        out = []
        for row in rows:
            try:
                seg_type = SegmentType(row.type)
            except Exception as exc:
                raise api_error(
                    500,
                    "invalid_segment_type",
                    "Persisted segment item type is invalid",
                    {"item_id": row.item_id, "type": row.type, "allowed": [e.value for e in SegmentType]},
                ) from exc
            out.append(
                Segment(
                    content=row.content,
                    metadata=row.metadata_json or {},
                    segment_id=row.item_id,
                    parent_id=row.parent_id,
                    level=row.level,
                    path=row.path_json or [],
                    type=seg_type,
                    original_format=row.original_format,
                )
            )
        return out

    def _get_llm(self, provider: str | None, model: str | None, temperature: float | None):
        try:
            resolved_provider = provider or settings.llm_provider_default
            resolved_model = model or settings.llm_model_default
            resolved_temperature = settings.llm_temperature_default if temperature is None else temperature
            from rag_lib.llm.factory import create_llm

            return create_llm(
                provider=resolved_provider,
                model_name=resolved_model,
                temperature=resolved_temperature,
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc

    def _get_embeddings(self, provider: str, model_name: str | None):
        provider_normalized = str(provider).strip().lower() if provider is not None else ""
        provider_normalized = provider_normalized or "openai"

        from rag_lib.embeddings.factory import create_embeddings_model

        try:
            return create_embeddings_model(
                provider=provider_normalized,
                model_name=model_name,
            )
        except ValueError as exc:
            raise api_error(
                400,
                "invalid_embedding_provider",
                "Unsupported embedding provider",
                {"provider": provider_normalized, "error": str(exc)},
            ) from exc
        except ImportError as exc:
            raise api_error(
                424,
                "missing_dependency",
                "Embedding provider dependency is not available",
                {"provider": provider_normalized, "error": str(exc)},
            ) from exc
        except Exception as exc:
            raise api_error(
                424,
                "embedding_provider_init_failed",
                "Embedding provider initialization failed",
                {"provider": provider_normalized, "model_name": model_name, "error": str(exc)},
            ) from exc
