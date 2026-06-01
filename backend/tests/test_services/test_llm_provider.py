import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Generator

# Ensure backend/app/services is importable
sys.path.insert(0, "/Users/ommprakashmohanty/.gemini/antigravity-ide/scratch/personal-branding-engine/backend")

from app.services.llm_provider import (
    GroqProvider,
    GeminiProvider,
    OpenAIProvider,
    FallbackLLMProvider
)

@pytest.fixture
def mock_groq() -> Generator[MagicMock, None, None]:
    with patch("groq.AsyncGroq") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        # Mock async completions.create call
        mock_chat = MagicMock()
        mock_instance.chat = mock_chat
        mock_completions = MagicMock()
        mock_chat.completions = mock_completions
        
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Response from Groq"
        mock_response.choices = [MagicMock(message=mock_message)]
        
        # Async call completion mock
        mock_completions.create = AsyncMock(return_value=mock_response)
        
        yield mock_class

@pytest.fixture
def mock_openai() -> Generator[MagicMock, None, None]:
    with patch("openai.AsyncOpenAI") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance
        mock_chat = MagicMock()
        mock_instance.chat = mock_chat
        mock_completions = MagicMock()
        mock_chat.completions = mock_completions
        
        mock_response = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "Response from OpenAI"
        mock_response.choices = [MagicMock(message=mock_message)]
        
        mock_completions.create = AsyncMock(return_value=mock_response)
        
        yield mock_class

@pytest.fixture
def mock_gemini() -> Generator[MagicMock, None, None]:
    with patch("google.generativeai.GenerativeModel") as mock_model_class, \
         patch("google.generativeai.configure") as mock_configure:
        mock_model_instance = MagicMock()
        mock_model_class.return_value = mock_model_instance
        
        mock_response = MagicMock()
        mock_response.text = "Response from Gemini"
        
        mock_model_instance.generate_content_async = AsyncMock(return_value=mock_response)
        
        yield mock_model_class

@pytest.mark.asyncio
async def test_groq_provider_success(mock_groq: MagicMock):
    provider = GroqProvider(api_key="test-key", model="llama-3.3-70b-versatile")
    result = await provider.generate(prompt="Hello", system_instruction="Be polite")
    assert result == "Response from Groq"
    provider.client.chat.completions.create.assert_called_once()

@pytest.mark.asyncio
async def test_openai_provider_success(mock_openai: MagicMock):
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")
    result = await provider.generate(prompt="Hello", system_instruction="Be brief")
    assert result == "Response from OpenAI"
    provider.client.chat.completions.create.assert_called_once()

@pytest.mark.asyncio
async def test_gemini_provider_success(mock_gemini: MagicMock):
    provider = GeminiProvider(api_key="test-key", model="gemini-1.5-flash")
    result = await provider.generate(prompt="Hello", system_instruction="Be smart")
    assert result == "Response from Gemini"
    mock_gemini.assert_called_once_with(model_name="gemini-1.5-flash", system_instruction="Be smart")

@pytest.mark.asyncio
async def test_fallback_primary_success(mock_groq: MagicMock, mock_gemini: MagicMock):
    # Set up config override so fallback does not fail at initialization
    configs = {
        "groq": {"api_key": "key-g"},
        "gemini": {"api_key": "key-gem"}
    }
    fallback_provider = FallbackLLMProvider(
        primary_name="groq",
        fallback_names=["gemini"],
        custom_configs=configs
    )
    result = await fallback_provider.generate(prompt="Hi")
    assert result == "Response from Groq"
    
    # Verify primary generated, gemini was never called for generation
    groq_instance = fallback_provider.providers["groq"]
    groq_instance.client.chat.completions.create.assert_called_once()
    
    gemini_instance = fallback_provider.providers["gemini"]
    # Check that generate_content_async was not called
    # gemini_instance would use Google's GenerativeModel class mocked above
    mock_gemini.return_value.generate_content_async.assert_not_called()

@pytest.mark.asyncio
async def test_fallback_primary_fails_secondary_succeeds(mock_groq: MagicMock, mock_gemini: MagicMock):
    # Primary (Groq) fails with an API connection error
    mock_groq.return_value.chat.completions.create.side_effect = Exception("Rate limit hit")
    
    configs = {
        "groq": {"api_key": "key-g"},
        "gemini": {"api_key": "key-gem"}
    }
    fallback_provider = FallbackLLMProvider(
        primary_name="groq",
        fallback_names=["gemini"],
        custom_configs=configs
    )
    result = await fallback_provider.generate(prompt="Hi")
    assert result == "Response from Gemini"
    
    # Verify both were tried, with Gemini succeeding
    mock_groq.return_value.chat.completions.create.assert_called_once()
    mock_gemini.return_value.generate_content_async.assert_called_once()

@pytest.mark.asyncio
async def test_fallback_all_fail(mock_groq: MagicMock, mock_openai: MagicMock):
    mock_groq.return_value.chat.completions.create.side_effect = Exception("Groq down")
    mock_openai.return_value.chat.completions.create.side_effect = Exception("OpenAI down")
    
    configs = {
        "groq": {"api_key": "key-g"},
        "openai": {"api_key": "key-o"}
    }
    fallback_provider = FallbackLLMProvider(
        primary_name="groq",
        fallback_names=["openai"],
        custom_configs=configs
    )
    
    with pytest.raises(RuntimeError) as exc_info:
        await fallback_provider.generate(prompt="Hi")
        
    assert "All LLM providers failed" in str(exc_info.value)
    assert "Provider 'groq': Groq down" in str(exc_info.value)
    assert "Provider 'openai': OpenAI down" in str(exc_info.value)
