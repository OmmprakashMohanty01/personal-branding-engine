import re
from typing import List, Dict
from app.schemas.trends import TrendPayload

class TrendDeduplicator:
    """Consolidates duplicate posts about similar topics into single canonical records."""
    
    def _normalize_title(self, title: str) -> str:
        """Strip casing, spaces, and punctuation to simplify matching checks."""
        title_clean = title.lower()
        title_clean = re.sub(r"[^\w\s]", "", title_clean) # Remove punctuation
        return "".join(title_clean.split()) # Remove all whitespace

    def deduplicate(self, payloads: List[TrendPayload]) -> List[TrendPayload]:
        """Group payloads by normalized title or canonical URL, merging metadata.
        
        Args:
            payloads: The list of raw TrendPayload objects.
            
        Returns:
            A list of unique TrendPayload records with merged metadata and source URLs.
        """
        canonical_map: Dict[str, TrendPayload] = {}
        
        for payload in payloads:
            norm_title = self._normalize_title(payload.title)
            
            # Match by normalized title or exact canonical URL
            match_key = None
            if norm_title in canonical_map:
                match_key = norm_title
            elif payload.canonical_url in canonical_map:
                match_key = payload.canonical_url
                
            if match_key is None:
                # Store under both normalized title and URL to cover subsequent checks
                new_payload = TrendPayload(
                    canonical_url=payload.canonical_url,
                    title=payload.title,
                    summary=payload.summary,
                    topic=payload.topic,
                    published_at=payload.published_at,
                    metadata_json=payload.metadata_json.copy()
                )
                # Ensure source URLs list exists in metadata
                if "source_urls" not in new_payload.metadata_json:
                    new_payload.metadata_json["source_urls"] = [payload.canonical_url]
                
                canonical_map[norm_title] = new_payload
                canonical_map[payload.canonical_url] = new_payload
            else:
                existing = canonical_map[match_key]
                
                # Merge logic
                # 1. Retain earlier published timestamp
                if payload.published_at < existing.published_at:
                    existing.published_at = payload.published_at
                    
                # 2. Append missing summary details
                if not existing.summary and payload.summary:
                    existing.summary = payload.summary
                    
                # 3. Merge metadata elements
                for k, v in payload.metadata_json.items():
                    if k not in existing.metadata_json:
                        existing.metadata_json[k] = v
                    elif isinstance(v, (int, float)) and isinstance(existing.metadata_json[k], (int, float)):
                        # E.g. add upvotes together
                        existing.metadata_json[k] += v
                
                # 4. Merge source URLs
                urls = set(existing.metadata_json.get("source_urls", []))
                urls.add(payload.canonical_url)
                if "source_urls" in payload.metadata_json:
                    urls.update(payload.metadata_json["source_urls"])
                existing.metadata_json["source_urls"] = list(urls)
                
        # Return unique instances
        unique_results = list({id(p): p for p in canonical_map.values()}.values())
        return unique_results
