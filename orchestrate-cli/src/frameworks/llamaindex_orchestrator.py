"""
LlamaIndex Orchestrator - RAG and document processing with LlamaIndex

Features:
- Document indexing and retrieval
- Vector store integration
- Query engines
- Knowledge graphs
- Multi-modal document processing
"""

import asyncio
import os
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
    from llama_index.core.query_engine import RetrieverQueryEngine
    from llama_index.core.retrievers import VectorIndexRetriever
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.storage import StorageContext
    from llama_index.vector_stores.qdrant import QdrantVectorStore
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False

from src.orchestrators.orchestrator_factory import BaseOrchestrator
from src.agents.llamaindex_agent import LlamaIndexAgent

class LlamaIndexOrchestrator(BaseOrchestrator):
    """LlamaIndex orchestrator for RAG and document processing"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.framework_name = 'llamaindex'

        if not LLAMAINDEX_AVAILABLE:
            raise ImportError("LlamaIndex not available. Install with: pip install llama-index")

        self.indexes: Dict[str, VectorStoreIndex] = {}
        self.query_engines: Dict[str, RetrieverQueryEngine] = {}
        self.document_stores: Dict[str, str] = {}
        self.storage_configs = self._load_storage_configs()

    def _load_storage_configs(self) -> Dict[str, Dict[str, Any]]:
        """Load storage configurations"""
        return self.framework_config.get('storage', {})

    async def execute_task(self, task: str, agents: Optional[List[str]] = None) -> Dict[str, Any]:
        """Execute a RAG task with LlamaIndex"""
        logger.info(f"Executing RAG task with LlamaIndex: {task}")

        if not agents:
            agents = ['retrieval_agent', 'query_agent']

        results = {}

        for agent_name in agents:
            try:
                if agent_name == 'retrieval_agent':
                    result = await self._retrieve_documents(task)
                elif agent_name == 'query_agent':
                    result = await self._query_documents(task)
                else:
                    result = await self._execute_custom_agent(agent_name, task)

                results[agent_name] = result
                logger.info(f"Agent {agent_name} completed task")

            except Exception as e:
                logger.error(f"Agent {agent_name} failed: {e}")
                results[agent_name] = {'error': str(e)}

        return {
            'framework': 'llamaindex',
            'task': task,
            'agents': agents,
            'results': results,
            'timestamp': asyncio.get_event_loop().time()
        }

    async def _retrieve_documents(self, query: str) -> Dict[str, Any]:
        """Retrieve relevant documents"""
        # Use default index or create one
        if 'default' not in self.indexes:
            self.indexes['default'] = await self._create_index('default')

        index = self.indexes['default']
        retriever = VectorIndexRetriever(index=index, similarity_top_k=3)

        nodes = retriever.retrieve(query)

        return {
            'query': query,
            'retrieved_nodes': len(nodes),
            'nodes': [
                {
                    'text': node.text,
                    'score': node.score,
                    'metadata': node.metadata
                }
                for node in nodes
            ]
        }

    async def _query_documents(self, query: str) -> Dict[str, Any]:
        """Query documents using RAG"""
        if 'default' not in self.query_engines:
            if 'default' not in self.indexes:
                self.indexes['default'] = await self._create_index('default')

            index = self.indexes['default']
            query_engine = RetrieverQueryEngine.from_args(index)
            self.query_engines['default'] = query_engine

        query_engine = self.query_engines['default']
        response = query_engine.query(query)

        return {
            'query': query,
            'response': str(response),
            'sources': [node.node for node in response.source_nodes]
        }

    async def _execute_custom_agent(self, agent_name: str, task: str) -> Dict[str, Any]:
        """Execute custom LlamaIndex agent"""
        agent = LlamaIndexAgent(agent_name, self.framework_config)
        return await agent.execute(task)

    async def _create_index(self, index_name: str) -> VectorStoreIndex:
        """Create a document index"""
        storage_config = self.storage_configs.get(index_name, {})

        # Set up document directory
        doc_dir = storage_config.get('path', f'./data/documents/{index_name}')
        os.makedirs(doc_dir, exist_ok=True)

        # Check if documents exist, load sample if not
        if not os.listdir(doc_dir):
            logger.warning(f"No documents found in {doc_dir}, loading sample documents")
            self._load_sample_documents(doc_dir)

        # Load documents
        documents = SimpleDirectoryReader(doc_dir).load_data()

        # Set up vector store
        vector_store_config = storage_config.get('vector_store', {})

        if vector_store_config.get('type') == 'qdrant':
            vector_store = QdrantVectorStore(
                host=vector_store_config.get('host', 'localhost'),
                port=vector_store_config.get('port', 6333),
                url=vector_store_config.get('url'),
                index_name=f"{index_name}_docs"
            )

            storage_context = StorageContext.from_defaults(vector_store=vector_store)
        else:
            # Use default in-memory storage
            storage_context = None

        # Create index
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            embed_model=self._get_embed_model(),
            node_parser=SentenceSplitter(chunk_size=1024, chunk_overlap=200)
        )

        logger.info(f"Created index: {index_name}")
        return index

    def _get_embed_model(self):
        """Get embedding model"""
        embed_config = self.framework_config.get('embeddings', {})

        if embed_config.get('type') == 'local':
            return HuggingFaceEmbedding(
                model_name=embed_config.get('model', 'sentence-transformers/all-MiniLM-L6-v2')
            )
        else:
            # Use default OpenAI embeddings
            from llama_index.embeddings.openai import OpenAIEmbedding
            return OpenAIEmbedding()

    def _load_sample_documents(self, doc_dir: str):
        """Load sample documents for testing"""
        sample_docs = [
            "Artificial Intelligence is transforming how we work and live.",
            "Machine learning algorithms can process vast amounts of data.",
            "Natural Language Processing enables computers to understand human language.",
            "Computer vision allows machines to interpret visual information.",
            "Deep learning has revolutionized AI capabilities."
        ]

        for i, doc in enumerate(sample_docs):
            with open(f"{doc_dir}/doc_{i+1}.txt", 'w') as f:
                f.write(doc)

    def configure(self) -> None:
        """Configure LlamaIndex framework"""
        logger.info("Configuring LlamaIndex framework")

        # Validate configuration
        if not self.validate_config():
            raise ValueError("Invalid LlamaIndex configuration")

        # Create document directories
        for index_name, storage_config in self.storage_configs.items():
            doc_dir = storage_config.get('path', f'./data/documents/{index_name}')
            os.makedirs(doc_dir, exist_ok=True)

        # Initialize default indexes
        default_indexes = self.framework_config.get('default_indexes', ['default'])
        for index_name in default_indexes:
            if index_name not in self.indexes:
                try:
                    self.indexes[index_name] = asyncio.run(self._create_index(index_name))
                except Exception as e:
                    logger.error(f"Failed to create index {index_name}: {e}")

        logger.info("LlamaIndex configuration completed")

    def get_status(self) -> Dict[str, Any]:
        """Get LlamaIndex status"""
        status = super().get_status()

        # Check document directories
        doc_directories = []
        for index_name, storage_config in self.storage_configs.items():
            doc_dir = storage_config.get('path', f'./data/documents/{index_name}')
            if os.path.exists(doc_dir):
                doc_count = len([f for f in os.listdir(doc_dir) if f.endswith(('.txt', '.pdf', '.docx'))])
                doc_directories.append({'name': index_name, 'documents': doc_count})

        status.update({
            'indexes_count': len(self.indexes),
            'query_engines_count': len(self.query_engines),
            'document_directories': doc_directories,
            'storage_type': self.framework_config.get('storage_type', 'default')
        })

        return status

    def validate_config(self) -> bool:
        """Validate LlamaIndex configuration"""
        required_keys = ['frameworks', 'frameworks.llamaindex']

        for key in required_keys:
            if not self._check_nested_key(self.config, key):
                logger.error(f"Missing required config key: {key}")
                return False

        # Validate storage configurations
        storage_configs = self.storage_configs
        for storage_name, storage_config in storage_configs.items():
            if 'path' not in storage_config:
                logger.error(f"Missing path for storage: {storage_name}")
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
