from __future__ import annotations

from app.core.capabilities import require_feature
from app.core.config import settings
from app.core.errors import api_error
from app.schemas.table import TableSummarizerConfig


class TableService:
    def summarize(self, markdown_table: str, summarizer: TableSummarizerConfig) -> str:
        kind = summarizer.type
        if kind == "mock":
            from rag_lib.summarizers.table import MockTableSummarizer

            return MockTableSummarizer().summarize(markdown_table)

        if kind != "llm":
            raise api_error(400, "invalid_summarizer_type", "summarizer.type must be mock or llm")

        require_feature(
            settings.feature_enable_llm,
            "llm",
            hint="Set FEATURE_ENABLE_LLM=true and configure provider credentials.",
        )

        from rag_lib.llm.factory import get_llm
        from rag_lib.summarizers.table_llm import LLMTableSummarizer

        try:
            llm = get_llm(
                provider=summarizer.llm_provider or settings.llm_provider_default,
                model=summarizer.model or settings.llm_model_default,
                temperature=settings.llm_temperature_default if summarizer.temperature is None else summarizer.temperature,
                streaming=False,
            )
        except Exception as exc:
            raise api_error(424, "missing_dependency", "LLM provider initialization failed", {"error": str(exc)}) from exc
        return LLMTableSummarizer(llm=llm).summarize(markdown_table)

