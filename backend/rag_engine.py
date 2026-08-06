# rag_engine.py
# RAG pipeline: PDF parsing, large-chunk splitting, local embedding, FAISS indexing.
# Uses tenacity retry on the embedding step for resilience.

import fitz
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

logger = logging.getLogger(__name__)


def parse_pdf(uploaded_file) -> str:
    pdf_bytes = uploaded_file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()
    return full_text.strip()


# Local embedding initialisation — happens once, no API call
_embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=15),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def _build_index(documents: list) -> FAISS:
    """Embed and index documents with exponential-backoff retry."""
    return FAISS.from_documents(documents, _embeddings)


def build_vector_store(resume_text: str) -> FAISS:
    """
    Split resume into large chunks (minimises API calls), then embed and index.
    The tenacity decorator handles transient failures gracefully.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=2500,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    chunks = splitter.split_text(resume_text)

    documents = [
        Document(page_content=chunk, metadata={"source": "resume", "chunk_id": i})
        for i, chunk in enumerate(chunks)
    ]

    logger.info("Indexing %d chunks via FAISS", len(documents))
    return _build_index(documents)


def retrieve_relevant_chunks(vector_store: FAISS, query: str, k: int = 5) -> str:
    retriever = vector_store.as_retriever(search_kwargs={"k": k})
    docs = retriever.invoke(query)
    return "\n\n".join([doc.page_content for doc in docs])
