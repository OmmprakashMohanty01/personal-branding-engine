import re

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

    @staticmethod
    def sanitize_for_linkedin_api(text: str) -> str:
        """
        No-op sanitizer. Removed regex for stripping parentheses to fix truncation bugs.
        """
        return text
