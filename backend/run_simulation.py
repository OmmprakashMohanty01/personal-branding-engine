import asyncio
from unittest.mock import AsyncMock, patch
from app.database import AsyncSessionLocal, engine, Base
from app.services.generation.pipeline import ContentGenerationPipeline
from app.services.generation.context import PipelineContext
from app.models.content import Persona

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        persona = Persona(
            name="Simulated Author",
            tone_description="Gritty engineering voice",
            vocabulary_rules="No corporate speak",
            formatting_preferences="No dashes",
            is_default=True,
        )
        db.add(persona)
        await db.commit()

        pipeline = ContentGenerationPipeline()
        topic = "Transitioning from RabbitMQ to Kafka for high-throughput message brokering"
        
        # We will capture the prompts sent to the LLM
        captured_prompts = []
        
        async def mock_call_llm(prompt_text, stage_name):
            captured_prompts.append((stage_name, prompt_text))
            if stage_name == "STAGE1":
                return "Man, I just spent two hours tracing dropped messages in RabbitMQ. We pushed a huge spike in queue traffic and it immediately bottlenecked. The disk I/O was completely pegged and consumers were falling behind. I ended up just tearing it out and dropping Kafka in because it handles append-only sequential writes so much better. I really hate how fragile AMQP can be under load."
            else:
                return "I just spent two hours tracing dropped messages. We pushed a huge spike in queue traffic and it immediately bottlenecked.\n\nThe disk I/O was completely pegged and consumers were falling behind.\n\nI ended up tearing it out and dropping Kafka in because it handles append-only sequential writes so much better.\n\nHas anyone else lost their sanity to AMQP under load?"

        with patch.object(pipeline, 'run'):
            # actually we need to patch the inner `call_llm` function, which is nested! 
            # Alternatively, we can just patch `execute_with_retry`
            pass

        # Let's just import the prompt builders and show what they output.
        print(f"Simulating prompt generation for topic: {topic}\n")
        
        from app.services.generation.prompt_builder import PromptBuilder
        builder = PromptBuilder()
        system_prompt = await builder.build_system_prompt(persona, topic, db)
        user_prompt = builder.build_user_prompt(topic, None)
        
        from app.services.generation.prompts.stage1_log import get_raw_log_prompt
        from app.services.generation.prompts.stage2_compiler import get_compiler_prompt
        
        context_string = f"{system_prompt}\n\nAdditional Input: {user_prompt}"
        stage1_prompt = get_raw_log_prompt(topic, context_string)
        
        print("=== STAGE 1 PROMPT (Sent to LLM) ===")
        print(stage1_prompt)
        print("\n\n")
        
        # Simulated raw log
        raw_log = "Man, I just spent two hours tracing dropped messages in RabbitMQ. We pushed a huge spike in queue traffic and it immediately bottlenecked. The disk I/O was completely pegged and consumers were falling behind. I ended up just tearing it out and dropping Kafka in because it handles append-only sequential writes so much better. I really hate how fragile AMQP can be under load."
        
        stage2_prompt = get_compiler_prompt(raw_log)
        
        print("=== STAGE 2 PROMPT (Sent to LLM) ===")
        print(stage2_prompt)
        print("\n\n")

if __name__ == "__main__":
    asyncio.run(main())
