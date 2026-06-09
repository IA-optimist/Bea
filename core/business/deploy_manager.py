"""
BeaMax P3.4 — Deployment Manager
Automates VPS deployment with Docker and Caddy reverse proxy.
"""

import os
import subprocess  # nosec B404
import logging
from typing import Dict, Any, Optional

from models.opportunity import Opportunity

logger = logging.getLogger(__name__)


class DeployManager:
    """Automate VPS deployment for MVPs"""
    
    def __init__(
        self,
        vps_host: Optional[str] = None,
        vps_user: Optional[str] = None,
        vps_ssh_key: Optional[str] = None,
        deploy_base_dir: str = "/opt/beamax_mvps",
        domain: str = "beamaxapp.co.uk",
    ):
        """
        Initialize deployment manager.
        
        Args:
            vps_host: VPS hostname or IP
            vps_user: SSH username
            vps_ssh_key: Path to SSH private key
            deploy_base_dir: Base directory for deployments on VPS
            domain: Base domain for subdomains
        """
        self.vps_host = vps_host or os.getenv("VPS_DEPLOY_HOST", "bea.beamaxapp.co.uk")
        self.vps_user = vps_user or os.getenv("VPS_DEPLOY_USER", "root")
        self.vps_ssh_key = vps_ssh_key or os.getenv("VPS_SSH_KEY", "/root/.ssh/id_rsa")
        self.deploy_base_dir = deploy_base_dir
        self.domain = domain
        
        logger.info(
            f"deploy_manager_initialized "
            f"host={self.vps_host} "
            f"user={self.vps_user} "
            f"domain={self.domain}"
        )
    
    def deploy(
        self,
        opportunity: Opportunity,
        repo_url: str,
        project_slug: str,
    ) -> Dict[str, Any]:
        """
        Deploy MVP to VPS.
        
        Args:
            opportunity: Opportunity model
            repo_url: GitHub repository URL
            project_slug: Project slug (for subdomain)
        
        Returns:
            Dict with deployment result:
            {
                "success": bool,
                "subdomain": str,
                "url": str,
                "deploy_path": str,
                "message": str,
            }
        """
        subdomain = f"{project_slug}.{self.domain}"
        deploy_path = f"{self.deploy_base_dir}/{project_slug}"
        
        logger.info(
            f"deployment_started "
            f"opportunity_id={opportunity.id} "
            f"subdomain={subdomain}"
        )
        
        try:
            # 0. Quick reachability check — fall back to Railway if VPS not up
            ssh_cmd = self._build_ssh_cmd()
            probe = subprocess.run(  # nosec B603 B607
                ssh_cmd + ["echo ok"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if probe.returncode != 0:
                logger.warning(
                    f"vps_unreachable host={self.vps_host} stderr={probe.stderr.strip()[:80]} "
                    f"→ falling back to Railway"
                )
                return self._deploy_railway(opportunity, project_slug)

            # 1. Clone repo on VPS
            logger.debug(f"cloning_repo_on_vps path={deploy_path}")

            # Create base dir
            result = subprocess.run(  # nosec B603 B607
                ssh_cmd + [f"mkdir -p {self.deploy_base_dir}"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logger.error(f"mkdir_failed: {result.stderr}")
                return {
                    "success": False,
                    "message": f"Failed to create deploy directory: {result.stderr}",
                    "error": "mkdir_failed",
                }
            
            # Clone or pull repo
            result = subprocess.run(  # nosec B603 B607
                ssh_cmd + [
                    f"if [ -d {deploy_path} ]; then "
                    f"cd {deploy_path} && git pull; "
                    f"else "
                    f"git clone {repo_url} {deploy_path}; "
                    f"fi"
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            
            if result.returncode != 0:
                logger.error(f"git_clone_failed: {result.stderr}")
                return {
                    "success": False,
                    "message": f"Failed to clone repo: {result.stderr}",
                    "error": "git_clone_failed",
                }
            
            logger.info(f"repo_cloned path={deploy_path}")
            
            # 2. Build and start Docker containers
            logger.debug("starting_docker_containers")
            
            result = subprocess.run(  # nosec B603 B607
                ssh_cmd + [
                    f"cd {deploy_path} && "
                    f"docker-compose down 2>/dev/null || true && "
                    f"docker-compose up -d --build"
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 min for build
            )
            
            if result.returncode != 0:
                logger.error(f"docker_up_failed: {result.stderr}")
                return {
                    "success": False,
                    "message": f"Failed to start containers: {result.stderr}",
                    "error": "docker_up_failed",
                }
            
            logger.info(f"docker_containers_started path={deploy_path}")
            
            # 3. Configure Caddy reverse proxy
            logger.debug(f"configuring_caddy subdomain={subdomain}")
            
            caddy_config = self._generate_caddy_config(subdomain, project_slug)
            
            # Write Caddyfile snippet
            result = subprocess.run(  # nosec B603 B607
                ssh_cmd + [
                    f"echo '{caddy_config}' > /etc/caddy/sites/{project_slug}.caddy"
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode != 0:
                logger.warning(f"caddy_config_write_failed: {result.stderr}")
            
            # Reload Caddy
            result = subprocess.run(  # nosec B603 B607
                ssh_cmd + ["systemctl reload caddy"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode != 0:
                logger.warning(f"caddy_reload_failed: {result.stderr}")
            else:
                logger.info(f"caddy_reloaded subdomain={subdomain}")
            
            # 4. Health check
            logger.debug("running_health_check")
            
            import time
            time.sleep(5)  # Wait for services to start
            
            result = subprocess.run(  # nosec B603 B607
                ssh_cmd + [
                    f"cd {deploy_path} && "
                    f"docker-compose ps --format json | jq -r '.State'"
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if "running" not in result.stdout.lower():
                logger.warning(f"containers_not_running: {result.stdout}")
            
            url = f"https://{subdomain}"
            
            logger.info(
                f"deployment_completed "
                f"opportunity_id={opportunity.id} "
                f"url={url}"
            )
            
            return {
                "success": True,
                "subdomain": subdomain,
                "url": url,
                "deploy_path": deploy_path,
                "message": f"MVP deployed successfully: {url}",
            }
        
        except subprocess.TimeoutExpired as e:
            logger.error(f"deployment_timeout opportunity_id={opportunity.id}: {e}")
            return {
                "success": False,
                "message": f"Deployment timeout: {str(e)}",
                "error": "timeout",
            }
        
        except Exception as e:
            logger.error(f"deployment_exception opportunity_id={opportunity.id}: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Deployment exception: {str(e)}",
                "error": str(e),
            }
    
    def _deploy_railway(self, opportunity: "Opportunity", project_slug: str) -> Dict[str, Any]:
        """Deploy MVP to Railway when VPS is not available."""
        import shutil as _shutil
        from core.business.mvp_generator import MVPGenerator
        generator = MVPGenerator()
        mvp_dir = str(generator.workspace_dir / project_slug)

        # Locate railway CLI (may not be in PATH when running as service)
        railway_bin = _shutil.which("railway") or r"C:\Users\maxen\AppData\Roaming\npm\railway.cmd"

        try:
            logger.info(f"railway_deploy_started opportunity_id={opportunity.id} dir={mvp_dir}")
            env = {**__import__("os").environ}

            # Init Railway project linked to the slug
            subprocess.run(  # nosec B603 B607
                [railway_bin, "init", "--name", f"beamax-mvp-{opportunity.id}"],
                cwd=mvp_dir,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )

            # Deploy
            result = subprocess.run(  # nosec B603 B607
                [railway_bin, "up", "--detach"],
                cwd=mvp_dir,
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )

            if result.returncode != 0:
                logger.error(f"railway_up_failed: {result.stderr}")
                return {
                    "success": False,
                    "message": f"Railway deploy failed: {result.stderr[:200]}",
                    "error": "railway_up_failed",
                }

            # Get the URL from railway status
            status = subprocess.run(  # nosec B603 B607
                [railway_bin, "status", "--json"],
                cwd=mvp_dir,
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
            )

            url = f"https://beamax-mvp-{opportunity.id}.up.railway.app"
            try:
                import json as _json
                info = _json.loads(status.stdout)
                url = info.get("url") or info.get("deploymentUrl") or url
            except Exception:
                pass

            logger.info(f"railway_deploy_completed opportunity_id={opportunity.id} url={url}")
            return {
                "success": True,
                "subdomain": f"beamax-mvp-{opportunity.id}.up.railway.app",
                "url": url,
                "deploy_path": mvp_dir,
                "message": f"Deployed to Railway: {url}",
            }

        except subprocess.TimeoutExpired as e:
            logger.error(f"railway_deploy_timeout: {e}")
            return {"success": False, "message": f"Railway timeout: {e}", "error": "timeout"}
        except Exception as e:
            logger.error(f"railway_deploy_exception: {e}", exc_info=True)
            return {"success": False, "message": str(e), "error": str(e)}

    def _build_ssh_cmd(self) -> list:
        """Build SSH command with proper key and options"""
        return [
            "ssh",
            "-i", self.vps_ssh_key,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{self.vps_user}@{self.vps_host}",
        ]
    
    def _generate_caddy_config(self, subdomain: str, project_slug: str) -> str:
        """Generate Caddyfile snippet for reverse proxy"""
        return f"""
{subdomain} {{
    reverse_proxy localhost:8000
    encode gzip
    log {{
        output file /var/log/caddy/{project_slug}.log
    }}
}}
"""
    
    def undeploy(self, project_slug: str) -> bool:
        """
        Remove deployment from VPS.
        
        Args:
            project_slug: Project slug
        
        Returns:
            bool: True if successful
        """
        deploy_path = f"{self.deploy_base_dir}/{project_slug}"
        
        logger.info(f"undeployment_started slug={project_slug}")
        
        try:
            ssh_cmd = self._build_ssh_cmd()
            
            # Stop containers
            subprocess.run(  # nosec B603 B607
                ssh_cmd + [f"cd {deploy_path} && docker-compose down || true"],
                capture_output=True,
                timeout=30,
            )
            
            # Remove directory
            subprocess.run(  # nosec B603 B607
                ssh_cmd + [f"rm -rf {deploy_path}"],
                capture_output=True,
                timeout=10,
            )
            
            # Remove Caddy config
            subprocess.run(  # nosec B603 B607
                ssh_cmd + [f"rm -f /etc/caddy/sites/{project_slug}.caddy"],
                capture_output=True,
                timeout=10,
            )
            
            # Reload Caddy
            subprocess.run(  # nosec B603 B607
                ssh_cmd + ["systemctl reload caddy"],
                capture_output=True,
                timeout=10,
            )
            
            logger.info(f"undeployment_completed slug={project_slug}")
            return True
        
        except Exception as e:
            logger.error(f"undeploy_exception slug={project_slug}: {e}", exc_info=True)
            return False
