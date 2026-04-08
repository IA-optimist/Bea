"""
JarvisMax P3.3 — MVP Generator
Generates complete SaaS codebases from feasibility analyses.
"""

import os
import re
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

from models.opportunity import Opportunity
from models.opportunity_analysis import OpportunityAnalysis

logger = logging.getLogger(__name__)


class MVPGenerator:
    """Generate complete MVP codebase from feasibility analysis"""
    
    def __init__(self, workspace_dir: str = "/tmp/jarvismax_mvp"):
        """
        Initialize MVP generator.
        
        Args:
            workspace_dir: Directory for generated MVPs
        """
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup Jinja2 environment
        templates_dir = Path(__file__).parent.parent.parent / "business" / "templates" / "mvp"
        self.jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))
        
        logger.info(f"mvp_generator_initialized workspace={self.workspace_dir}")
    
    def generate(
        self,
        opportunity: Opportunity,
        analysis: OpportunityAnalysis,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate complete MVP codebase.
        
        Args:
            opportunity: Opportunity model
            analysis: OpportunityAnalysis model
            output_dir: Optional custom output directory
        
        Returns:
            Dict with generation result:
            {
                "success": bool,
                "output_dir": str,
                "files_created": int,
                "project_slug": str,
                "message": str,
            }
        """
        logger.info(f"mvp_generation_started opportunity_id={opportunity.id}")
        
        # Prepare context
        context = self._prepare_context(opportunity, analysis)
        
        # Create project directory
        if output_dir:
            project_dir = Path(output_dir)
        else:
            project_dir = self.workspace_dir / context["project_slug"]
        
        if project_dir.exists():
            logger.warning(f"mvp_directory_exists path={project_dir}")
            shutil.rmtree(project_dir)
        
        project_dir.mkdir(parents=True, exist_ok=True)
        
        files_created = 0
        
        try:
            # 1. Generate backend
            backend_dir = project_dir
            files_created += self._generate_backend(backend_dir, context)
            
            # 2. Generate frontend
            frontend_dir = project_dir / "frontend"
            frontend_dir.mkdir(exist_ok=True)
            files_created += self._generate_frontend(frontend_dir, context)
            
            # 3. Generate Docker files
            files_created += self._generate_docker(project_dir, context)
            
            # 4. Generate deployment files
            github_dir = project_dir / ".github" / "workflows"
            github_dir.mkdir(parents=True, exist_ok=True)
            files_created += self._generate_deployment(github_dir, context)
            
            # 5. Generate README
            files_created += self._generate_readme(project_dir, context)
            
            # 6. Generate .gitignore
            files_created += self._generate_gitignore(project_dir, context)
            
            logger.info(
                f"mvp_generation_completed "
                f"opportunity_id={opportunity.id} "
                f"files_created={files_created} "
                f"output_dir={project_dir}"
            )
            
            return {
                "success": True,
                "output_dir": str(project_dir),
                "files_created": files_created,
                "project_slug": context["project_slug"],
                "message": f"MVP generated successfully: {files_created} files created",
            }
        
        except Exception as e:
            logger.error(f"mvp_generation_failed opportunity_id={opportunity.id}: {e}", exc_info=True)
            
            # Cleanup on failure
            if project_dir.exists():
                shutil.rmtree(project_dir)
            
            return {
                "success": False,
                "output_dir": str(project_dir),
                "files_created": 0,
                "project_slug": context["project_slug"],
                "message": f"MVP generation failed: {str(e)}",
                "error": str(e),
            }
    
    def _prepare_context(self, opportunity: Opportunity, analysis: OpportunityAnalysis) -> Dict[str, Any]:
        """Prepare Jinja2 template context"""
        
        # Generate project slug
        project_slug = self._slugify(opportunity.title)
        
        # Extract models from MVP features (simple heuristic)
        models = self._extract_models(analysis.mvp_features or [])
        
        context = {
            # Project metadata
            "project_name": opportunity.title,
            "project_slug": project_slug,
            "description": opportunity.description or "No description provided",
            "timestamp": datetime.utcnow().isoformat(),
            "opportunity_id": opportunity.id,
            
            # Opportunity data
            "pain_points": opportunity.pain_points or [],
            "total_score": opportunity.total_score,
            
            # Analysis data
            "tech_stack": analysis.tech_stack or ["python", "fastapi", "postgresql"],
            "dependencies": analysis.dependencies or [],
            "complexity_score": analysis.complexity_score or 5,
            "estimated_hours": analysis.estimated_hours or 80,
            "mvp_features": analysis.mvp_features or [],
            "nice_to_have_features": analysis.nice_to_have_features or [],
            "out_of_scope": analysis.out_of_scope or [],
            "technical_risks": analysis.technical_risks or [],
            "mitigation_strategies": analysis.mitigation_strategies or [],
            "recommendation": analysis.recommendation or "BUILD",
            "confidence_score": f"{analysis.confidence_score:.3f}" if analysis.confidence_score else "0.000",
            "market_fit_score": analysis.market_fit_score or 0,
            
            # Database
            "db_user": "mvp_user",
            "db_password": "mvp_pass_change_me",
            "db_name": f"{project_slug}_db",
            
            # Models (extracted from features)
            "models": models,
        }
        
        return context
    
    def _extract_models(self, features: List[str]) -> List[Dict[str, Any]]:
        """
        Extract database models from MVP features.
        
        Simple heuristic: look for nouns in feature names.
        E.g., "user_dashboard" → User model
              "payment_processing" → Payment model
        """
        model_names = set()
        
        # Common SaaS entities
        common_models = {
            "user": {"name": "Profile", "table_name": "profiles", "fields": [
                {"name": "bio", "type": "String", "python_type": "str", "optional": True, "nullable": True},
                {"name": "avatar_url", "type": "String", "python_type": "str", "optional": True, "nullable": True},
            ]},
            "dashboard": {"name": "Dashboard", "table_name": "dashboards", "fields": [
                {"name": "name", "type": "String", "python_type": "str"},
                {"name": "config", "type": "String", "python_type": "str", "optional": True, "nullable": True},
            ]},
            "payment": {"name": "Payment", "table_name": "payments", "fields": [
                {"name": "amount", "type": "Integer", "python_type": "int"},
                {"name": "currency", "type": "String", "python_type": "str", "default": "'usd'"},
                {"name": "status", "type": "String", "python_type": "str", "default": "'pending'"},
            ]},
            "subscription": {"name": "Subscription", "table_name": "subscriptions", "fields": [
                {"name": "plan_name", "type": "String", "python_type": "str"},
                {"name": "status", "type": "String", "python_type": "str", "default": "'active'"},
                {"name": "expires_at", "type": "DateTime", "python_type": "datetime", "optional": True, "nullable": True},
            ]},
            "project": {"name": "Project", "table_name": "projects", "fields": [
                {"name": "name", "type": "String", "python_type": "str"},
                {"name": "description", "type": "String", "python_type": "str", "optional": True, "nullable": True},
                {"name": "status", "type": "String", "python_type": "str", "default": "'active'"},
            ]},
            "task": {"name": "Task", "table_name": "tasks", "fields": [
                {"name": "title", "type": "String", "python_type": "str"},
                {"name": "description", "type": "String", "python_type": "str", "optional": True, "nullable": True},
                {"name": "completed", "type": "Boolean", "python_type": "bool", "default": "False"},
            ]},
        }
        
        # Scan features for model keywords
        for feature in features:
            feature_lower = feature.lower()
            for keyword in common_models:
                if keyword in feature_lower:
                    model_names.add(keyword)
        
        # Default: at least one model
        if not model_names:
            model_names.add("project")
        
        models = [common_models[name] for name in model_names if name in common_models]
        
        return models
    
    def _slugify(self, text: str) -> str:
        """Convert text to slug (lowercase, hyphens)"""
        text = text.lower()
        text = re.sub(r'[^a-z0-9]+', '-', text)
        text = text.strip('-')
        return text
    
    def _generate_backend(self, output_dir: Path, context: Dict[str, Any]) -> int:
        """Generate backend files"""
        files = 0
        
        # main.py
        template = self.jinja_env.get_template("backend/main.py.jinja2")
        output_file = output_dir / "main.py"
        output_file.write_text(template.render(**context))
        files += 1
        
        # requirements.txt
        template = self.jinja_env.get_template("backend/requirements.txt.jinja2")
        output_file = output_dir / "requirements.txt"
        output_file.write_text(template.render(**context))
        files += 1
        
        logger.debug(f"backend_generated files={files}")
        return files
    
    def _generate_frontend(self, output_dir: Path, context: Dict[str, Any]) -> int:
        """Generate frontend files"""
        files = 0
        
        # index.html
        template = self.jinja_env.get_template("frontend/index.html.jinja2")
        output_file = output_dir / "index.html"
        output_file.write_text(template.render(**context))
        files += 1
        
        logger.debug(f"frontend_generated files={files}")
        return files
    
    def _generate_docker(self, output_dir: Path, context: Dict[str, Any]) -> int:
        """Generate Docker files"""
        files = 0
        
        # Dockerfile
        template = self.jinja_env.get_template("docker/Dockerfile.jinja2")
        output_file = output_dir / "Dockerfile"
        output_file.write_text(template.render(**context))
        files += 1
        
        # docker-compose.yml
        template = self.jinja_env.get_template("docker/docker-compose.yml.jinja2")
        output_file = output_dir / "docker-compose.yml"
        output_file.write_text(template.render(**context))
        files += 1
        
        logger.debug(f"docker_generated files={files}")
        return files
    
    def _generate_deployment(self, output_dir: Path, context: Dict[str, Any]) -> int:
        """Generate deployment files"""
        files = 0
        
        # GitHub Actions workflow
        template = self.jinja_env.get_template("deployment/github-actions.yml.jinja2")
        output_file = output_dir / "deploy.yml"
        output_file.write_text(template.render(**context))
        files += 1
        
        logger.debug(f"deployment_generated files={files}")
        return files
    
    def _generate_readme(self, output_dir: Path, context: Dict[str, Any]) -> int:
        """Generate README"""
        template = self.jinja_env.get_template("README.md.jinja2")
        output_file = output_dir / "README.md"
        output_file.write_text(template.render(**context))
        
        logger.debug("readme_generated")
        return 1
    
    def _generate_gitignore(self, output_dir: Path, context: Dict[str, Any]) -> int:
        """Generate .gitignore"""
        template = self.jinja_env.get_template(".gitignore.jinja2")
        output_file = output_dir / ".gitignore"
        output_file.write_text(template.render(**context))
        
        logger.debug("gitignore_generated")
        return 1
