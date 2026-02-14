from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.retrieval import RetrieveRequest, RetrieveResponse, RetrievalRunOut
from app.services.retrieval_service import RetrievalService
from app.services.serializers import retrieval_run_out

router = APIRouter()


@router.post("/projects/{project_id}/retrieve", response_model=RetrieveResponse)
async def retrieve(project_id: str, request: RetrieveRequest, session: AsyncSession = Depends(get_session)):
    svc = RetrievalService(session)
    return await svc.retrieve(project_id, request)


@router.get("/projects/{project_id}/retrieval_runs", response_model=list[RetrievalRunOut])
async def list_retrieval_runs(project_id: str, session: AsyncSession = Depends(get_session)):
    svc = RetrievalService(session)
    rows = await svc.list_runs(project_id)
    return [retrieval_run_out(r) for r in rows]


@router.get("/retrieval_runs/{run_id}", response_model=RetrievalRunOut)
async def get_retrieval_run(run_id: str, session: AsyncSession = Depends(get_session)):
    svc = RetrievalService(session)
    row = await svc.get_run(run_id)
    return retrieval_run_out(row)


@router.delete("/retrieval_runs/{run_id}")
async def delete_retrieval_run(run_id: str, session: AsyncSession = Depends(get_session)):
    svc = RetrievalService(session)
    row = await svc.soft_delete_run(run_id)
    return {"ok": True, "run_id": row.run_id}
