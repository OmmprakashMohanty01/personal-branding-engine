# Content Generation Engine Guide

This document details the design, template engineering strategies, formatting filters, and customization guides for the Content Generation Engine (CGE).

---

## 1. High-Level Engine Architecture

The Content Generation Engine connects inputs from the database (Trends and Personas) with the LLM Abstraction Layer, post-processes the generated output via platform formatters, and registers draft artifacts.

```
┌───────────────┐      ┌───────────────┐
│     Trend     │      │    Persona    │
└───────┬───────┘      └───────┬───────┘
        │                      │
        ▼                      ▼
┌──────────────────────────────────────┐
│            PromptFactory             │
│   (Jinja2 Template compilation)      │
└──────────────────┬───────────────────┘
                   │
                   ▼ [System + User Prompts]
┌──────────────────────────────────────┐
│         FallbackLLMProvider          │
│   (Groq / OpenAI / Gemini APIs)      │
└──────────────────┬───────────────────┘
                   │
                   ▼ [Raw Content Text]
┌──────────────────────────────────────┐
│          Platform Formatters         │
│   (Length checks, Emoji limits)      │
└──────────────────┬───────────────────┘
                   │
                   ▼ [Formatted Content]
┌──────────────────────────────────────┐
│             ContentDraft             │
│   (Saved to DB with PENDING status)  │
└──────────────────────────────────────┘
```

---

## 2. Prompt Engineering & Jinja2 Templates

We use Jinja2 string rendering to isolate guidelines from programmatic python scripts. The Prompt Factory manages two primary template blocks:

### 2.1 System Persona Prompt Template
Builds structural formatting targets, vocabulary constraints, and platform layout expectations:
```jinja2
You are an expert content creator writing for {{ platform.upper() }}.
Your writing style is governed by the following persona guidelines:
Name: {{ persona.name }}
Tone: {{ persona.tone_description }}
Vocabulary Rules: {{ persona.vocabulary_rules }}
Formatting Preferences: {{ persona.formatting_preferences }}

Strict Platform Rules:
{% if platform == 'x' %}
- Write a short, punchy post. If the content requires deep explanation, write it in a structured thread format where each post in the thread is separated by a new line with "---thread-split---".
- Keep individual thread parts strictly under 250 characters.
- Minimal hashtags (max 1).
{% elif platform == 'linkedin' %}
- Start with a strong, curiosity-inducing hook line.
- Use clean line breaks (double newlines) to improve scannability.
- Cap emoji count at maximum 3.
- Match professional tech branding voice.
...
```

### 2.2 User Context Prompt Template
Injects the trending subject and any direct adjustment commands:
```jinja2
Develop a piece of content based on the following trending topic:
Title: {{ trend.title }}
Summary: {{ trend.summary }}
Topic Category: {{ trend.topic }}
Source Metadata: {{ trend.metadata_json }}

{% if feedback %}
User feedback adjustment request:
"{{ feedback }}"
Modify the generation to address this feedback request.
{% endif %}
```

---

## 3. Platform Formatters

To guarantee compliance with social media layout boundaries, output text undergoes post-processing validation:

* **X (Twitter) Formatter**: Measures overall string length. If it exceeds 280 characters, it dynamically segments sentences and paragraphs into a multi-part thread, inserting the designated splitter separator (`---thread-split---`).
* **LinkedIn Formatter**: Enforces readable spacing. It automatically counts emoji unicode code points and strips any characters after the first three to ensure a clean layout.
* **Threads Formatter**: Formats casual phrasing, appending an open question if none is present at the end of the text.
* **Substack Formatter**: Ensures standard Markdown styling, prefixing a title header if it is missing from the output.

---

## 4. Extension Guide: Adding a Platform Formatter (e.g. Medium)

To support a new platform (like Medium), complete these three steps:

### Step 1: Write the Formatter
Add a new class inside `backend/app/services/generation/formatters.py`:

```python
class MediumFormatter:
    """Format Medium posts: add publication header and tag metadata."""
    
    def format(self, text: str) -> str:
        formatted = text.strip()
        # Enforce header presence and append publication signature
        if not formatted.startswith("# "):
            formatted = "# Tech Insights\n\n" + formatted
        formatted += "\n\n---\n*Originally published on AI Personal Branding Engine.*"
        return formatted
```

### Step 2: Register in PromptFactory
Edit `backend/app/services/generation/prompts.py` to add any specific rule blocks under `SYSTEM_TEMPLATE`:
```jinja2
{% elif platform == 'medium' %}
- Write in-depth long form articles.
- Include structured sections.
```

### Step 3: Wire into GenerationOrchestrator
Edit `backend/app/services/generation/orchestrator.py`:
1. Import `MediumFormatter` or instantiate it.
2. Update the conditional switch inside `generate_draft()`:
```python
elif plat_lower == "medium":
    formatted_output = self.medium_formatter.format(raw_output)
```
The database model and API routes will dynamically adapt without structural schema updates!
