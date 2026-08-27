import pytest
from unittest.mock import patch, MagicMock
from app.schemas.generation import VisualDirection
from app.services.generation.visual_director import VisualDirector

@pytest.mark.asyncio
async def test_visual_director_valid_output():
    topic = "Why GrapheneOS is the future of mobile privacy"
    content = "Platforms locking out privacy focused operating systems like GrapheneOS is bad."
    
    mock_direction = VisualDirection(
        visual_type="editorial_photo",
        subject="modern Android smartphone representing a privacy focused mobile operating system",
        scene="smartphone isolated on a dark technical desk with subtle cybersecurity and privacy visual cues",
        concept="tension between user privacy and platform controlled distribution",
        composition="single dominant smartphone, strong negative space, cinematic three quarter perspective",
        lighting="subtle blue ambient lighting",
        style="premium technology editorial photography",
        negative_prompt="text, typography, quote cards"
    )

    with patch('litellm.acompletion') as mock_acompletion:
        # Mock response to avoid actual API call
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = mock_direction.model_dump_json()
        mock_acompletion.return_value = mock_response

        direction = await VisualDirector.generate_direction(topic, content)

        assert direction.visual_type == "editorial_photo"
        assert direction.subject == "modern Android smartphone representing a privacy focused mobile operating system"
        assert "text" in direction.negative_prompt

@pytest.mark.asyncio
async def test_visual_director_fallback_on_failure():
    with patch('litellm.acompletion', side_effect=Exception("API Down")):
        direction = await VisualDirector.generate_direction("topic", "content")
        
        # It should return the default direction
        assert direction.visual_type == "editorial_photo"
        assert "server room" in direction.subject
        assert "text" in direction.negative_prompt
