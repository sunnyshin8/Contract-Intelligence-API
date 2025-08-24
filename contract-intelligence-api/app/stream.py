from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
import asyncio
import json
import os
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import FAISS
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler

from models import AskRequest
from ask import get_vector_store, format_citations
from logging_config import get_logger, log_event

logger = get_logger("stream")

router = APIRouter(
    prefix="/ask",
    tags=["ask"],
    responses={404: {"description": "Not found"}},
)

class StreamingCallbackHandler(StreamingStdOutCallbackHandler):
    def __init__(self):
        super().__init__()
        self.tokens = []
        
    def on_llm_new_token(self, token: str, **kwargs):
        self.tokens.append(token)
        
    def get_tokens(self):
        return self.tokens


@router.post("/stream")
async def stream_answer(request: AskRequest):
    """
    Stream answer tokens for a question using SSE.
    
    - Returns tokens one by one
    - Uses the same RAG approach as the non-streaming endpoint
    """
    log_event("stream_question_started", {
        "question_length": len(request.question),
        "document_ids_provided": len(request.document_ids) if request.document_ids else 0
    }, "stream")
    
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    
    if not GEMINI_API_KEY:
        logger.error("Gemini API key not configured for streaming")
        raise HTTPException(
            status_code=500,
            detail="Gemini API key not configured. Set the GEMINI_API_KEY environment variable."
        )
    
    async def event_generator():
        try:
            document_ids = request.document_ids
            if not document_ids:
                import glob
                from pathlib import Path
                extracted_dir = Path(__file__).parent / "data" / "extracted"
                json_files = glob.glob(str(extracted_dir / "*.json"))
                document_ids = [Path(f).stem for f in json_files]
            
            if not document_ids:
                logger.warning("No documents found for streaming search")
                yield {"event": "error", "data": json.dumps({"detail": "No documents found to search"})}
                return
            
            log_event("stream_documents_loaded", {
                "document_count": len(document_ids)
            }, "stream")
            
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
            
            streaming_handler = StreamingCallbackHandler()
            
            chain = RetrievalQA.from_chain_type(
                llm=ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash",
                    google_api_key=GEMINI_API_KEY,
                    temperature=0,
                    streaming=True,
                    callbacks=[streaming_handler]
                ),
                chain_type="stuff",
                retriever=retriever,
                return_source_documents=True,
                chain_type_kwargs={"prompt": prompt}
            )
            
            task = asyncio.create_task(
                chain.invoke({"query": request.question})
            )
            
            citations_sent = False
            
            last_token_idx = 0
            while not task.done():
                await asyncio.sleep(0.1)
                current_tokens = streaming_handler.tokens
                
                new_tokens = current_tokens[last_token_idx:]
                for token in new_tokens:
                    yield {"event": "token", "data": token}
                
                last_token_idx = len(current_tokens)
            
            result = await task
            current_tokens = streaming_handler.tokens
            new_tokens = current_tokens[last_token_idx:]
            for token in new_tokens:
                yield {"event": "token", "data": token}
            
            sources = result.get("source_documents", [])
            citations = format_citations(sources)
            yield {"event": "citations", "data": json.dumps([citation.dict() for citation in citations])}
            
            log_event("stream_question_completed", {
                "tokens_streamed": len(streaming_handler.tokens),
                "citations_count": len(citations)
            }, "stream")
            
            yield {"event": "done", "data": ""}
            
        except Exception as e:
            logger.error(f"Error during streaming: {str(e)}")
            log_event("stream_question_failed", {
                "error": str(e)
            }, "stream")
            yield {"event": "error", "data": json.dumps({"detail": str(e)})}
    
    return EventSourceResponse(event_generator())
