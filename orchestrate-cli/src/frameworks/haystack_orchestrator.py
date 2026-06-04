"""
Haystack Orchestrator - Search and retrieval orchestration with Haystack

Features:
- Document search and retrieval
- BM25 and vector search
- Pipeline-based workflows
- Document preprocessing
- Query optimization
"""

import asyncio
import os
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from haystack import Document, Pipeline
    from haystack.components.retrievers import BM25Retriever, SentenceTransformersRetriever
    from haystack.components.writers import DocumentWriter
    from haystack.components.preprocessors import DocumentCleaner, DocumentSplitter  # noqa: F401
    from haystack.components.rankers import TransformersRanker
    from haystack.document_stores import InMemoryDocumentStore, FAISSDocumentStore
    from haystack.nodes import TextConverter, PreProcessor  # noqa: F401
    from haystack.utils import fetch_archive_from_http
    HAYSTACK_AVAILABLE = True
except ImportError:
    HAYSTACK_AVAILABLE = False

from src.orchestrators.orchestrator_factory import BaseOrchestrator
from src.agents.haystack_agent import HaystackAgent

class HaystackOrchestrator(BaseOrchestrator):
    """Haystack orchestrator for search and retrieval"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.framework_name = 'haystack'
        
        if not HAYSTACK_AVAILABLE:
            raise ImportError("Haystack not available. Install with: pip install haystack-ai")
        
        self.document_stores: Dict[str, Any] = {}
        self.pipelines: Dict[str, Pipeline] = {}
        self.retrievers: Dict[str, Any] = {}
        self.retriever_configs = self._load_retriever_configs()
        
    def _load_retriever_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load retriever configurations"""
        return self.framework_config.get('retrievers', {})
    
    async def execute_task(self, task: str, agents: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a search task with Haystack"""
        logger.info(f"Executing search task with Haystack: {task}")
        
        if not agents:
            agents = ['bm25_retriever', 'vector_retriever', 'ranker']
        
        results = {}
        
        for agent_name in agents:
            try:
                if agent_name == 'bm25_retriever':
                    result = await self._bm25_search(task)
                elif agent_name == 'vector_retriever':
                    result = await self._vector_search(task)
                elif agent_name == 'ranker':
                    result = await self._ranked_search(task)
                else:
                    result = await self._execute_custom_agent(agent_name, task)
                
                results[agent_name] = result
                logger.info(f"Agent {agent_name} completed task")
                
            except Exception as e:
                logger.error(f"Agent {agent_name} failed: {e}")
                results[agent_name] = {'error': str(e)}
        
        return {
            'framework': 'haystack',
            'task': task,
            'agents': agents,
            'results': results,
            'timestamp': asyncio.get_event_loop().time()
        }
    
    async def _bm25_search(self, query: str) -> Dict[str, Any]:
        """Execute BM25 search"""
        if 'bm25' not in self.document_stores:
            self.document_stores['bm25'] = self._create_bm25_store()
        
        doc_store = self.document_stores['bm25']
        retriever = BM25Retriever(document_store=doc_store)
        
        documents = retriever.retrieve(query)
        
        return {
            'query': query,
            'retrieval_method': 'BM25',
            'retrieved_documents': len(documents),
            'documents': [
                {
                    'id': doc.id,
                    'text': doc.content,
                    'score': doc.score,
                    'meta': doc.meta
                }
                for doc in documents
            ]
        }
    
    async def _vector_search(self, query: str) -> Dict[str, Any]:
        """Execute vector search"""
        if 'vector' not in self.document_stores:
            self.document_stores['vector'] = self._create_vector_store()
        
        doc_store = self.document_stores['vector']
        retriever = SentenceTransformersRetriever(document_store=doc_store)
        
        documents = retriever.retrieve(query)
        
        return {
            'query': query,
            'retrieval_method': 'Vector',
            'retrieved_documents': len(documents),
            'documents': [
                {
                    'id': doc.id,
                    'text': doc.content,
                    'score': doc.score,
                    'meta': doc.meta
                }
                for doc in documents
            ]
        }
    
    async def _ranked_search(self, query: str) -> Dict[str, Any]:
        """Execute ranked search with ranking"""
        # Get documents from BM25 first
        bm25_result = await self._bm25_search(query)
        
        if not bm25_result['documents']:
            return {'query': query, 'message': 'No documents found for ranking'}
        
        # Create ranking pipeline
        pipeline = self._create_ranking_pipeline()
        
        # Add documents to pipeline
        documents = [Document.from_dict(doc) for doc in bm25_result['documents']]
        
        # Execute ranking
        result = pipeline.run(query=query, documents=documents)
        
        return {
            'query': query,
            'retrieval_method': 'Ranked',
            'ranked_documents': len(result.get('documents', [])),
            'documents': [
                {
                    'id': doc.id,
                    'text': doc.content,
                    'score': doc.score,
                    'meta': doc.meta
                }
                for doc in result.get('documents', [])
            ]
        }
    
    async def _execute_custom_agent(self, agent_name: str, task: str) -> Dict[str, Any]:
        """Execute custom Haystack agent"""
        agent = HaystackAgent(agent_name, self.framework_config)
        return await agent.execute(task)
    
    def _create_bm25_store(self) -> InMemoryDocumentStore:
        """Create BM25 document store"""
        doc_store = InMemoryDocumentStore()
        
        # Add sample documents
        sample_docs = [
            "Machine learning is a subset of artificial intelligence.",
            "Deep learning uses neural networks with multiple layers.",
            "Natural language processing helps computers understand text.",
            "Computer vision enables image recognition and analysis.",
            "Reinforcement learning learns through trial and error."
        ]
        
        documents = [Document(content=doc) for doc in sample_docs]
        doc_store.write_documents(documents)
        
        return doc_store
    
    def _create_vector_store(self) -> FAISSDocumentStore:
        """Create vector document store"""
        doc_store = FAISSDocumentStore(faiss_index_path_path="./faiss_index")
        
        # Add sample documents
        sample_docs = [
            "Artificial Intelligence enables machines to learn and adapt.",
            "Data science combines statistics and computer programming.",
            "Big data processing handles massive datasets efficiently.",
            "Cloud computing provides scalable computational resources.",
            "Cybersecurity protects digital systems and data."
        ]
        
        documents = [Document(content=doc) for doc in sample_docs]
        doc_store.write_documents(documents)
        
        return doc_store
    
    def _create_ranking_pipeline(self) -> Pipeline:
        """Create ranking pipeline"""
        pipeline = Pipeline()
        
        # Add ranker
        ranker = TransformersRanker(model="cross-encoder/ms-marco-MiniLM-L-6-v2")
        pipeline.add_component("ranker", ranker)
        
        return pipeline
    
    def configure(self) -> None:
        """Configure Haystack framework"""
        logger.info("Configuring Haystack framework")
        
        # Validate configuration
        if not self.validate_config():
            raise ValueError("Invalid Haystack configuration")
        
        # Create document stores
        for store_name, store_config in self.framework_config.get('document_stores', {}).items():
            if store_name not in self.document_stores:
                try:
                    if store_config.get('type') == 'faiss':
                        self.document_stores[store_name] = self._create_vector_store()
                    else:
                        self.document_stores[store_name] = self._create_bm25_store()
                except Exception as e:
                    logger.error(f"Failed to create document store {store_name}: {e}")
        
        # Create pipelines
        for pipeline_name, pipeline_config in self.framework_config.get('pipelines', {}).items():
            if pipeline_name not in self.pipelines:
                self.pipelines[pipeline_name] = self._create_pipeline(pipeline_config)
        
        # Load documents if specified
        self._load_documents()
        
        logger.info("Haystack configuration completed")
    
    def _create_pipeline(self, config: Dict[str, Any]) -> Pipeline:
        """Create a Haystack pipeline"""
        pipeline = Pipeline()
        
        # Add components based on configuration
        for component_name, component_config in config.get('components', {}).items():
            component_type = component_config.get('type')
            
            if component_type == 'retriever':
                if component_config.get('retriever_type') == 'bm25':
                    pipeline.add_component(component_name, BM25Retriever())
                elif component_config.get('retriever_type') == 'vector':
                    pipeline.add_component(component_name, SentenceTransformersRetriever())
            elif component_type == 'ranker':
                pipeline.add_component(component_name, TransformersRanker())
            elif component_type == 'writer':
                pipeline.add_component(component_name, DocumentWriter())
        
        return pipeline
    
    def _load_documents(self):
        """Load documents from configured sources"""
        document_sources = self.framework_config.get('document_sources', {})
        
        for source_name, source_config in document_sources.items():
            try:
                if source_config.get('type') == 'file':
                    self._load_documents_from_file(source_config)
                elif source_config.get('type') == 'url':
                    self._load_documents_from_url(source_config)
            except Exception as e:
                logger.error(f"Failed to load documents from {source_name}: {e}")
    
    def _load_documents_from_file(self, source_config: Dict[str, Any]):
        """Load documents from file"""
        file_path = source_config.get('path')
        if not file_path or not os.path.exists(file_path):
            logger.error(f"Document file not found: {file_path}")
            return
        
        # Simple text file loading
        with open(file_path, 'r') as f:
            content = f.read()
        
        doc = Document(content=content)
        
        # Add to appropriate document store
        store_name = source_config.get('document_store', 'bm25')
        if store_name in self.document_stores:
            self.document_stores[store_name].write_documents([doc])
    
    def _load_documents_from_url(self, source_config: Dict[str, Any]):
        """Load documents from URL"""
        url = source_config.get('url')
        if not url:
            logger.error("No URL provided for document source")
            return
        
        # Download and process documents
        fetch_archive_from_http(url, target_dir=f"./temp_data/{hash(url)}")
        
        # Note: This would need proper document processing
        logger.info(f"Downloaded documents from: {url}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get Haystack status"""
        status = super().get_status()
        
        # Count documents in stores
        document_counts = {}
        for store_name, doc_store in self.document_stores.items():
            try:
                doc_count = len(doc_store.get_documents())
                document_counts[store_name] = doc_count
            except Exception:
                document_counts[store_name] = 0
        
        status.update({
            'document_stores_count': len(self.document_stores),
            'pipelines_count': len(self.pipelines),
            'retrievers_count': len(self.retrievers),
            'document_counts': document_counts,
            'retrievers_configured': list(self.retriever_configs.keys())
        })
        
        return status
    
    def validate_config(self) -> bool:
        """Validate Haystack configuration"""
        required_keys = ['frameworks', 'frameworks.haystack']
        
        for key in required_keys:
            if not self._check_nested_key(self.config, key):
                logger.error(f"Missing required config key: {key}")
                return False
        
        # Validate retriever configurations
        retrievers = self.retriever_configs
        for retriever_name, retriever_config in retrievers.items():
            if 'type' not in retriever_config:
                logger.error(f"Missing type for retriever: {retriever_name}")
                return False
        
        return True
    
    def _check_nested_key(self, config: Dict[str, Any], key_path: str) -> bool:
        """Check if a nested key exists in config"""
        keys = key_path.split('.')
        current = config
        
        for key in keys:
            if key not in current:
                return False
            current = current[key]
        
        return True