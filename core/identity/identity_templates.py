"""
BEA MAX — Identity Templates
===================================
Provider templates defining required fields, secret types,
risk levels, and policies for common services.

Templates are extensible — new providers added by registering a dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IdentityTemplate:
    """Template for creating identities on a specific provider."""
    provider: str
    display_name: str
    identity_type: str
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)
    secret_types: list[dict] = field(default_factory=list)  # [{role, type, required}]
    risk_level: str = "medium"
    requires_approval: bool = False
    expected_domains: list[str] = field(default_factory=list)
    recommended_agents: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "name": self.display_name,
            "type": self.identity_type,
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "secret_types": self.secret_types,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "domains": self.expected_domains,
            "agents": self.recommended_agents,
        }

    def validate_fields(self, data: dict) -> tuple[bool, list[str]]:
        """Validate that required fields are present."""
        missing = [f for f in self.required_fields if not data.get(f)]
        return len(missing) == 0, missing


# ── Built-in Templates ──

TEMPLATES: dict[str, IdentityTemplate] = {}


def _register(t: IdentityTemplate) -> None:
    TEMPLATES[t.provider] = t


# ── Email ──

_register(IdentityTemplate(
    provider="gmail",
    display_name="Gmail Account",
    identity_type="email_account",
    required_fields=["email", "password"],
    optional_fields=["recovery_email", "phone"],
    secret_types=[
        {"role": "password", "type": "credential", "required": True},
        {"role": "totp_seed", "type": "totp", "required": False},
    ],
    risk_level="high",
    requires_approval=True,
    expected_domains=["google.com", "gmail.com", "accounts.google.com"],
    recommended_agents=["browser_agent"],
    notes="Google may require phone verification",
))

_register(IdentityTemplate(
    provider="outlook",
    display_name="Outlook/Microsoft Account",
    identity_type="email_account",
    required_fields=["email", "password"],
    optional_fields=["recovery_email"],
    secret_types=[
        {"role": "password", "type": "credential", "required": True},
        {"role": "totp_seed", "type": "totp", "required": False},
    ],
    risk_level="high",
    requires_approval=True,
    expected_domains=["microsoft.com", "outlook.com", "login.microsoftonline.com"],
    recommended_agents=["browser_agent"],
))

# ── Payment ──

_register(IdentityTemplate(
    provider="stripe",
    display_name="Stripe Account",
    identity_type="payment_account",
    required_fields=["email"],
    optional_fields=["business_name"],
    secret_types=[
        {"role": "api_key_secret", "type": "api_key", "required": True},
        {"role": "api_key_publishable", "type": "api_key", "required": False},
        {"role": "webhook_secret", "type": "api_key", "required": False},
    ],
    risk_level="critical",
    requires_approval=True,
    expected_domains=["stripe.com", "api.stripe.com", "dashboard.stripe.com"],
    recommended_agents=["finance_agent"],
    notes="Handles real money — always production-critical",
))

# ── Developer ──

_register(IdentityTemplate(
    provider="github",
    display_name="GitHub Account",
    identity_type="developer_account",
    required_fields=["username"],
    optional_fields=["email"],
    secret_types=[
        {"role": "token", "type": "token", "required": True},
        {"role": "ssh_key", "type": "private_key", "required": False},
    ],
    risk_level="medium",
    requires_approval=False,
    expected_domains=["github.com", "api.github.com"],
    recommended_agents=["coder", "devops"],
))

_register(IdentityTemplate(
    provider="vercel",
    display_name="Vercel Account",
    identity_type="developer_account",
    required_fields=["email"],
    optional_fields=[],
    secret_types=[
        {"role": "api_token", "type": "token", "required": True},
    ],
    risk_level="medium",
    requires_approval=False,
    expected_domains=["vercel.com", "api.vercel.com"],
    recommended_agents=["devops", "tech_builder"],
))

_register(IdentityTemplate(
    provider="supabase",
    display_name="Supabase Project",
    identity_type="developer_account",
    required_fields=["project_url"],
    optional_fields=["email"],
    secret_types=[
        {"role": "anon_key", "type": "api_key", "required": True},
        {"role": "service_role_key", "type": "api_key", "required": False},
        {"role": "db_password", "type": "credential", "required": False},
    ],
    risk_level="medium",
    requires_approval=False,
    expected_domains=["supabase.co", "supabase.com"],
    recommended_agents=["coder", "tech_builder"],
))

# ── SaaS ──

_register(IdentityTemplate(
    provider="notion",
    display_name="Notion Workspace",
    identity_type="saas_account",
    required_fields=["email"],
    optional_fields=["workspace_name"],
    secret_types=[
        {"role": "integration_token", "type": "token", "required": True},
    ],
    risk_level="low",
    requires_approval=False,
    expected_domains=["notion.so", "api.notion.com"],
    recommended_agents=["content_agent", "coder"],
))

_register(IdentityTemplate(
    provider="slack",
    display_name="Slack Workspace",
    identity_type="saas_account",
    required_fields=["workspace_name"],
    optional_fields=["email"],
    secret_types=[
        {"role": "bot_token", "type": "token", "required": True},
        {"role": "webhook_url", "type": "api_key", "required": False},
    ],
    risk_level="low",
    requires_approval=False,
    expected_domains=["slack.com", "api.slack.com"],
    recommended_agents=["customer_agent"],
))

# ── Social ──

_register(IdentityTemplate(
    provider="discord",
    display_name="Discord Bot",
    identity_type="social_account",
    required_fields=["bot_name"],
    optional_fields=["guild_id"],
    secret_types=[
        {"role": "bot_token", "type": "token", "required": True},
    ],
    risk_level="low",
    requires_approval=False,
    expected_domains=["discord.com", "discord.gg"],
    recommended_agents=["customer_agent"],
))

_register(IdentityTemplate(
    provider="telegram",
    display_name="Telegram Bot",
    identity_type="social_account",
    required_fields=["bot_name"],
    optional_fields=["bot_username"],
    secret_types=[
        {"role": "bot_token", "type": "token", "required": True},
    ],
    risk_level="low",
    requires_approval=False,
    expected_domains=["telegram.org", "api.telegram.org"],
    recommended_agents=["customer_agent"],
))

# ── Domain ──

_register(IdentityTemplate(
    provider="cloudflare",
    display_name="Cloudflare Account",
    identity_type="domain_account",
    required_fields=["email"],
    optional_fields=[],
    secret_types=[
        {"role": "api_token", "type": "token", "required": True},
        {"role": "global_key", "type": "api_key", "required": False},
    ],
    risk_level="high",
    requires_approval=True,
    expected_domains=["cloudflare.com", "api.cloudflare.com"],
    recommended_agents=["devops"],
))

_register(IdentityTemplate(
    provider="namecheap",
    display_name="Namecheap Account",
    identity_type="domain_account",
    required_fields=["username"],
    optional_fields=["email"],
    secret_types=[
        {"role": "api_key", "type": "api_key", "required": True},
        {"role": "password", "type": "credential", "required": False},
    ],
    risk_level="high",
    requires_approval=True,
    expected_domains=["namecheap.com", "api.namecheap.com"],
    recommended_agents=["devops"],
))

# ── API Providers ──

_register(IdentityTemplate(
    provider="openrouter",
    display_name="OpenRouter API",
    identity_type="api_account",
    required_fields=["email"],
    optional_fields=[],
    secret_types=[
        {"role": "api_key", "type": "api_key", "required": True},
    ],
    risk_level="medium",
    requires_approval=False,
    expected_domains=["openrouter.ai", "api.openrouter.ai"],
    recommended_agents=["*"],
))

_register(IdentityTemplate(
    provider="anthropic",
    display_name="Anthropic API",
    identity_type="api_account",
    required_fields=["email"],
    optional_fields=["org_id"],
    secret_types=[
        {"role": "api_key", "type": "api_key", "required": True},
    ],
    risk_level="medium",
    requires_approval=False,
    expected_domains=["anthropic.com", "api.anthropic.com"],
    recommended_agents=["*"],
))

_register(IdentityTemplate(
    provider="openai",
    display_name="OpenAI API",
    identity_type="api_account",
    required_fields=["email"],
    optional_fields=["org_id"],
    secret_types=[
        {"role": "api_key", "type": "api_key", "required": True},
    ],
    risk_level="medium",
    requires_approval=False,
    expected_domains=["openai.com", "api.openai.com"],
    recommended_agents=["*"],
))


# ── Template Registry ──

def get_template(provider: str) -> IdentityTemplate | None:
    """Get template by provider name."""
    return TEMPLATES.get(provider.lower())


def list_templates() -> list[dict]:
    """List all available templates."""
    return [t.to_dict() for t in TEMPLATES.values()]


def register_template(template: IdentityTemplate) -> None:
    """Register a custom template."""
    TEMPLATES[template.provider.lower()] = template


def template_providers() -> list[str]:
    """List all registered provider names."""
    return sorted(TEMPLATES.keys())
