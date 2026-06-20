"""
Configuration Loader - Handles loading and validation of configuration files

Features:
- YAML and JSON configuration support
- Environment variable interpolation
- Configuration validation
- Default value handling
- Configuration templates
"""

import os
import yaml
import json
from pathlib import Path
from typing import Dict, Any, Optional
from loguru import logger

class ConfigLoader:
    """Configuration loader for the orchestrate CLI"""

    def __init__(self, config_path: str = 'config/orchestrate.yaml'):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.templates = {}

    def load(self) -> Dict[str, Any]:
        """Load configuration from file"""
        logger.info(f"Loading configuration from: {self.config_path}")

        if not self.config_path.exists():
            logger.warning(f"Configuration file not found: {self.config_path}")
            return self._get_default_config()

        try:
            with open(self.config_path, 'r') as f:
                if self.config_path.suffix.lower() == '.yaml' or self.config_path.suffix.lower() == '.yml':
                    self.config = yaml.safe_load(f)
                elif self.config_path.suffix.lower() == '.json':
                    self.config = json.load(f)
                else:
                    logger.error(f"Unsupported configuration file format: {self.config_path.suffix}")
                    return self._get_default_config()

            # Interpolate environment variables
            self.config = self._interpolate_env_vars(self.config)

            # Validate configuration
            if not self._validate_config():
                logger.error("Configuration validation failed")
                return self._get_default_config()

            logger.info("Configuration loaded successfully")
            return self.config

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            'version': '1.0.0',
            'frameworks': {
                'langchain': {
                    'enabled': True,
                    'providers': {
                        'openrouter': {
                            'api_key': '${OPENROUTER_API_KEY}',
                            'models': ['deepseek/deepseek-v4-pro'],
                            'temperature': 0.7,
                            'max_tokens': 4000
                        },
                        'anthropic': {
                            'api_key': '${ANTHROPIC_API_KEY}',
                            'models': ['claude-3-sonnet-20240229'],
                            'temperature': 0.7,
                            'max_tokens': 4000
                        }
                    }
                },
                'autogen': {
                    'enabled': True,
                    'agents': {
                        'assistant': {
                            'model': 'deepseek/deepseek-v4-pro',
                            'temperature': 0.7,
                            'max_tokens': 4000,
                            'system_message': 'You are a helpful AI assistant.'
                        },
                        'user_proxy': {
                            'model': 'deepseek/deepseek-v4-pro',
                            'temperature': 0.0,
                            'max_tokens': 4000,
                            'human_input_mode': 'NEVER'
                        }
                    }
                },
                'crewai': {
                    'enabled': True,
                    'agents': {
                        'research_agent': {
                            'role': 'Research Specialist',
                            'goal': 'Gather and analyze information',
                            'backstory': 'Expert researcher with access to multiple data sources',
                            'verbose': True
                        },
                        'code_agent': {
                            'role': 'Code Specialist',
                            'goal': 'Write and review code',
                            'backstory': 'Experienced developer with expertise in multiple programming languages',
                            'verbose': True
                        }
                    }
                },
                'llamaindex': {
                    'enabled': True,
                    'storage': {
                        'path': './data/documents',
                        'vector_store': 'default'
                    },
                    'embeddings': {
                        'type': 'local',
                        'model': 'sentence-transformers/all-MiniLM-L6-v2'
                    }
                },
                'haystack': {
                    'enabled': True,
                    'retrievers': {
                        'bm25': {
                            'type': 'bm25',
                            'top_k': 5
                        },
                        'vector': {
                            'type': 'vector',
                            'top_k': 5
                        }
                    }
                }
            },
            'agents': {
                'default_team': {
                    'framework': 'langchain',
                    'agents': ['research_agent', 'code_agent', 'planning_agent'],
                    'workflow': 'sequential'
                }
            },
            'llm': {
                'default_provider': 'openrouter',
                'default_model': 'deepseek/deepseek-v4-pro',
                'temperature': 0.7,
                'max_tokens': 4000
            },
            'logging': {
                'level': 'INFO',
                'file': './logs/orchestrate.log',
                'format': '{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}'
            },
            'tools': {
                'enabled': ['web_search', 'file_operations', 'code_execution'],
                'custom_tools': []
            },
            'storage': {
                'type': 'local',
                'path': './data'
            },
            'api': {
                'host': 'localhost',
                'port': 8000,
                'debug': False
            }
        }

    def _interpolate_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Interpolate environment variables in configuration"""
        if isinstance(config, dict):
            return {k: self._interpolate_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [self._interpolate_env_vars(item) for item in config]
        elif isinstance(config, str) and config.startswith('${') and config.endswith('}'):
            env_var = config[2:-1]
            return os.getenv(env_var, config)
        else:
            return config

    def _validate_config(self) -> bool:
        """Validate configuration"""
        required_sections = ['frameworks', 'llm', 'logging']

        for section in required_sections:
            if section not in self.config:
                logger.error(f"Missing required configuration section: {section}")
                return False

        # Validate frameworks
        frameworks = self.config.get('frameworks', {})
        for framework_name, framework_config in frameworks.items():
            if not isinstance(framework_config, dict):
                logger.error(f"Invalid framework configuration: {framework_name}")
                return False

            if 'enabled' not in framework_config:
                logger.warning(f"Missing 'enabled' field for framework: {framework_name}")

        # Validate logging
        logging_config = self.config.get('logging', {})
        if 'level' in logging_config:
            valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
            if logging_config['level'] not in valid_levels:
                logger.error(f"Invalid logging level: {logging_config['level']}")
                return False

        return True

    def save(self, config: Dict[str, Any], path: Optional[str] = None) -> bool:
        """Save configuration to file"""
        save_path = Path(path) if path else self.config_path

        try:
            with open(save_path, 'w') as f:
                if save_path.suffix.lower() == '.yaml' or save_path.suffix.lower() == '.yml':
                    yaml.dump(config, f, default_flow_style=False, indent=2)
                elif save_path.suffix.lower() == '.json':
                    json.dump(config, f, indent=2)
                else:
                    logger.error(f"Unsupported configuration file format: {save_path.suffix}")
                    return False

            logger.info(f"Configuration saved to: {save_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False

    def get_template(self, template_name: str) -> Dict[str, Any]:
        """Get configuration template"""
        templates = {
            'minimal': {
                'version': '1.0.0',
                'frameworks': {
                    'langchain': {'enabled': True},
                    'autogen': {'enabled': False},
                    'crewai': {'enabled': False}
                },
                'llm': {
                    'default_provider': 'openrouter',
                    'default_model': 'deepseek/deepseek-v4-pro'
                },
                'logging': {'level': 'INFO'}
            },
            'development': {
                'version': '1.0.0',
                'frameworks': {
                    'langchain': {'enabled': True},
                    'autogen': {'enabled': True},
                    'crewai': {'enabled': True},
                    'llamaindex': {'enabled': True},
                    'haystack': {'enabled': False}
                },
                'llm': {
                    'default_provider': 'openrouter',
                    'default_model': 'deepseek/deepseek-v4-pro'
                },
                'logging': {'level': 'DEBUG', 'file': './logs/orchestrate.log'},
                'tools': {'enabled': ['web_search', 'file_operations', 'code_execution']}
            },
            'production': {
                'version': '1.0.0',
                'frameworks': {
                    'langchain': {'enabled': True},
                    'autogen': {'enabled': True},
                    'crewai': {'enabled': True},
                    'llamaindex': {'enabled': True},
                    'haystack': {'enabled': True}
                },
                'llm': {
                    'default_provider': 'openrouter',
                    'default_model': 'deepseek/deepseek-v4-pro'
                },
                'logging': {'level': 'INFO', 'file': './logs/orchestrate.log'},
                'api': {'host': '0.0.0.0', 'port': 8000, 'debug': False}
            }
        }

        return templates.get(template_name, self._get_default_config())

    def merge_configs(self, base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge two configurations"""
        merged = base_config.copy()

        for key, value in override_config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self.merge_configs(merged[key], value)
            else:
                merged[key] = value

        return merged

    def get_framework_config(self, framework: str) -> Dict[str, Any]:
        """Get configuration for a specific framework"""
        return self.config.get('frameworks', {}).get(framework, {})

    def get_agent_config(self, agent_name: str) -> Dict[str, Any]:
        """Get configuration for a specific agent"""
        for _, team_config in self.config.get('agents', {}).items():
            if 'agents' in team_config:
                if agent_name in team_config['agents']:
                    return team_config
        return {}

    def update_config(self, key: str, value: Any) -> bool:
        """Update configuration value"""
        keys = key.split('.')
        current = self.config

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value
        return True
