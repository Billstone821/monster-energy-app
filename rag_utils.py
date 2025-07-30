import os
from bs4 import BeautifulSoup
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from dotenv import load_dotenv

# Load environment variables within rag_utils.py as well,
# in case it's run or imported in a context where app.py hasn't loaded them yet.
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("[ERROR] GEMINI_API_KEY is NOT loaded in rag_utils.py environment.")
    raise ValueError("GEMINI_API_KEY is missing from .env in rag_utils.py context. Please set it.")
else:
    print("[INFO] GEMINI_API_KEY successfully loaded in rag_utils.py.")

# Initialize embeddings model (make sure GEMINI_API_KEY is set in your .env)
embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key=GEMINI_API_KEY)

def extract_text_from_file(file_path):
    """
    Extracts text content from an HTML file.
    Args:
        file_path (str): The path to the HTML file.
    Returns:
        str: The extracted text content.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
            for script_or_style in soup(['script', 'style']):
                script_or_style.extract()
            text = soup.get_text(separator=' ', strip=True)
            return text
    except FileNotFoundError:
        print(f"[ERROR] File not found: {file_path}")
        return None
    except Exception as e:
        print(f"[ERROR] Error extracting text from {file_path}: {e}")
        return None

def load_webpage_content_for_rag(file_path):
    """
    Loads text content from a webpage file, splits it into chunks,
    and creates a FAISS vector store for RAG.
    Args:
        file_path (str): The path to the webpage (HTML) file.
    Returns:
        FAISS: A FAISS vector store containing the indexed document chunks, or None if loading fails.
    """
    print(f"[INFO] Attempting to load content from {file_path}")
    text_content = extract_text_from_file(file_path)

    if not text_content:
        print(f"[ERROR] No text content extracted from {file_path}. Cannot create RAG retriever.")
        return None

    documents = [Document(page_content=text_content, metadata={"source": file_path})]

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )
    chunks = text_splitter.split_documents(documents)
    print(f"[INFO] Split content into {len(chunks)} chunks.")

    try:
        vector_store = FAISS.from_documents(chunks, embeddings)
        print("[INFO] FAISS vector store created successfully.")
        return vector_store
    except Exception as e:
        print(f"[ERROR] Error creating FAISS vector store: {e}")
        return None

def retrieve_relevant_chunks(vector_store, query, k=3):
    """
    Retrieves the most relevant document chunks from the vector store based on a query.
    Args:
        vector_store (FAISS): The FAISS vector store.
        query (str): The user's query.
        k (int): The number of top relevant chunks to retrieve.
    Returns:
        list: A list of relevant Document chunks.
    """
    if vector_store is None:
        print("[WARNING] Vector store is not initialized. Cannot retrieve chunks.")
        return []
    try:
        relevant_docs = vector_store.similarity_search(query, k=k)
        return relevant_docs
    except Exception as e:
        print(f"[ERROR] Error retrieving relevant chunks: {e}")
        return []

if __name__ == '__main__':
    print("--- Testing rag_utils.py ---")
    if not os.path.exists('index.html'):
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write("""
            <!DOCTYPE html>
            <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Welcome to Monster Energy Campaign</h1>
                <p>This program allows you to earn $500.00 weekly for 12 weeks.</p>
                <p>You can use your Car, Truck, Van, Motorcycle, or Boat.</p>
                <p>No application fee is required.</p>
                <p>Contact us at info@monsterenergy.com.</p>
            </body>
            </html>
            """)
        print("[INFO] Created a dummy index.html for testing.")

    test_retriever = load_webpage_content_for_rag('index.html')

    if test_retriever:
        print("\n--- Performing a test retrieval ---")
        test_query = "How much can I earn and for how long?"
        retrieved_chunks = retrieve_relevant_chunks(test_retriever, test_query)

        if retrieved_chunks:
            print(f"Query: '{test_query}'")
            print("Retrieved Chunks:")
            for i, chunk in enumerate(retrieved_chunks):
                print(f"--- Chunk {i+1} ---")
                print(chunk.page_content)
                print(f"Source: {chunk.metadata.get('source', 'N/A')}")
        else:
            print("No chunks retrieved for the test query.")
    else:
        print("Failed to initialize test retriever.")
    print("--- End of rag_utils.py testing ---")
