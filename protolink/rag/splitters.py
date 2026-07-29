"""Built-in document splitters with stable chunk identifiers."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import Chunk, Document


class RecursiveCharacterSplitter:
    """Split text along natural boundaries before falling back to characters.

    The splitter prefers paragraphs, then lines, sentences, words, and finally
    hard character boundaries. Adjacent chunks overlap by ``chunk_overlap``
    characters so facts near a boundary remain retrievable with their context.

    Args:
        chunk_size: Maximum number of characters in one chunk.
        chunk_overlap: Number of trailing characters reused by the next chunk.
        separators: Ordered boundary strings from strongest to weakest.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        *,
        separators: Sequence[str] = ("\n\n", "\n", ". ", " ", ""),
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if not separators:
            raise ValueError("separators cannot be empty")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = tuple(separators)

    def split(self, documents: Iterable[Document]) -> list[Chunk]:
        """Split documents while retaining source and metadata."""
        chunks: list[Chunk] = []
        for document in documents:
            pieces = self.split_text(document.text)
            search_start = 0
            for index, text in enumerate(pieces):
                start = document.text.find(text, max(0, search_start - self.chunk_overlap))
                if start < 0:
                    start = search_start
                end = start + len(text)
                metadata = {
                    **document.metadata,
                    "chunk_index": index,
                    "start_index": start,
                    "end_index": end,
                    "media_type": document.media_type,
                }
                chunks.append(
                    Chunk(
                        text=text,
                        document_id=str(document.id),
                        index=index,
                        source=document.source,
                        metadata=metadata,
                    )
                )
                search_start = max(end, search_start)
        return chunks

    def split_text(self, text: str) -> list[str]:
        """Split one text value into bounded, overlapping passages."""
        stripped = text.strip()
        if not stripped:
            return []
        chunks: list[str] = []
        start = 0
        text_length = len(stripped)
        while start < text_length:
            hard_end = min(start + self.chunk_size, text_length)
            end = hard_end
            if hard_end < text_length:
                # Prefer a natural boundary in the latter half of the window.
                # Requiring it to be beyond the overlap also guarantees that
                # the cursor advances on the next iteration.
                earliest_break = start + max(
                    self.chunk_size // 2,
                    self.chunk_overlap + 1,
                )
                for separator in self.separators:
                    if not separator:
                        continue
                    position = stripped.rfind(separator, earliest_break, hard_end)
                    if position >= 0:
                        end = position + len(separator)
                        break

            chunk = stripped[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= text_length:
                break
            start = max(end - self.chunk_overlap, start + 1)
        return chunks
