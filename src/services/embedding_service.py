import ollama
import logging

logger = logging.getLogger("fable.embedding")

# Use nomic-embed-text:v1.5 as it's installed locally (768 dims)
OLLAMA_EMBED_MODEL = "nomic-embed-text:v1.5"

async def get_embedding(text: str) -> list[float]:
    """
    Generates a vector embedding for the given text using local Ollama.
    """
    try:
        response = ollama.embeddings(model=OLLAMA_EMBED_MODEL, prompt=text)
        return response['embedding']
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        # Note: If the model isn't pulled yet, you might need to run `ollama pull mxbai-embed-large`
        raise
