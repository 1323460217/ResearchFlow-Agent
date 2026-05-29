# ResearchFlow-Agent

ResearchFlow-Agent is a multi-agent research assistant platform for academic research workflows. It helps with paper retrieval, literature analysis, knowledge-base question answering, research idea generation, and report generation.

## Features

- Multi-agent workflow powered by LangGraph
- RAG-based knowledge base retrieval
- Document upload, parsing, chunking, and indexing
- Paper retrieval and analysis tools
- Research report generation
- Vue-based frontend interface

## Tech Stack

- Backend: FastAPI, SQLAlchemy, Celery
- Agent: LangGraph, LangChain
- RAG: LlamaIndex, ChromaDB, BM25, reranking
- Memory: Redis
- Database: PostgreSQL
- Frontend: Vue 3, Pinia, Vite

## Project Structure

```text
backend/      Backend API, agents, RAG, tools, database models
frontend/     Vue frontend application
requirements.txt
