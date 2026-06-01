import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.content import ContentDraft
from app.models.trend import Trend
from app.models.trend_score import TrendScore

logger = logging.getLogger("branding_engine.analytics.metrics")

class PipelineMetricsService:
    """Computes internal pipeline metrics and aggregations for the Analytics Dashboard."""
    
    async def get_dashboard_metrics(self, db: AsyncSession) -> dict:
        """Calculate and return dashboard KPIs.
        
        Returns:
            dict containing:
                - total_drafts_generated (int)
                - approval_rate (float, 0.0 - 1.0)
                - platform_distribution (dict)
                - top_performing_trends (list of dicts)
        """
        try:
            # 1. Total drafts generated
            total_stmt = select(func.count(ContentDraft.id))
            total_res = await db.execute(total_stmt)
            total_drafts = total_res.scalar() or 0
            
            # 2. Approval rate (APPROVED + PUBLISHED + FAILED_PUBLISHING / Total)
            approved_statuses = ["APPROVED", "PUBLISHED", "FAILED_PUBLISHING"]
            approved_stmt = select(func.count(ContentDraft.id)).where(ContentDraft.status.in_(approved_statuses))
            approved_res = await db.execute(approved_stmt)
            approved_count = approved_res.scalar() or 0
            
            approval_rate = round(approved_count / total_drafts, 4) if total_drafts > 0 else 0.0
            
            # 3. Platform distribution for published drafts
            dist_stmt = (
                select(ContentDraft.platform, func.count(ContentDraft.id))
                .where(ContentDraft.status == "PUBLISHED")
                .group_by(ContentDraft.platform)
            )
            dist_res = await db.execute(dist_stmt)
            dist_data = {row[0].lower(): row[1] for row in dist_res.all()}
            
            platform_distribution = {
                "linkedin": dist_data.get("linkedin", 0),
                "x": dist_data.get("x", 0),
                "threads": dist_data.get("threads", 0),
                "substack": dist_data.get("substack", 0),
            }
            
            # 4. Top performing trends (trends joined with TrendScore ordered by drafts count)
            trends_stmt = (
                select(
                    Trend.id,
                    Trend.title,
                    Trend.topic,
                    Trend.canonical_url,
                    func.coalesce(func.max(TrendScore.final_score), 0.0).label("score"),
                    func.count(ContentDraft.id).label("post_count")
                )
                .join(ContentDraft, ContentDraft.trend_id == Trend.id)
                .outerjoin(TrendScore, TrendScore.trend_id == Trend.id)
                .group_by(Trend.id, Trend.title, Trend.topic, Trend.canonical_url)
                .order_by(func.count(ContentDraft.id).desc())
                .limit(5)
            )
            trends_res = await db.execute(trends_stmt)
            top_trends = []
            for row in trends_res.all():
                top_trends.append({
                    "trend_id": row[0],
                    "title": row[1],
                    "topic": row[2],
                    "canonical_url": row[3],
                    "score": float(row[4]),
                    "post_count": int(row[5])
                })
                
            return {
                "total_drafts_generated": total_drafts,
                "approval_rate": approval_rate,
                "platform_distribution": platform_distribution,
                "top_performing_trends": top_trends
            }
            
        except Exception as e:
            logger.error(f"Error calculating SQL aggregation dashboard metrics: {str(e)}")
            # Fallback to computing in Python memory if SQLite dialect joins/aggregates fail
            return await self._get_dashboard_metrics_fallback(db)

    async def _get_dashboard_metrics_fallback(self, db: AsyncSession) -> dict:
        """Fallback to computing metrics in Python memory to avoid SQL dialect failures."""
        logger.info("Executing in-memory fallback for dashboard metrics calculation.")
        try:
            # Load all drafts
            drafts_stmt = select(ContentDraft)
            drafts_res = await db.execute(drafts_stmt)
            drafts = drafts_res.scalars().all()
            
            total_drafts = len(drafts)
            
            approved_statuses = {"APPROVED", "PUBLISHED", "FAILED_PUBLISHING"}
            approved_count = sum(1 for d in drafts if d.status in approved_statuses)
            approval_rate = round(approved_count / total_drafts, 4) if total_drafts > 0 else 0.0
            
            platform_distribution = {
                "linkedin": sum(1 for d in drafts if d.status == "PUBLISHED" and d.platform.lower() == "linkedin"),
                "x": sum(1 for d in drafts if d.status == "PUBLISHED" and d.platform.lower() == "x"),
                "threads": sum(1 for d in drafts if d.status == "PUBLISHED" and d.platform.lower() == "threads"),
                "substack": sum(1 for d in drafts if d.status == "PUBLISHED" and d.platform.lower() == "substack"),
            }
            
            # Group drafts by trend_id to count them
            trend_counts = {}
            for d in drafts:
                if d.trend_id:
                    trend_counts[d.trend_id] = trend_counts.get(d.trend_id, 0) + 1
                    
            # Load all trends that have drafts
            top_trends = []
            if trend_counts:
                trends_stmt = select(Trend).where(Trend.id.in_(list(trend_counts.keys())))
                trends_res = await db.execute(trends_stmt)
                trends = trends_res.scalars().all()
                
                # Fetch scores
                scores_stmt = select(TrendScore).where(TrendScore.trend_id.in_(list(trend_counts.keys())))
                scores_res = await db.execute(scores_stmt)
                scores = scores_res.scalars().all()
                
                trend_scores = {}
                for s in scores:
                    trend_scores[s.trend_id] = max(trend_scores.get(s.trend_id, 0.0), s.final_score)
                    
                for t in trends:
                    top_trends.append({
                        "trend_id": t.id,
                        "title": t.title,
                        "topic": t.topic,
                        "canonical_url": t.canonical_url,
                        "score": float(trend_scores.get(t.id, 0.0)),
                        "post_count": int(trend_counts.get(t.id, 0))
                    })
                # Sort by post_count descending
                top_trends.sort(key=lambda x: x["post_count"], reverse=True)
                top_trends = top_trends[:5]
                
            return {
                "total_drafts_generated": total_drafts,
                "approval_rate": approval_rate,
                "platform_distribution": platform_distribution,
                "top_performing_trends": top_trends
            }
        except Exception as e:
            logger.error(f"Critical error in in-memory fallback dashboard metrics: {str(e)}")
            return {
                "total_drafts_generated": 0,
                "approval_rate": 0.0,
                "platform_distribution": {"linkedin": 0, "x": 0, "threads": 0, "substack": 0},
                "top_performing_trends": []
            }
