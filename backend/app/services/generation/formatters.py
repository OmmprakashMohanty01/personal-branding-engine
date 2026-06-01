import re
from typing import List

class XFormatter:
    """Format and validate X (Twitter) posts, implementing thread splitting if needed."""
    
    def format(self, text: str) -> str:
        # Check if the LLM output explicitly contains the thread separator
        if "---thread-split---" in text:
            parts = [p.strip() for p in text.split("---thread-split---") if p.strip()]
            valid_parts = []
            for part in parts:
                if len(part) > 280:
                    # Fallback truncate/split if LLM exceeded limits
                    valid_parts.extend(self._fallback_split(part))
                else:
                    valid_parts.append(part)
            return "---thread-split---".join(valid_parts)
            
        if len(text) <= 280:
            return text.strip()
            
        # Fallback thread builder
        parts = self._fallback_split(text)
        return "---thread-split---".join(parts)

    def _fallback_split(self, text: str, max_chars: int = 260) -> List[str]:
        """Split text by sentences/paragraphs to keep each chunk under max_chars."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            # If paragraph fits, add to current chunk
            if len(current_chunk) + len(para) + 2 <= max_chars:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                
                # If paragraph itself is longer than max_chars, split by sentences
                if len(para) > max_chars:
                    sentences = re.split(r"(?<=[.!?]) +", para)
                    sub_chunk = ""
                    for sent in sentences:
                        if len(sub_chunk) + len(sent) + 1 <= max_chars:
                            sub_chunk = (sub_chunk + " " + sent).strip()
                        else:
                            if sub_chunk:
                                chunks.append(sub_chunk)
                            sub_chunk = sent
                    if sub_chunk:
                        current_chunk = sub_chunk
                else:
                    current_chunk = para
                    
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks


class LinkedInFormatter:
    """Format LinkedIn posts: optimize double-line spacing and limit emojis to max 3."""
    
    def format(self, text: str) -> str:
        # Normalize newline gaps to double newlines for spacing
        spaced_text = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", text.strip())
        
        # Robust character inspection to filter out excess emojis
        emoji_count = 0
        result = []
        for char in spaced_text:
            code = ord(char)
            # Define standard emoji and symbol code point boundaries
            is_emoji = (
                (0x1F300 <= code <= 0x1F9FF) or
                (0x2600 <= code <= 0x27BF) or
                (0x1F600 <= code <= 0x1F64F) or
                (0x1F680 <= code <= 0x1F6FF) or
                (0x1F900 <= code <= 0x1F9FF) or
                (0x1FA00 <= code <= 0x1FAFF)
            )
            if is_emoji:
                emoji_count += 1
                if emoji_count <= 3:
                    result.append(char)
            else:
                result.append(char)
                
        return "".join(result).strip()


class ThreadsFormatter:
    """Conversational Threads formatting, ensuring it ends with an engaging question."""
    
    def format(self, text: str) -> str:
        formatted = text.strip()
        # Ensure it contains a question mark somewhere near the end
        if "?" not in formatted[-50:]:
            formatted += "\n\nWhat do you think about this? Let me know!"
        return formatted


class SubstackFormatter:
    """Substack long-form Markdown formatter."""
    
    def format(self, text: str) -> str:
        # Ensure it starts with a title header if missing
        formatted = text.strip()
        if not formatted.startswith("# "):
            # If no H1 header, try to extract first line as H1 or add generic title
            lines = formatted.split("\n")
            if lines and len(lines[0]) < 80 and not lines[0].startswith("##"):
                lines[0] = f"# {lines[0]}"
                formatted = "\n".join(lines)
            else:
                formatted = "# Weekly Tech Insights\n\n" + formatted
        return formatted
