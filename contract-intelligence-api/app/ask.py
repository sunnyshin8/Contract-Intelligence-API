from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List, Dict, Any
import os
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.schema import Document

from models import AskRequest, AskResponse, Citation
from webhook import trigger_webhook_event
from logging_config import get_logger, log_event
from utils import load_document

logger = get_logger("ask")

router = APIRouter(
    prefix="/ask",
    tags=["ask"],
    responses={404: {"description": "Not found"}},
)

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

document_chunks = {}
vector_stores = {}


def prepare_document(document_id: str) -> List[Dict[str, Any]]:
    """Prepare document for RAG by splitting into chunks with metadata."""
    if document_id in document_chunks:
        return document_chunks[document_id]
    
    doc_data = load_document(document_id)
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )
    
    chunks = []
    for page_num, text in doc_data["text_by_page"].items():
        page_chunks = text_splitter.create_documents(
            [text],
            metadatas=[{
                "document_id": document_id,
                "page": int(page_num),
                "start_char": 0,
                "end_char": len(text),
            }]
        )
        
        start_idx = 0
        for chunk in page_chunks:
            chunk_text = chunk.page_content
            chunk_start = text.find(chunk_text, start_idx)
            if chunk_start == -1:
                chunk_start = start_idx
            
            chunk_end = chunk_start + len(chunk_text)
            chunk.metadata["start_char"] = chunk_start
            chunk.metadata["end_char"] = chunk_end
            start_idx = chunk_end - CHUNK_OVERLAP
            
            chunks.append({
                "text": chunk_text,
                "metadata": chunk.metadata
            })
    
    document_chunks[document_id] = chunks
    return chunks


def get_vector_store(document_ids: List[str]) -> FAISS:
    """Get or create vector store for the specified documents."""
    store_key = "_".join(sorted(document_ids))
    
    if store_key in vector_stores:
        return vector_stores[store_key]
    
    all_chunks = []
    for doc_id in document_ids:
        doc_chunks = prepare_document(doc_id)
        all_chunks.extend(doc_chunks)

    if not all_chunks:
        raise ValueError(f"No valid chunks found for documents: {document_ids}")

    documents = [
        Document(
            page_content=chunk["text"],
            metadata=chunk["metadata"]
        )
        for chunk in all_chunks
    ]
    
    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/embedding-001",
        google_api_key=GEMINI_API_KEY
    )
    
    vector_store = FAISS.from_documents(documents, embeddings)
    
    vector_stores[store_key] = vector_store
    return vector_store


def format_citations(sources: List[Document]) -> List[Citation]:
    """Format sources as citations."""
    citations = []
    for source in sources:
        metadata = source.metadata
        citations.append(
            Citation(
                document_id=metadata.get("document_id", ""),
                page=metadata.get("page", 0),
                start_char=metadata.get("start_char", 0),
                end_char=metadata.get("end_char", 0),
                text=source.page_content[:200]
            )
        )
    return citations


@router.post("/", response_model=AskResponse)
async def ask_question(request: AskRequest, background_tasks: BackgroundTasks):
    """
    Answer a question about contracts using RAG.
    
    - Uses only the documents provided (or all if none specified)
    - Returns answer with citations (document_id + page/char ranges)
    """
    log_event("question_asked", {
        "question_length": len(request.question),
        "document_ids_provided": len(request.document_ids) if request.document_ids else 0
    }, "ask")
    
    if not GEMINI_API_KEY:
        logger.error("Gemini API key not configured")
        raise HTTPException(
            status_code=500,
            detail="Gemini API key not configured. Set the GEMINI_API_KEY environment variable."
        )
    
    try:
        document_ids = request.document_ids
        if not document_ids:
            import glob
            from pathlib import Path
            extracted_dir = Path(__file__).parent / "data" / "extracted"
            json_files = glob.glob(str(extracted_dir / "*.json"))
            document_ids = [Path(f).stem for f in json_files]
        
        if not document_ids:
            logger.warning("No documents found to search")
            log_event("question_failed_no_documents", {}, "ask")
            raise HTTPException(
                status_code=404,
                detail="No documents found to search"
            )
        
        log_event("documents_loaded_for_question", {
            "document_count": len(document_ids)
        }, "ask")
        
        vector_store = get_vector_store(document_ids)
        
        retriever = vector_store.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 5}
        )
        
        template = """You are a contract analysis expert. Use only the provided contract excerpts to answer the question. 
        If the answer cannot be found in the excerpts, say "I don't have enough information to answer this question based on the provided contracts."
        Provide a concise, factual answer with reference to specific contract language.
        
        Context excerpts from contracts:
        {context}
        
        Question: {question}
        
        Answer:"""
        
        prompt = PromptTemplate(
            template=template,
            input_variables=["context", "question"]
        )
        
        chain = RetrievalQA.from_chain_type(
            llm=ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=GEMINI_API_KEY,
                temperature=0
            ),
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": prompt}
        )
        
        result = chain.invoke({"query": request.question})
        
        answer = result.get("result", "")
        sources = result.get("source_documents", [])
        
        citations = format_citations(sources)
        
        log_event("question_answered", {
            "answer_length": len(answer),
            "citations_count": len(citations),
            "sources_count": len(sources)
        }, "ask")
        
        trigger_webhook_event("ask.complete", {"question": request.question, "answer": answer, "citations": [c.dict() for c in citations]}, background_tasks)

        return AskResponse(
            answer=answer,
            citations=citations
        )
    
    except FileNotFoundError as e:
        logger.error(f"File not found during question answering: {str(e)}")
        log_event("question_failed_file_not_found", {
            "error": str(e)
        }, "ask")
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        import traceback
        logger.error(f"Error during question answering: {str(e)}")
        logger.error(traceback.format_exc())
        
        log_event("question_failed", {
            "error": str(e)
        }, "ask")
        
        raise HTTPException(
            status_code=500,
            detail="An error occurred while processing your request."
        )
