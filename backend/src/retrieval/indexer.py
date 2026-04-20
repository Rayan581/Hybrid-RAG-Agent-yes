import os
import logging
from typing import List
from chromadb import PersistentClient
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Configuration
DOCS_DIR = os.getenv("DOCS_DIR", "/app/dataset")
CHROMA_PATH = os.getenv("CHROMA_PATH", "/app/chroma_db")

# Local fallback for development on host
if not os.path.exists(DOCS_DIR):
    # Looking for dataset/ in project root
    DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "dataset"))
if not os.path.exists(CHROMA_PATH):
    # Looking for chroma_db/ in project root
    CHROMA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "chroma_db"))

COLLECTION_NAME = "daraz_kb"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
CHUNK_SIZE = 512  # in characters (approximate to tokens for this model)

CHUNK_OVERLAP = 50

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

class Indexer:
    def __init__(self):
        self.client = PersistentClient(path=CHROMA_PATH)
        self.model = SentenceTransformer(EMBED_MODEL_NAME)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )

    def run(self):
        """Processes all documents in the docs directory and updates the vector store."""
        if not os.path.exists(DOCS_DIR):
            logger.error(f"Documents directory not found: {DOCS_DIR}")
            return

        # Initialize or get collection
        collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        files = [f for f in os.listdir(DOCS_DIR) if f.endswith(".txt")]
        logger.info(f"Found {len(files)} documents to index.")

        total_chunks = 0
        for filename in files:
            file_path = os.path.join(DOCS_DIR, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()

                chunks = self.text_splitter.split_text(content)
                ids = [f"{filename}_{i}" for i in range(len(chunks))]
                
                # Metadata to track source
                metadatas = [{"source": filename, "chunk": i} for i in range(len(chunks))]
                
                # Embed and Add to Chroma
                # Note: Chroma can handle embedding with its own functions, 
                # but we use SentenceTransformer explicitly as per requirement.
                embeddings = self.model.encode(chunks).tolist()
                
                collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas
                )
                
                total_chunks += len(chunks)
                logger.info(f"Indexed {filename}: {len(chunks)} chunks.")
            
            except Exception as e:
                logger.error(f"Failed to index {filename}: {e}")

        logger.info(f"Indexing complete. Total chunks in collection '{COLLECTION_NAME}': {total_chunks}")

if __name__ == "__main__":
    indexer = Indexer()
    indexer.run()