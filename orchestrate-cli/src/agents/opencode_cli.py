"""
OpenCode CLI Integration - Collaborative AI coding platform

Features:
- OpenCode AI integration
- Collaborative coding sessions
- Real-time code sharing
- Team programming
- Code review and feedback
- Project management
"""

import asyncio
import subprocess
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    import opencode
    OPENCODE_AVAILABLE = True
except ImportError:
    OPENCODE_AVAILABLE = False

class OpenCodeCLI:
    """OpenCode CLI integration for collaborative AI coding"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.available = OPENCODE_AVAILABLE
        self.api_key = self.config.get('api_key') or self._get_api_key()
        self.model = self.config.get('model', 'gpt-4')
        self.client = None

    def _get_api_key(self) -> Optional[str]:
        """Get OpenCode API key from environment"""
        import os
        return os.getenv('OPENCODE_API_KEY') or os.getenv('OPENCODE_TOKEN')

    def check_availability(self) -> bool:
        """Check if OpenCode CLI is available"""
        if not self.available:
            logger.error("OpenCode CLI not available")
            return False

        if not self.api_key:
            logger.error("OpenCode API key not configured")
            return False

        try:
            # Check if opencode command is available
            result = subprocess.run(['opencode', '--version'],
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except Exception as e:
            logger.error(f"OpenCode CLI check failed: {e}")
            return False

    async def initialize_client(self):
        """Initialize OpenCode client"""
        if not self.check_availability():
            raise Exception("OpenCode CLI not available")

        try:
            self.client = opencode.OpenCodeClient(
                api_key=self.api_key,
                model=self.model
            )
            logger.info("OpenCode client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize OpenCode client: {e}")
            raise

    async def create_session(self, project_name: str, participants: List[str] = None) -> Dict[str, Any]:
        """Create a collaborative coding session"""
        logger.info(f"Creating OpenCode session: {project_name}")

        try:
            if not self.client:
                await self.initialize_client()

            session = await self.client.create_session(
                name=project_name,
                participants=participants or [],
                settings=self.config.get('session_settings', {})
            )

            return {
                'session_id': session['id'],
                'project_name': project_name,
                'participants': participants or [],
                'session_url': session['url'],
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Session creation failed: {e}")
            return {'error': str(e)}

    async def join_session(self, session_id: str) -> Dict[str, Any]:
        """Join an existing coding session"""
        logger.info(f"Joining OpenCode session: {session_id}")

        try:
            if not self.client:
                await self.initialize_client()

            session = await self.client.join_session(session_id)

            return {
                'session_id': session_id,
                'joined': True,
                'session_info': session,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Session join failed: {e}")
            return {'error': str(e)}

    async def share_code(self, session_id: str, code: str, language: str = 'python') -> Dict[str, Any]:
        """Share code in a collaborative session"""
        logger.info(f"Sharing code in session: {session_id}")

        try:
            if not self.client:
                await self.initialize_client()

            share_result = await self.client.share_code(
                session_id=session_id,
                code=code,
                language=language
            )

            return {
                'session_id': session_id,
                'code': code,
                'language': language,
                'share_result': share_result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Code sharing failed: {e}")
            return {'error': str(e)}

    async def request_review(self, session_id: str, file_path: str, review_type: str = 'general') -> Dict[str, Any]:
        """Request code review from collaborators"""
        logger.info(f"Requesting review for: {file_path}")

        try:
            if not self.client:
                await self.initialize_client()

            review_request = await self.client.request_review(
                session_id=session_id,
                file_path=file_path,
                review_type=review_type
            )

            return {
                'session_id': session_id,
                'file_path': file_path,
                'review_type': review_type,
                'review_request': review_request,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Review request failed: {e}")
            return {'error': str(e)}

    async def get_feedback(self, session_id: str) -> Dict[str, Any]:
        """Get feedback from collaborators"""
        logger.info(f"Getting feedback for session: {session_id}")

        try:
            if not self.client:
                await self.initialize_client()

            feedback = await self.client.get_feedback(session_id)

            return {
                'session_id': session_id,
                'feedback': feedback,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Feedback retrieval failed: {e}")
            return {'error': str(e)}

    async def collaborate_on_task(self, session_id: str, task_description: str) -> Dict[str, Any]:
        """Collaborate on a specific task"""
        logger.info(f"Collaborating on task: {task_description}")

        try:
            if not self.client:
                await self.initialize_client()

            collaboration = await self.client.collaborate_on_task(
                session_id=session_id,
                task_description=task_description
            )

            return {
                'session_id': session_id,
                'task_description': task_description,
                'collaboration': collaboration,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Task collaboration failed: {e}")
            return {'error': str(e)}

    async def create_project(self, project_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new collaborative project"""
        logger.info("Creating collaborative project")

        try:
            if not self.client:
                await self.initialize_client()

            project = await self.client.create_project(project_config)

            return {
                'project_config': project_config,
                'project': project,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Project creation failed: {e}")
            return {'error': str(e)}

    async def list_projects(self) -> Dict[str, Any]:
        """List all collaborative projects"""
        logger.info("Listing collaborative projects")

        try:
            if not self.client:
                await self.initialize_client()

            projects = await self.client.list_projects()

            return {
                'projects': projects,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Project listing failed: {e}")
            return {'error': str(e)}

    async def invite_collaborators(self, project_id: str, emails: List[str]) -> Dict[str, Any]:
        """Invite collaborators to a project"""
        logger.info(f"Inviting collaborators to project: {project_id}")

        try:
            if not self.client:
                await self.initialize_client()

            invitations = await self.client.invite_collaborators(
                project_id=project_id,
                emails=emails
            )

            return {
                'project_id': project_id,
                'emails': emails,
                'invitations': invitations,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Collaborator invitation failed: {e}")
            return {'error': str(e)}

    async def get_project_activity(self, project_id: str) -> Dict[str, Any]:
        """Get project activity and collaboration metrics"""
        logger.info(f"Getting activity for project: {project_id}")

        try:
            if not self.client:
                await self.initialize_client()

            activity = await self.client.get_project_activity(project_id)

            return {
                'project_id': project_id,
                'activity': activity,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Activity retrieval failed: {e}")
            return {'error': str(e)}

    async def generate_collaborative_report(self, project_id: str) -> Dict[str, Any]:
        """Generate collaboration analytics report"""
        logger.info(f"Generating collaboration report for project: {project_id}")

        try:
            if not self.client:
                await self.initialize_client()

            report = await self.client.generate_collaborative_report(project_id)

            return {
                'project_id': project_id,
                'collaboration_report': report,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            return {'error': str(e)}

    async def end_session(self, session_id: str) -> Dict[str, Any]:
        """End a collaborative session"""
        logger.info(f"Ending session: {session_id}")

        try:
            if not self.client:
                await self.initialize_client()

            result = await self.client.end_session(session_id)

            return {
                'session_id': session_id,
                'session_ended': result,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Session ending failed: {e}")
            return {'error': str(e)}

    async def get_session_history(self, session_id: str) -> Dict[str, Any]:
        """Get session history and code changes"""
        logger.info(f"Getting session history: {session_id}")

        try:
            if not self.client:
                await self.initialize_client()

            history = await self.client.get_session_history(session_id)

            return {
                'session_id': session_id,
                'session_history': history,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"History retrieval failed: {e}")
            return {'error': str(e)}

    async def export_session(self, session_id: str, format: str = 'zip') -> Dict[str, Any]:
        """Export session data"""
        logger.info(f"Exporting session: {session_id}")

        try:
            if not self.client:
                await self.initialize_client()

            export = await self.client.export_session(session_id, format)

            return {
                'session_id': session_id,
                'format': format,
                'export': export,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Session export failed: {e}")
            return {'error': str(e)}

    async def create_template(self, template_name: str, template_config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a collaboration template"""
        logger.info(f"Creating template: {template_name}")

        try:
            if not self.client:
                await self.initialize_client()

            template = await self.client.create_template(
                name=template_name,
                config=template_config
            )

            return {
                'template_name': template_name,
                'template_config': template_config,
                'template': template,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Template creation failed: {e}")
            return {'error': str(e)}

    async def list_templates(self) -> Dict[str, Any]:
        """List available collaboration templates"""
        logger.info("Listing collaboration templates")

        try:
            if not self.client:
                await self.initialize_client()

            templates = await self.client.list_templates()

            return {
                'templates': templates,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            logger.error(f"Template listing failed: {e}")
            return {'error': str(e)}

    def get_version(self) -> Dict[str, Any]:
        """Get OpenCode CLI version"""
        if not self.check_availability():
            return {"error": "OpenCode CLI not available"}

        try:
            process = subprocess.run(['opencode', '--version'],
                                  capture_output=True, text=True, timeout=10)

            return {
                'version': process.stdout.strip(),
                'available': True,
                'timestamp': asyncio.get_event_loop().time()
            }

        except Exception as e:
            return {
                'error': str(e),
                'available': False,
                'timestamp': asyncio.get_event_loop().time()
            }

    def install_opencode(self) -> Dict[str, Any]:
        """Install OpenCode CLI"""
        logger.info("Installing OpenCode CLI")

        try:
            # Install via pip
            process = subprocess.run(['pip', 'install', 'opencode-ai'],
                                  capture_output=True, text=True, timeout=60)

            if process.returncode == 0:
                logger.info("OpenCode CLI installed successfully")
                return {
                    'success': True,
                    'message': 'OpenCode CLI installed successfully',
                    'timestamp': asyncio.get_event_loop().time()
                }
            else:
                logger.error(f"OpenCode CLI installation failed: {process.stderr}")
                return {
                    'success': False,
                    'error': process.stderr,
                    'timestamp': asyncio.get_event_loop().time()
                }

        except Exception as e:
            logger.error(f"OpenCode CLI installation failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': asyncio.get_event_loop().time()
            }

    def configure_api_key(self, api_key: str) -> bool:
        """Configure OpenCode API key"""
        try:
            # Store API key in config
            self.config['api_key'] = api_key
            self.api_key = api_key

            # Set up authentication
            process = subprocess.run(['opencode', 'auth', 'login', api_key],
                                  capture_output=True, text=True, timeout=30)

            if process.returncode == 0:
                logger.info("OpenCode API key configured successfully")
                return True
            else:
                logger.error(f"Failed to configure OpenCode API key: {process.stderr}")
                return False

        except Exception as e:
            logger.error(f"Failed to configure OpenCode API key: {e}")
            return False
