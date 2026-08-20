import pytest
from unittest.mock import patch, MagicMock
from app.services.generation.diagram_service import render_mermaid_to_png

@pytest.mark.asyncio
@patch('httpx.AsyncClient.post')
async def test_render_mermaid_to_png_success(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\x89PNG\r\n\x1a\nfake_png_data'
    mock_post.return_value = mock_response

    mermaid_code = """
    flowchart TD
      A[Start] --> B{Is it working?}
      B -- Yes --> C[Great!]
      B -- No --> D[Debug]
    """
    
    png_bytes = await render_mermaid_to_png(mermaid_code)
    
    assert png_bytes is not None
    assert isinstance(png_bytes, bytes)
    # PNGs start with the standard 8-byte signature
    assert png_bytes.startswith(b'\x89PNG\r\n\x1a\n')

@pytest.mark.asyncio
@patch('httpx.AsyncClient.post')
async def test_render_mermaid_to_png_invalid_syntax(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Syntax error"
    mock_post.return_value = mock_response
    # Kroki will likely return 400 for completely invalid syntax
    mermaid_code = "invalid mermaid syntax here 123 !@#"
    png_bytes = await render_mermaid_to_png(mermaid_code)
    assert png_bytes is None
