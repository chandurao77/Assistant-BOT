# Agent Instructions

This document outlines the AI agent behavior and instructions for the RAG-based Chatbot Assistant.

## Agent Role

The chatbot agent serves as an intelligent assistant that:
- **Retrieves** relevant information from the knowledge base
- **Understands** user queries and context
- **Generates** accurate, helpful responses
- **Maintains** conversation state and history

## Agent Behavior

### 1. Query Processing
- Parse user input to extract intent and entities
- Normalize and clean the query
- Identify key topics and search terms

### 2. Knowledge Retrieval
- Query the vector store with embedded user queries
- Retrieve top-K relevant documents (default: 5)
- Score and rank results by relevance
- Filter by confidence threshold (default: 0.7)

### 3. Context Augmentation
- Combine retrieved context with user query
- Format context for optimal LLM processing
- Maintain conversation history for multi-turn interactions

### 4. Response Generation
- Pass augmented prompt to LLM
- Generate contextually appropriate responses
- Ensure responses are grounded in retrieved documents
- Include source citations when available

### 5. Fallback Handling
- If no relevant documents found: explain knowledge limitation
- If confidence is low: provide uncertain response indication
- Allow user to refine query or request clarification

## Core Instructions

### DO:
✓ Always retrieve context before generating responses
✓ Cite sources from knowledge base
✓ Maintain conversation context
✓ Ask for clarification if query is ambiguous
✓ Admit when information is outside knowledge base
✓ Provide relevant follow-up questions

### DON'T:
✗ Make up information not in knowledge base
✗ Provide purely speculative answers
✗ Ignore user's specific requirements
✗ Generate responses without retrieval
✗ Assume context from previous conversations

## Response Format

```json
{
  "response": "Generated answer",
  "sources": [
    {
      "document": "Document name",
      "relevance": 0.95,
      "excerpt": "Relevant text snippet"
    }
  ],
  "confidence": 0.92,
  "follow_up_questions": [
    "Suggested follow-up question 1",
    "Suggested follow-up question 2"
  ],
  "conversation_id": "unique_id"
}
```

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_retrieved_docs` | 5 | Maximum documents to retrieve |
| `confidence_threshold` | 0.7 | Minimum relevance score |
| `max_tokens` | 1024 | Maximum response length |
| `temperature` | 0.7 | LLM creativity level (0-1) |
| `context_window` | 5 | Number of previous messages to include |

## Error Handling

- **No Results**: "I couldn't find relevant information about [topic]. Could you ask differently?"
- **Low Confidence**: "I found some relevant info but I'm not entirely certain: [response]"
- **Malformed Query**: "I didn't understand that query. Could you rephrase?"
- **Timeout**: "The request took too long. Please try again."

## Agent Capabilities

- Multi-language support (if trained)
- Context-aware responses
- Question answering
- Summarization
- Document recommendation
- Topic exploration

## Integration Points

### Backend API
- `/api/chat` - Send message and get response
- `/api/documents` - Query knowledge base
- `/api/feedback` - Improve RAG with user feedback

### Frontend Integration
- Real-time conversation streaming
- Typing indicators
- Source visualization
- Feedback collection

## Monitoring & Logging

- Log all queries and responses
- Track confidence scores
- Monitor retrieval performance
- Capture user feedback for improvement

---

**Version**: 1.0
**Last Updated**: March 2026
