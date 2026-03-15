# RAG-Based Chatbot Assistant

A Retrieval-Augmented Generation (RAG) chatbot application that combines a knowledge base with AI capabilities to provide intelligent, context-aware responses.

## Overview

This chatbot leverages RAG technology to:
- Retrieve relevant information from a knowledge base
- Augment prompts with retrieved context
- Generate accurate, knowledge-based responses
- Maintain conversation context and history

## Project Structure

```
Assistant Bot/
├── backend/          # FastAPI service and configuration
│   ├── app.py        # Compatibility launcher for `python app.py`
│   ├── main.py       # API routes
│   ├── config.py     # Settings loader
│   └── requirements.txt
├── frontend/         # Vite + React client
│   ├── index.html
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── Agent.md          # Chatbot behavior notes
└── README.md
```

## Key Features

- **Knowledge Base Integration**: Query and retrieve relevant information
- **RAG Pipeline**: Augment user queries with contextual knowledge
- **Chat Interface**: User-friendly conversation UI
- **API Architecture**: RESTful backend for easy integration

## Getting Started

### Prerequisites
- Python 3.9+ (Backend)
- Node.js 14+ (Frontend)
- SQLite/PostgreSQL (Database)

### Backend Setup
```bash
cd backend
pip install -r requirements.txt
python app.py
```

### Frontend Setup
```bash
cd frontend
npm install
npm start
```

## Usage

1. User asks a question through the chat interface
2. Query is sent to the backend RAG pipeline
3. System retrieves relevant documents from knowledge base
4. Retrieved context augments the AI prompt
5. Response is generated and sent to user

## Technology Stack

- **Backend**: Python, FastAPI/Flask, LangChain, ChromaDB/Pinecone
- **Frontend**: React/Vue, Axios, TailwindCSS
- **LLM**: OpenAI/Hugging Face
- **Vector Store**: ChromaDB/Milvus/Pinecone
- **Database**: PostgreSQL/SQLite

## Architecture

```
┌─────────────────┐
│   User Input    │
└────────┬────────┘
         │
    ┌────▼────┐
    │Frontend  │
    └────┬────┘
         │
    ┌────▼──────────────┐
    │  Backend RAG API  │
    └────┬──────────────┘
         │
    ┌────┴─────────────────┐
    │                      │
┌───▼────────┐   ┌────────▼──┐
│ Knowledge  │   │ LLM Model  │
│ Base/VectorStore          │
└────────────┘   └────────────┘
    │                │
    └────┬───────────┘
         │
    ┌────▼─────────┐
    │ Generated    │
    │ Response     │
    └──────────────┘
```

## Configuration

See `copilot-instructions.md` for Copilot-specific configurations and `Agent.md` for agent setup.

## Contributing

Follow the development guidelines in the respective backend and frontend README files.

## License

MIT License

---

For more details, see individual component documentation.
