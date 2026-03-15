# Copilot Instructions

Guidelines for GitHub Copilot usage and code generation within the RAG Chatbot Assistant project.

## Code Generation Standards

### 1. Python Backend Code

**Style Guide:**
- Follow PEP 8 standards
- Use type hints for all functions
- Write docstrings for all classes and functions
- Maximum line length: 100 characters
- Use async/await for I/O operations

**Example Function:**
```python
async def retrieve_from_knowledge_base(
    query: str, 
    top_k: int = 5, 
    threshold: float = 0.7
) -> List[Document]:
    """
    Retrieve relevant documents from knowledge base.
    
    Args:
        query: User query string
        top_k: Number of top results to return
        threshold: Minimum relevance score
        
    Returns:
        List of retrieved Document objects
    """
    # Implementation
```

### 2. React/Vue Frontend Code

**Style Guide:**
- Use functional components with hooks
- Implement proper error boundaries
- Add loading and error states
- Use TypeScript for type safety
- Follow component naming conventions (PascalCase)

**Example Component:**
```jsx
interface ChatProps {
  onMessage: (message: string) => void;
  loading: boolean;
}

export const ChatInput: React.FC<ChatProps> = ({ onMessage, loading }) => {
  const [input, setInput] = useState('');
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim()) {
      onMessage(input);
      setInput('');
    }
  };
  
  return (/* JSX */);
};
```

## RAG-Specific Code Patterns

### Vector Store Operations
```python
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma

embeddings = OpenAIEmbeddings()
vectorstore = Chroma.from_documents(docs, embeddings)
results = vectorstore.similarity_search_with_score(query, k=5)
```

### LLM Chain Setup
```python
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI

llm = ChatOpenAI(model="gpt-4")
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=vectorstore.as_retriever(),
)
```

### API Endpoint Pattern
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None

@app.post("/api/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    # RAG pipeline logic
    pass
```

## Testing Requirements

### Backend Tests
```python
def test_retrieve_documents():
    """Test knowledge base retrieval"""
    
def test_rag_pipeline():
    """Test end-to-end RAG flow"""
    
def test_response_generation():
    """Test LLM response generation"""
```

### Frontend Tests
```jsx
describe('ChatInput', () => {
  it('should submit message on enter', () => {
    // Test logic
  });
});
```

## Common Patterns to Avoid

❌ Hardcoded API keys (use environment variables)
❌ Synchronous API calls in frontend (use async/await)
❌ Missing error handling
❌ Untyped variables
❌ No input validation
❌ Inefficient vector store queries

## Environment Variables

Create `.env` files with:
```bash
# Backend
OPENAI_API_KEY=sk-...
VECTOR_DB_PATH=./data/vectordb
DB_CONNECTION_STRING=postgresql://...
LOG_LEVEL=INFO

# Frontend
REACT_APP_API_URL=http://localhost:8000
REACT_APP_ENV=development
```

## Documentation Standards

- Add docstrings to all functions
- Use type hints
- Include usage examples
- Document configuration options
- Add architecture diagrams using Mermaid

**Example:**
```python
def calculate_similarity(doc1: str, doc2: str) -> float:
    """
    Calculate semantic similarity between two documents.
    
    Args:
        doc1: First document text
        doc2: Second document text
        
    Returns:
        Similarity score between 0 and 1
        
    Example:
        >>> score = calculate_similarity("hello", "hi")
        >>> print(score)
        0.85
    """
```

## Performance Considerations

- Batch embedding operations
- Cache frequently retrieved documents
- Use pagination for large result sets
- Implement connection pooling
- Monitor query latency

## Security Best Practices

- Sanitize user inputs
- Validate API requests
- Use CORS appropriately
- Implement rate limiting
- Encrypt sensitive data
- Use parameterized queries

## Commit Message Standards

```
feat: Add RAG pipeline for document retrieval
fix: Resolve embedding dimension mismatch
docs: Update API documentation
test: Add test coverage for retrieval module
```

---

**Version**: 1.0
**Last Updated**: March 2026
**Copilot Model**: Claude Haiku 4.5
