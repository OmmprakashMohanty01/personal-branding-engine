import asyncio
import logging
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.schemas.trends import TrendPayload
from app.models.trend_source import TrendSource
from app.models.trend import Trend
from app.models.trend_score import TrendScore
from app.services.trends.base import BaseTrendSource
from app.services.trends.scorer import TrendScorer
from app.services.trends.deduplicator import TrendDeduplicator

logger = logging.getLogger("branding_engine.trends.aggregator")

class TrendAggregator:
    """Orchestrates concurrent retrieval, deduplication, scoring, and saving of trends."""
    
    def __init__(self, connectors: List[BaseTrendSource], max_concurrency: int = 5):
        self.connectors = connectors
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.scorer = TrendScorer()
        self.deduplicator = TrendDeduplicator()

    async def _run_connector_with_semaphore(self, connector: BaseTrendSource) -> List[TrendPayload]:
        async with self.semaphore:
            logger.info(f"Starting execution of connector: {connector.name}")
            return await connector.fetch_trends()

    async def aggregate_and_score(self) -> List[Tuple[TrendPayload, float, float]]:
        """Run all connectors in parallel, deduplicate and score the results."""
        tasks = [self._run_connector_with_semaphore(conn) for conn in self.connectors]
        
        # Concurrently gather all payloads
        results = await asyncio.gather(*tasks)
        
        # Flatten the list of lists
        all_payloads: List[TrendPayload] = []
        for payloads in results:
            all_payloads.extend(payloads)
            
        logger.info(f"Gathered {len(all_payloads)} total raw payloads from all connectors.")
        
        # Deduplicate
        unique_payloads = self.deduplicator.deduplicate(all_payloads)
        logger.info(f"Deduplicated to {len(unique_payloads)} unique trends.")
        
        scored_trends = []
        for payload in unique_payloads:
            # Map metadata engagement to base_metrics (e.g. upvotes, rating)
            upvotes = payload.metadata_json.get("upvotes", 0)
            score_metrics = min(upvotes / 10.0, 30.0) # Scale down upvotes to a 0-30 scale
            
            raw, final = self.scorer.calculate_score(
                title=payload.title,
                summary=payload.summary,
                base_metrics=score_metrics
            )
            
            scored_trends.append((payload, raw, final))
            
        return scored_trends

    async def save_to_db(self, db: AsyncSession, scored_trends: List[Tuple[TrendPayload, float, float]]):
        """Save unique trends and their calculated score histories to the DB."""
        for payload, raw, final in scored_trends:
            # Resolve TrendSource ID dynamically by name
            source_name = payload.metadata_json.get("source_name", "unknown")
            
            stmt = select(TrendSource).where(TrendSource.name == source_name)
            res = await db.execute(stmt)
            source = res.scalars().first()
            
            if not source:
                source = TrendSource(
                    name=source_name,
                    source_url=payload.metadata_json.get("source_url", "https://example.com"),
                    connector_type=payload.metadata_json.get("connector_type", "api")
                )
                db.add(source)
                await db.flush()
            
            # Find if Trend already exists by unique canonical_url
            trend_stmt = select(Trend).where(Trend.canonical_url == payload.canonical_url)
            trend_res = await db.execute(trend_stmt)
            trend = trend_res.scalars().first()
            
            if not trend:
                trend = Trend(
                    source_id=source.id,
                    canonical_url=payload.canonical_url,
                    title=payload.title,
                    summary=payload.summary,
                    topic=payload.topic,
                    published_at=payload.published_at,
                    metadata_json=payload.metadata_json
                )
                db.add(trend)
                await db.flush()
            else:
                # Update details on existing trend
                trend.title = payload.title
                if payload.summary:
                    trend.summary = payload.summary
                trend.metadata_json = payload.metadata_json
                await db.flush()
                
            # Insert score record for tracking
            score_record = TrendScore(
                trend_id=trend.id,
                raw_score=raw,
                final_score=final
            )
            db.add(score_record)
            
        await db.commit()
        logger.info(f"Successfully upserted {len(scored_trends)} trends into database.")
