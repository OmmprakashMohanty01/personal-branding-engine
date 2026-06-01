from typing import Optional, Tuple

class TrendScorer:
    """Evaluates trending content with positive and negative keyword multipliers."""
    
    POSITIVE_KEYWORDS = {
        "ai": 15.0,
        "artificial intelligence": 15.0,
        "agentic": 15.0,
        "automation": 15.0,
        "startup": 15.0,
        "startups": 15.0,
        "career growth": 15.0,
        "career": 10.0,
        "open source": 15.0,
        "opensource": 15.0,
        "software engineering": 15.0,
        "python": 10.0,
        "fastapi": 10.0,
        "business technology": 15.0,
        "cloud": 10.0,
        "rag": 15.0
    }
    
    NEGATIVE_KEYWORDS = {
        "politics", "political", "election", "democrat", "republican", "congress", "senate",
        "celebrity", "gossip", "religion", "religious", "god", "church", "bible", "spirituality",
        "spam", "clickbait", "low quality", "divisive"
    }

    def calculate_score(self, title: str, summary: Optional[str] = None, base_metrics: float = 0.0) -> Tuple[float, float]:
        """Assess the quality and relevance score of a trend.
        
        Args:
            title: The trend title.
            summary: Optional trend summary.
            base_metrics: Standardized metrics points (e.g. upvotes, forks) ranging 0-30.
            
        Returns:
            Tuple of (raw_score, final_score) clamped to 0.0 - 100.0.
        """
        # Start base score calculation from normalized metrics (0-30 points)
        base = min(max(base_metrics, 0.0), 30.0)
        
        content_block = f"{title} {summary or ''}".lower()
        
        # Apply positive keyword modifiers
        boost = 0.0
        for keyword, weight in self.POSITIVE_KEYWORDS.items():
            if keyword in content_block:
                boost += weight
                
        raw_score = base + boost
        
        # Apply negative keyword modifiers (severe penalty)
        penalized = False
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in content_block:
                penalized = True
                break
                
        final_score = raw_score
        if penalized:
            final_score = 0.0 # Strict discard rule for unwanted topics
            
        # Ensure scores are clamped between 0 and 100
        clamped_raw = min(max(raw_score, 0.0), 100.0)
        clamped_final = min(max(final_score, 0.0), 100.0)
        
        return clamped_raw, clamped_final
