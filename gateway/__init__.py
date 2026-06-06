"""gateway — passerelle de messagerie multi-plateformes (Axe 4, inspiration Hermes).

Cœur agnostique : `GatewayRunner` route les messages entrants (depuis n'importe
quel `PlatformAdapter`) vers un handler unique (le cœur agent), avec autorisation
et clé de session. Les adaptateurs concrets (Telegram, Discord…) sont des étapes
opt-in qui n'altèrent pas le cœur.
"""
from gateway.base import MessageEvent, PlatformAdapter
from gateway.runner import GatewayRunner

__all__ = ["MessageEvent", "PlatformAdapter", "GatewayRunner"]
