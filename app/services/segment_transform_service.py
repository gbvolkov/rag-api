from __future__ import annotations

from typing import Any

from app.core.capabilities import require_feature, require_module
from app.core.config import settings
from app.core.errors import api_error
from app.models import SegmentItem
from app.services.segment_service import SegmentService


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
        from rag_lib.embeddings.factory import get_embeddings_model
        from rag_lib.processors.raptor import RaptorProcessor

        embeddings = get_embeddings_model(provider=embedding_provider, model_name=embedding_model_name)
        processor = RaptorProcessor(llm=llm, embeddings=embeddings, max_levels=max_levels)
        transformed = processor.process_segments(segments)
        return await self.segment_service.create_derived_from_segments(
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

    def _rows_to_segments(self, rows: list[SegmentItem]) -> list:
        from rag_lib.core.domain import Segment, SegmentType

        out = []
        for row in rows:
            try:
                seg_type = SegmentType(row.type)
            except Exception:
                seg_type = SegmentType.TEXT
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
        from rag_lib.llm.factory import get_llm

        try:
            return get_llm(
                provider=provider or settings.llm_provider_default,
                model=model or settings.llm_model_default,
                temperature=settings.llm_temperature_default if temperature is None else temperature,
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc

