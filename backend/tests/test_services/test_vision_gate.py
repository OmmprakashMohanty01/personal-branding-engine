import pytest
from unittest.mock import patch, MagicMock
from app.services.generation.vision_gate import evaluate_image_alignment, _extract_bytes_from_data_uri

@pytest.fixture
def mock_genai_client():
    with patch('app.services.generation.vision_gate.genai.Client') as mock_client:
        yield mock_client

@pytest.mark.asyncio
async def test_evaluate_image_alignment_passing(mock_genai_client):
    # Setup mock response
    mock_instance = MagicMock()
    mock_genai_client.return_value = mock_instance
    
    mock_response = MagicMock()
    mock_response.text = '{"score": 8, "passed": true, "reason": "Good alignment"}'
    mock_instance.models.generate_content.return_value = mock_response
    
    # Test data URI
    data_uri = "data:image/jpeg;base64,iVBORw0KGgo="
    
    with patch.dict('os.environ', {'GEMINI_API_KEY': 'test_key'}):
        result = await evaluate_image_alignment("Test draft", data_uri)
        
    assert result['score'] == 8
    assert result['passed'] is True
    assert result['reason'] == "Good alignment"
    mock_instance.models.generate_content.assert_called_once()

@pytest.mark.asyncio
async def test_evaluate_image_alignment_failing(mock_genai_client):
    # Setup mock response
    mock_instance = MagicMock()
    mock_genai_client.return_value = mock_instance
    
    mock_response = MagicMock()
    mock_response.text = '{"score": 4, "passed": false, "reason": "Irrelevant image"}'
    mock_instance.models.generate_content.return_value = mock_response
    
    # Test URL
    url = "https://example.com/image.jpg"
    
    with patch('app.services.generation.vision_gate._fetch_bytes_from_url', return_value=b'testbytes'):
        with patch.dict('os.environ', {'GEMINI_API_KEY': 'test_key'}):
            result = await evaluate_image_alignment("Test draft", url)
            
    assert result['score'] == 4
    assert result['passed'] is False
    assert result['reason'] == "Irrelevant image"

@pytest.mark.asyncio
async def test_evaluate_image_alignment_no_api_key():
    with patch.dict('os.environ', {}, clear=True):
        result = await evaluate_image_alignment("Test draft", "data:image/png;base64,abc")
        
    # Should auto-pass when no key
    assert result['score'] == 10
    assert result['passed'] is True
    assert result['reason'] == "No API key found, validation skipped."

def test_extract_bytes_from_data_uri():
    uri = "data:image/png;base64,YWJj"
    b, mime = _extract_bytes_from_data_uri(uri)
    assert b == b'abc'
    assert mime == "image/png"
