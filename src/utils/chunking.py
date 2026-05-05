import re

def chunk_text(text: str, max_chunk_size: int = 1000, overlap: int = 150) -> list[str]:
    """
    Chunks text into roughly `max_chunk_size` characters, overlapping by `overlap`.
    Tries to split on paragraphs or sentences to preserve semantic meaning.
    """
    # Split by double newline (paragraphs)
    paragraphs = re.split(r'\n\s*\n', text)
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        if len(current_chunk) + len(para) > max_chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Simple overlap: take the last `overlap` characters from the current chunk
            # Better to find a sentence boundary, but this works as a baseline.
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + " " + para
        else:
            current_chunk += ("\n\n" if current_chunk else "") + para
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks
