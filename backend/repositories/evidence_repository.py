from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.evidence import Evidence


class EvidenceRepository:
    async def bulk_create_evidence(
        self,
        session: AsyncSession,
        run_id: int,
        report_id: int | None,
        evidence_items: list[dict[str, Any]],
    ) -> list[Evidence]:
        existing_pairs = set(
            (
                content_hash,
                locator,
            )
            for content_hash, locator in (
                await session.execute(
                    select(Evidence.content_hash, Evidence.locator).where(
                        Evidence.run_id == run_id
                    )
                )
            ).all()
            if content_hash is not None and locator is not None
        )
        created: list[Evidence] = []
        for item in evidence_items:
            if not isinstance(item, dict):
                raise ValueError("evidence_items must contain dictionaries")
            content_hash = item.get("content_hash")
            locator = item.get("locator")
            pair = (content_hash, locator)
            if content_hash is not None and locator is not None and pair in existing_pairs:
                continue
            quote = item.get("quote")
            source_type = item.get("source_type")
            if not source_type or not quote:
                raise ValueError("evidence requires source_type and quote")
            evidence = Evidence(
                run_id=run_id,
                report_id=report_id if report_id is not None else item.get("report_id"),
                document_id=item.get("document_id"),
                source_type=source_type,
                source_uri=item.get("source_uri"),
                title=item.get("title"),
                page_number=item.get("page_number"),
                section=item.get("section"),
                chunk_id=item.get("chunk_id"),
                quote=quote,
                locator=locator,
                relevance_score=item.get("relevance_score"),
                citation_key=item.get("citation_key"),
                metadata_=item.get("metadata", item.get("metadata_")),
                content_hash=content_hash,
            )
            session.add(evidence)
            created.append(evidence)
            if content_hash is not None and locator is not None:
                existing_pairs.add(pair)
        if created:
            await session.flush()
        return created

    async def list_evidence_for_run(
        self, session: AsyncSession, run_id: int, offset: int = 0, limit: int = 200
    ) -> list[Evidence]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = await session.execute(
            select(Evidence)
            .where(Evidence.run_id == run_id)
            .order_by(Evidence.created_at.asc(), Evidence.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_evidence_for_report(
        self, session: AsyncSession, report_id: int, offset: int = 0, limit: int = 200
    ) -> list[Evidence]:
        if offset < 0 or limit < 1:
            raise ValueError("offset must be non-negative and limit must be positive")
        result = await session.execute(
            select(Evidence)
            .where(Evidence.report_id == report_id)
            .order_by(Evidence.created_at.asc(), Evidence.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
