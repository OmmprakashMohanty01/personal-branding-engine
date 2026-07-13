import os
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

logger = logging.getLogger("branding_engine.llm")

class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM Providers."""
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        """Generate text based on prompt and parameters.
        
        Args:
            prompt: The user input prompt.
            system_instruction: Optional system instruction/persona constraints.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            
        Returns:
            The generated text response.
        """
        pass


class GroqProvider(BaseLLMProvider):
    """Groq API Provider implementation."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        
        if not self.api_key:
            raise ValueError("Groq API key is missing. Set GROQ_API_KEY environment variable.")
            
        from groq import AsyncGroq
        self.client = AsyncGroq(api_key=self.api_key)

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        logger.info(f"Sending request to Groq using model {self.model}")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API Provider implementation."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-3.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        
        if not self.api_key:
            raise ValueError("Gemini API key is missing. Set GEMINI_API_KEY environment variable.")
            
        from google import genai
        self.client = genai.Client(api_key=self.api_key)

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        logger.info(f"Sending request to Gemini using model {self.model_name}")
        
        stage_1_prompt = f"{system_instruction}\n\nUser Input/Topic: {prompt}" if system_instruction else prompt
        interaction = self.client.interactions.create(
            model=self.model_name,
            input=stage_1_prompt
        )
        return interaction.output_text


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API Provider implementation."""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        
        if not self.api_key:
            raise ValueError("OpenAI API key is missing. Set OPENAI_API_KEY environment variable.")
            
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=self.api_key)

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        logger.info(f"Sending request to OpenAI using model {self.model}")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens
        )
        return response.choices[0].message.content


class FallbackLLMProvider(BaseLLMProvider):
    """Orchestrator that implements fallback logic across multiple providers."""
    
    def __init__(
        self,
        primary_name: Optional[str] = None,
        fallback_names: Optional[List[str]] = None,
        custom_configs: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        """Initialize fallback orchestrator using environment configuration or explicit defaults.
        
        Args:
            primary_name: Override for the primary provider name.
            fallback_names: Override for the list of fallback provider names.
            custom_configs: Override settings for specific providers, e.g. models or API keys.
        """
        self.primary_name = primary_name or os.getenv("LLM_PRIMARY_PROVIDER", "groq").lower()
        
        fallbacks_env = os.getenv("LLM_FALLBACK_PROVIDERS", "gemini,openai")
        if fallback_names is None:
            self.fallback_names = [name.strip().lower() for name in fallbacks_env.split(",") if name.strip()]
        else:
            self.fallback_names = [name.lower() for name in fallback_names]
            
        self.custom_configs = custom_configs or {}
        self.providers: Dict[str, BaseLLMProvider] = {}
        
        # Instantiate primary and fallback providers lazily or at initialization
        self._initialize_providers()

    def _initialize_providers(self):
        all_requested = [self.primary_name] + self.fallback_names
        
        for name in all_requested:
            if name in self.providers:
                continue
                
            config = self.custom_configs.get(name, {})
            try:
                if name == "groq":
                    self.providers[name] = GroqProvider(
                        api_key=config.get("api_key"),
                        model=config.get("model", "llama-3.3-70b-versatile")
                    )
                elif name == "gemini":
                    self.providers[name] = GeminiProvider(
                        api_key=config.get("api_key"),
                        model=config.get("model", "gemini-3.5-flash")
                    )
                elif name == "openai":
                    self.providers[name] = OpenAIProvider(
                        api_key=config.get("api_key"),
                        model=config.get("model", "gpt-4o-mini")
                    )
                else:
                    logger.warning(f"Unknown provider configured: {name}")
            except Exception as e:
                logger.error(f"Failed to initialize provider '{name}': {e}. It will be unavailable.")

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000
    ) -> str:
        # Check order of attempts: primary first, then fallbacks
        order = [self.primary_name] + self.fallback_names
        
        errors = []
        for provider_name in order:
            provider = self.providers.get(provider_name)
            if not provider:
                # Try initializing on the fly if not initialized
                self._initialize_providers()
                provider = self.providers.get(provider_name)
                if not provider:
                    errors.append(f"Provider '{provider_name}' is not configured or failed initialization.")
                    continue
            
            try:
                result = await provider.generate(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                logger.info(f"Successfully generated response using provider: {provider_name}")
                return result
            except Exception as e:
                logger.warning(f"Provider '{provider_name}' failed during generation: {e}")
                errors.append(f"Provider '{provider_name}': {str(e)}")
                
        # If we got here, all providers failed
        error_msg = f"All LLM providers failed. Attempts: {'; '.join(errors)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
