# Backend WebSocket Server for Orchestrate Mobile

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Set, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS — origines explicites via env CORS_ORIGINS (csv).
# Hardening (audit critique C1): un `allow_origins=["*"]` + `allow_credentials=True`
# est non seulement rejeté par les navigateurs modernes, mais reste exploitable
# depuis tout client non-browser (curl/Postman) qui ré-émet les cookies/headers.
_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Data Models
class Agent(BaseModel):
    id: str
    name: str
    type: str
    status: str
    progress: float
    message: str
    model: str
    config: Dict[str, Any]
    last_update: datetime
    active_workflows: List[str]

class Workflow(BaseModel):
    id: str
    name: str
    description: str
    agent_ids: List[str]
    status: str
    progress: float
    steps: List[Dict[str, Any]]
    start_time: datetime
    end_time: datetime = None
    config: Dict[str, Any]
    framework: str

class Message(BaseModel):
    id: str
    agent_id: str
    content: str
    type: str
    timestamp: datetime
    metadata: Dict[str, Any]

class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.agents: Dict[str, Agent] = {}
        self.workflows: Dict[str, Workflow] = {}
        self.messages: List[Message] = []
        self.websocket_clients: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.websocket_clients.add(websocket)
        logger.info(f"Client {client_id} connected")
        
        # Send initial data
        await self.send_to_client(client_id, {
            'type': 'init',
            'data': {
                'agents': list(self.agents.values()),
                'workflows': list(self.workflows.values()),
            }
        })
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        logger.info(f"Client {client_id} disconnected")
    
    async def send_to_client(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error sending to client {client_id}: {e}")
                self.disconnect(client_id)
    
    async def broadcast(self, message: dict):
        disconnected = set()
        for websocket in self.websocket_clients:
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")
                disconnected.add(websocket)
        
        # Clean up disconnected clients
        for websocket in disconnected:
            self.websocket_clients.discard(websocket)
    
    async def handle_agent_update(self, agent_id: str, data: dict):
        # Update agent
        agent = self.agents.get(agent_id)
        if agent:
            agent.status = data.get('status', agent.status)
            agent.progress = data.get('progress', agent.progress)
            agent.message = data.get('message', agent.message)
            agent.last_update = datetime.now()
            
            # Broadcast update
            await self.broadcast({
                'type': 'agent_update',
                'data': agent.dict()
            })
            
            logger.info(f"Agent {agent_id} updated: {agent.status}")
    
    async def handle_workflow_update(self, workflow_id: str, data: dict):
        # Update workflow
        workflow = self.workflows.get(workflow_id)
        if workflow:
            workflow.status = data.get('status', workflow.status)
            workflow.progress = data.get('progress', workflow.progress)
            workflow.steps = data.get('steps', workflow.steps)
            if workflow.status == 'completed':
                workflow.end_time = datetime.now()
            
            # Broadcast update
            await self.broadcast({
                'type': 'workflow_update',
                'data': workflow.dict()
            })
            
            logger.info(f"Workflow {workflow_id} updated: {workflow.status}")

# Global WebSocket manager
ws_manager = WebSocketManager()

# Initialize with sample data
def initialize_sample_data():
    # Sample agents
    ws_manager.agents.update({
        'agent_1': Agent(
            id='agent_1',
            name='LangChain Research Agent',
            type='langchain',
            status='running',
            progress=0.7,
            message='Processing research request...',
            model='gpt-4',
            config={'temperature': 0.7},
            last_update=datetime.now(),
            active_workflows=['workflow_1']
        ),
        'agent_2': Agent(
            id='agent_2',
            name='AutoGen Analysis Agent',
            type='autogen',
            status='idle',
            progress=0.0,
            message='Ready',
            model='claude-3',
            config={},
            last_update=datetime.now(),
            active_workflows=[]
        ),
        'agent_3': Agent(
            id='agent_3',
            name='Kimi Agent',
            type='kimi',
            status='running',
            progress=0.3,
            message='Searching documents...',
            model='kimi-large',
            config={},
            last_update=datetime.now(),
            active_workflows=['workflow_1']
        )
    })
    
    # Sample workflows
    ws_manager.workflows.update({
        'workflow_1': Workflow(
            id='workflow_1',
            name='Research & Analysis Workflow',
            description='Multi-agent research and analysis workflow',
            agent_ids=['agent_1', 'agent_2', 'agent_3'],
            status='running',
            progress=0.5,
            steps=[
                {'id': 'step_1', 'name': 'Research',
                 'status': 'completed', 'progress': 1.0},
                {'id': 'step_2', 'name': 'Analysis',
                 'status': 'running', 'progress': 0.5},
                {'id': 'step_3', 'name': 'Report',
                 'status': 'pending', 'progress': 0.0}
            ],
            start_time=datetime.now(),
            config={'timeout': 300},
            framework='langchain'
        )
    })

# API Endpoints
@app.get("/agents")
async def get_agents():
    return list(ws_manager.agents.values())

@app.get("/workflows")
async def get_workflows():
    return list(ws_manager.workflows.values())

@app.get("/status")
async def get_status():
    return {
        'connected_clients': len(ws_manager.websocket_clients),
        'active_agents': len(
            [a for a in ws_manager.agents.values()
             if a.status == 'running']),
        'active_workflows': len(
            [w for w in ws_manager.workflows.values()
             if w.status == 'running']),
        'total_agents': len(ws_manager.agents),
        'total_workflows': len(ws_manager.workflows)
    }

@app.get("/")
async def root():
    return {"message": "Orchestrate Mobile API"}

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    client_id = f"client_{len(ws_manager.active_connections)}"
    await ws_manager.connect(websocket, client_id)
    
    try:
        while True:
            # Receive messages from client
            data = await websocket.receive_text()
            message = json.loads(data)
            
            message_type = message.get('type')
            
            if message_type == 'agent_command':
                # Handle agent commands
                agent_id = message.get('agent_id')
                command = message.get('command')
                
                # Simulate command execution
                await ws_manager.handle_agent_update(agent_id, {
                    'status': 'running',
                    'progress': 0.5,
                    'message': f'Executing command: {command}'
                })
                
            elif message_type == 'start_workflow':
                # Handle workflow start
                workflow_id = message.get('workflow_id')
                name = message.get('name')
                agent_ids = message.get('agent_ids')
                framework = message.get('framework')
                
                # Create new workflow
                workflow = Workflow(
                    id=workflow_id,
                    name=name,
                    description=f'{name} workflow',
                    agent_ids=agent_ids,
                    status='running',
                    progress=0.0,
                    steps=[],
                    start_time=datetime.now(),
                    config={},
                    framework=framework
                )
                
                ws_manager.workflows[workflow_id] = workflow
                
                # Start agents
                for agent_id in agent_ids:
                    if agent_id in ws_manager.agents:
                        ws_manager.agents[agent_id].active_workflows.append(workflow_id)
                        await ws_manager.handle_agent_update(agent_id, {
                            'status': 'running',
                            'progress': 0.0,
                            'message': f'Started workflow: {name}'
                        })
                
                await ws_manager.broadcast({
                    'type': 'workflow_update',
                    'data': workflow.dict()
                })
                
            elif message_type == 'stop_workflow':
                # Handle workflow stop
                workflow_id = message.get('workflow_id')
                
                if workflow_id in ws_manager.workflows:
                    workflow = ws_manager.workflows[workflow_id]
                    workflow.status = 'completed'
                    workflow.progress = 1.0
                    workflow.end_time = datetime.now()
                    
                    # Stop agents
                    for agent_id in workflow.agent_ids:
                        if agent_id in ws_manager.agents:
                            ws_manager.agents[agent_id].active_workflows.remove(workflow_id)
                            await ws_manager.handle_agent_update(agent_id, {
                                'status': 'idle',
                                'progress': 0.0,
                                'message': 'Workflow completed'
                            })
                    
                    await ws_manager.broadcast({
                        'type': 'workflow_update',
                        'data': workflow.dict()
                    })
            
            elif message_type == '3d_update':
                # Handle 3D visualization updates
                await ws_manager.broadcast({
                    'type': '3d_update',
                    'data': message.get('data')
                })
                
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)

# Kimi Agent SDK Integration
class KimiAgentService:
    def __init__(self):
        self.agents: Dict[str, Any] = {}
    
    async def start_agent(self, agent_id: str, prompt: str, config: dict):
        """Start a Kimi agent with the given prompt"""
        try:
            # Simulate agent execution
            progress = 0.0
            for i in range(10):
                progress += 0.1
                await asyncio.sleep(0.5)  # Simulate work
                
                # Update progress
                await ws_manager.handle_agent_update(agent_id, {
                    'progress': progress,
                    'message': f'Processing... {progress * 100:.0f}%'
                })
            
            # Complete
            await ws_manager.handle_agent_update(agent_id, {
                'status': 'completed',
                'progress': 1.0,
                'message': 'Task completed successfully'
            })
            
        except Exception as e:
            await ws_manager.handle_agent_update(agent_id, {
                'status': 'error',
                'progress': 0.0,
                'message': f'Error: {str(e)}'
            })
    
    async def process_prompt(self, agent_id: str, prompt: str):
        """Process a prompt using Kimi Agent SDK"""
        # This would integrate with the actual Kimi Agent SDK
        # For now, we'll simulate the process
        
        logger.info(f"Processing prompt for agent {agent_id}: {prompt}")
        
        # Start processing
        await ws_manager.handle_agent_update(agent_id, {
            'status': 'running',
            'progress': 0.0,
            'message': f'Starting: {prompt}'
        })
        
        # Simulate processing
        steps = [
            "Understanding the request...",
            "Analyzing requirements...",
            "Generating response...",
            "Finalizing results..."
        ]
        
        for i, step in enumerate(steps):
            await ws_manager.handle_agent_update(agent_id, {
                'progress': (i + 1) / len(steps),
                'message': step
            })
            await asyncio.sleep(1)
        
        # Complete
        await ws_manager.handle_agent_update(agent_id, {
            'status': 'completed',
            'progress': 1.0,
            'message': 'Response generated successfully'
        })

# Initialize sample data
initialize_sample_data()

# Start the server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)