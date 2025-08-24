# Contract Intelligence API

A FastAPI-based service for intelligent contract processing that provides PDF ingestion, field extraction, question answering with RAG (Retrieval Augmented Generation), and contract auditing capabilities.

## Features

- **PDF Ingestion**: Upload and process contract PDFs
- **Field Extraction**: Extract structured data using LLM and fallback regex
- **Q&A with RAG**: Ask questions about contracts with citations
- **Streaming Responses**: Real-time streaming for long queries
- **Contract Auditing**: Identify risky clauses and compliance issues
- **Webhook Support**: Event notifications for integrations
- **Metrics & Monitoring**: Health checks and performance metrics

## Quick Start

### Prerequisites

- Python 3.8+
- Docker & Docker Compose (optional)
- Google Gemini API key

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd contract-intelligence-api
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run the application:
```bash
fastapi dev app/main.py
```

The API will be available at `http://localhost:8000`

## Environment Variables

Create a `.env` file with the following variables:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Optional
UPLOAD_DIR=./data/uploads
EXTRACTED_DIR=./data/extracted
VECTOR_DB_DIR=./data/vectordb
LOG_LEVEL=INFO
```

## API Endpoints

### Health Check
```bash
curl http://localhost:8000/health
```

### Document Ingestion
```bash
# Upload single PDF
curl -X POST "http://localhost:8000/ingest/" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@contract.pdf"

# Batch upload
curl -X POST "http://localhost:8000/ingest/batch" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@contract1.pdf" \
  -F "files=@contract2.pdf"
```

### Field Extraction
```bash
curl -X POST "http://localhost:8000/extract/" \
  -H "Content-Type: application/json" \
  -d '{"document_id": "doc123"}'
```

### Question Answering
```bash
# Standard Q&A
curl -X POST "http://localhost:8000/ask/" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the liability cap in this contract?",
    "document_ids": ["doc123"]
  }'

# Streaming Q&A
curl -X POST "http://localhost:8000/ask/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Summarize the key terms",
    "document_ids": ["doc123"]
  }'
```

### Contract Auditing
```bash
curl -X POST "http://localhost:8000/audit/" \
  -H "Content-Type: application/json" \
  -d '{"document_id": "doc123"}'
```

### Webhook Configuration
```bash
# Configure webhook
curl -X POST "http://localhost:8000/webhook/configure" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-webhook-endpoint.com",
    "events": ["extract.complete", "audit.complete"],
    "secret": "your-webhook-secret"
  }'
```

## Docker Deployment

### Using Docker Compose (Recommended)

```bash
# Build and start all services
docker-compose up --build

# Run in background
docker-compose up -d

# View logs
docker-compose logs -f api
```

### Using Docker directly

```bash
# Build image
docker build -t contract-intelligence-api .

# Run container
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -v $(pwd)/data:/app/data \
  contract-intelligence-api
```

## Architecture

The system follows a microservices-inspired modular architecture:

- **FastAPI**: Web framework for REST API
- **LangChain**: LLM orchestration and RAG pipeline
- **FAISS**: Vector database for document similarity search
- **Google Gemini**: Primary LLM for text generation and analysis
- **PyPDF2**: PDF text extraction
- **Background Tasks**: Asynchronous webhook processing

## Trade-offs & Design Decisions

### LLM Choice: Google Gemini vs OpenAI
- **Chosen**: Google Gemini 2.5 Flash
- **Rationale**: Better cost-performance ratio, faster inference, good multilingual support
- **Trade-off**: Slightly less capable than GPT-4 for complex reasoning tasks

### Vector Database: FAISS vs Pinecone/Weaviate
- **Chosen**: FAISS (local)
- **Rationale**: No external dependencies, faster for small-medium datasets, cost-effective
- **Trade-off**: Limited scalability, no managed infrastructure

### Chunking Strategy: Fixed vs Semantic
- **Chosen**: Fixed-size chunks (1000 chars, 200 overlap)
- **Rationale**: Predictable performance, simpler implementation
- **Trade-off**: May split related content, not optimized for document structure

### Extraction Approach: LLM-first with Regex Fallback
- **Chosen**: Primary LLM extraction with regex backup
- **Rationale**: Higher accuracy for complex documents, reliability through fallbacks
- **Trade-off**: Higher latency and cost compared to pure regex

### Deployment: Stateful vs Stateless
- **Chosen**: Stateful with local file storage
- **Rationale**: Simpler deployment, faster document access
- **Trade-off**: Horizontal scaling challenges, no built-in redundancy

## Security Considerations

- API keys stored in environment variables
- File uploads validated for type and size
- No authentication implemented (add OAuth2/JWT for production)
- Local file storage (consider encrypted storage for sensitive data)
- Input sanitization for LLM prompts

## Development

### Running Tests
```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/

# Run with coverage
pytest tests/ --cov=app
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes and add tests
4. Run tests and ensure they pass
5. Submit a pull request

## License

MIT License - see LICENSE file for details
