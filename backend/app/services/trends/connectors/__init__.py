from app.services.trends.connectors.github import GitHubTrendSource
from app.services.trends.connectors.hacker_news import HackerNewsSource
from app.services.trends.connectors.product_hunt import ProductHuntSource
from app.services.trends.connectors.reddit import RedditTrendSource
from app.services.trends.connectors.google_trends import GoogleTrendsSource
from app.services.trends.connectors.news_api import NewsAPITrendSource

__all__ = [
    "GitHubTrendSource",
    "HackerNewsSource",
    "ProductHuntSource",
    "RedditTrendSource",
    "GoogleTrendsSource",
    "NewsAPITrendSource"
]
