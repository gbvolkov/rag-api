from fastapi import APIRouter

from app.schemas.table import TableSummarizeRequest, TableSummarizeResponse
from app.services.table_service import TableService

router = APIRouter()


@router.post("/tables/summarize", response_model=TableSummarizeResponse)
async def summarize_table(request: TableSummarizeRequest):
    svc = TableService()
    summary = svc.summarize(request.markdown_table, request.summarizer)
    return TableSummarizeResponse(summary=summary, summarizer_type=request.summarizer.type)

