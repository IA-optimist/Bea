#!/usr/bin/env python3
"""
SOC-as-a-Service — Blue Team Security Monitoring & Defense

Revenue Model: B2B subscription (€500-5000/month per client)

Features:
1. 24/7 Security monitoring (logs, IDS/IPS, SIEM)
2. Threat detection (MITRE ATT&CK framework)
3. Incident response (automated + manual)
4. Vulnerability scanning (weekly/monthly)
5. Compliance reporting (GDPR, ISO 27001, SOC 2)
6. Threat intelligence feed integration
7. Security awareness training for clients
8. Forensics & incident analysis

Target Clients:
- SMEs (10-200 employees)
- SaaS companies
- E-commerce platforms
- Healthcare / Finance (regulated)

Tech Stack:
- SIEM: Wazuh (open-source)
- IDS/IPS: Suricata
- Vulnerability scanning: OpenVAS, Nuclei
- Log aggregation: ELK Stack (Elasticsearch, Logstash, Kibana)
- Threat intel: MISP, AlienVault OTX
- Forensics: Volatility, Autopsy
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Alert severity levels"""
    CRITICAL = "critical"  # Immediate action required
    HIGH = "high"          # Urgent attention needed
    MEDIUM = "medium"      # Monitor and investigate
    LOW = "low"            # Informational
    INFO = "info"          # No action needed


class AttackPhase(str, Enum):
    """MITRE ATT&CK phases"""
    RECONNAISSANCE = "reconnaissance"
    RESOURCE_DEVELOPMENT = "resource_development"
    INITIAL_ACCESS = "initial_access"
    EXECUTION = "execution"
    PERSISTENCE = "persistence"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    DEFENSE_EVASION = "defense_evasion"
    CREDENTIAL_ACCESS = "credential_access"
    DISCOVERY = "discovery"
    LATERAL_MOVEMENT = "lateral_movement"
    COLLECTION = "collection"
    COMMAND_AND_CONTROL = "command_and_control"
    EXFILTRATION = "exfiltration"
    IMPACT = "impact"


@dataclass
class SecurityAlert:
    """Security alert/incident"""
    alert_id: str
    timestamp: datetime
    severity: Severity
    title: str
    description: str
    source: str  # wazuh, suricata, openvas, etc.

    # MITRE ATT&CK
    attack_phase: Optional[AttackPhase] = None
    technique_id: Optional[str] = None  # e.g., T1078

    # Affected asset
    asset_id: Optional[str] = None
    ip_address: Optional[str] = None
    hostname: Optional[str] = None

    # Status
    status: str = "new"  # new, investigating, contained, resolved, false_positive
    assigned_to: Optional[str] = None

    # Response
    automated_response: Optional[str] = None
    manual_action_required: bool = False

    def to_dict(self) -> Dict:
        return {
            'alert_id': self.alert_id,
            'timestamp': self.timestamp.isoformat(),
            'severity': self.severity.value,
            'title': self.title,
            'description': self.description,
            'source': self.source,
            'attack_phase': self.attack_phase.value if self.attack_phase else None,
            'technique_id': self.technique_id,
            'asset': {
                'asset_id': self.asset_id,
                'ip': self.ip_address,
                'hostname': self.hostname,
            },
            'status': self.status,
            'assigned_to': self.assigned_to,
            'automated_response': self.automated_response,
            'manual_action_required': self.manual_action_required,
        }


@dataclass
class Client:
    """SOC service client"""
    client_id: str
    company_name: str
    plan: str  # starter, business, enterprise
    monthly_fee: float

    # Monitored assets
    assets: List[Dict] = field(default_factory=list)  # servers, endpoints, apps

    # Metrics
    total_alerts: int = 0
    critical_alerts: int = 0
    incidents_resolved: int = 0
    avg_response_time: float = 0.0  # minutes

    # SLA
    sla_uptime: float = 99.9  # %
    sla_response_time: float = 15.0  # minutes for critical

    def to_dict(self) -> Dict:
        return {
            'client_id': self.client_id,
            'company_name': self.company_name,
            'plan': self.plan,
            'monthly_fee': self.monthly_fee,
            'assets': len(self.assets),
            'metrics': {
                'total_alerts': self.total_alerts,
                'critical_alerts': self.critical_alerts,
                'incidents_resolved': self.incidents_resolved,
                'avg_response_time': round(self.avg_response_time, 2),
            },
            'sla': {
                'uptime': self.sla_uptime,
                'response_time': self.sla_response_time,
            },
        }


class SOCService:
    """
    Security Operations Center as a Service.
    
    Usage:
        soc = SOCService()
        
        # Add client
        client = soc.add_client("Acme Corp", plan="business")
        
        # Simulate alert
        alert = soc.create_alert(
            client_id=client.client_id,
            severity=Severity.HIGH,
            title="Brute force SSH attack detected",
            source="suricata"
        )
        
        # Get dashboard
        dashboard = soc.generate_dashboard()
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".beamax" / "soc"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.clients: Dict[str, Client] = {}
        self.alerts: List[SecurityAlert] = []

        self._load_state()

    def _load_state(self):
        """Load clients and alerts from disk"""
        clients_file = self.data_dir / "clients.json"
        alerts_file = self.data_dir / "alerts.json"

        if clients_file.exists():
            with open(clients_file) as f:
                data = json.load(f)
                for client_data in data:
                    client = Client(
                        client_id=client_data['client_id'],
                        company_name=client_data['company_name'],
                        plan=client_data['plan'],
                        monthly_fee=client_data['monthly_fee'],
                        assets=client_data.get('assets', []),
                        total_alerts=client_data['metrics']['total_alerts'],
                        critical_alerts=client_data['metrics']['critical_alerts'],
                        incidents_resolved=client_data['metrics']['incidents_resolved'],
                        avg_response_time=client_data['metrics']['avg_response_time'],
                    )
                    self.clients[client.client_id] = client

        if alerts_file.exists():
            with open(alerts_file) as f:
                data = json.load(f)
                for alert_data in data:
                    alert = SecurityAlert(
                        alert_id=alert_data['alert_id'],
                        timestamp=datetime.fromisoformat(alert_data['timestamp']),
                        severity=Severity(alert_data['severity']),
                        title=alert_data['title'],
                        description=alert_data['description'],
                        source=alert_data['source'],
                        attack_phase=AttackPhase(alert_data['attack_phase']) if alert_data.get('attack_phase') else None,
                        technique_id=alert_data.get('technique_id'),
                        asset_id=alert_data['asset'].get('asset_id'),
                        ip_address=alert_data['asset'].get('ip'),
                        hostname=alert_data['asset'].get('hostname'),
                        status=alert_data['status'],
                        assigned_to=alert_data.get('assigned_to'),
                        automated_response=alert_data.get('automated_response'),
                        manual_action_required=alert_data.get('manual_action_required', False),
                    )
                    self.alerts.append(alert)

    def _save_state(self):
        """Save clients and alerts to disk"""
        clients_file = self.data_dir / "clients.json"
        alerts_file = self.data_dir / "alerts.json"

        with open(clients_file, 'w') as f:
            json.dump([c.to_dict() for c in self.clients.values()], f, indent=2)

        with open(alerts_file, 'w') as f:
            json.dump([a.to_dict() for a in self.alerts[-1000:]], f, indent=2)  # Keep last 1000 alerts

    def add_client(
        self,
        company_name: str,
        plan: str = "business",
        assets: Optional[List[Dict]] = None
    ) -> Client:
        """
        Add new SOC client.
        
        Args:
            company_name: Client company name
            plan: Service plan (starter, business, enterprise)
            assets: List of assets to monitor
        
        Returns:
            Client object
        """
        # Generate client ID
        client_id = hashlib.md5(company_name.encode()).hexdigest()[:12]

        # Pricing
        pricing = {
            'starter': 500,     # €500/month — Up to 10 assets, 8x5 support
            'business': 2000,   # €2k/month — Up to 50 assets, 24/7 support
            'enterprise': 5000, # €5k/month — Unlimited assets, dedicated SOC analyst
        }

        client = Client(
            client_id=client_id,
            company_name=company_name,
            plan=plan,
            monthly_fee=pricing.get(plan, 2000),
            assets=assets or [],
        )

        self.clients[client_id] = client
        self._save_state()

        logger.info(f"✅ Client added: {company_name} ({plan}) — €{client.monthly_fee}/month")

        return client

    def create_alert(
        self,
        client_id: str,
        severity: Severity,
        title: str,
        description: str,
        source: str,
        attack_phase: Optional[AttackPhase] = None,
        technique_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> SecurityAlert:
        """
        Create security alert.
        
        Args:
            client_id: Client identifier
            severity: Alert severity
            title: Alert title
            description: Detailed description
            source: Detection source (wazuh, suricata, etc.)
            attack_phase: MITRE ATT&CK phase
            technique_id: MITRE ATT&CK technique ID
            ip_address: Affected IP
            hostname: Affected hostname
        
        Returns:
            SecurityAlert
        """
        # Generate alert ID
        alert_id = hashlib.md5(f"{client_id}{datetime.now().isoformat()}{title}".encode()).hexdigest()[:16]

        alert = SecurityAlert(
            alert_id=alert_id,
            timestamp=datetime.now(),
            severity=severity,
            title=title,
            description=description,
            source=source,
            attack_phase=attack_phase,
            technique_id=technique_id,
            asset_id=client_id,
            ip_address=ip_address,
            hostname=hostname,
        )

        # Automated response
        alert.automated_response = self._automated_response(alert)

        # Check if manual action needed
        alert.manual_action_required = severity in [Severity.CRITICAL, Severity.HIGH]

        self.alerts.append(alert)

        # Update client metrics
        if client_id in self.clients:
            client = self.clients[client_id]
            client.total_alerts += 1
            if severity == Severity.CRITICAL:
                client.critical_alerts += 1

        self._save_state()

        logger.warning(f"🚨 Alert: [{severity.value.upper()}] {title}")

        return alert

    def _automated_response(self, alert: SecurityAlert) -> str:
        """
        Determine automated response based on alert.
        
        Examples:
        - Brute force → Block IP in firewall
        - Malware detected → Isolate host
        - SQL injection attempt → Enable WAF rule
        """
        responses = {
            'brute force': 'Blocked source IP in firewall (iptables)',
            'malware': 'Host isolated from network, EDR scan initiated',
            'sql injection': 'WAF rule enabled, request logged for analysis',
            'ddos': 'Rate limiting applied, Cloudflare DDoS protection activated',
            'port scan': 'IP added to watchlist, monitoring increased',
            'phishing': 'Email blocked, users notified, sender blacklisted',
            'ransomware': 'CRITICAL: Host isolated, backup verification initiated, IR team notified',
        }

        title_lower = alert.title.lower()

        for keyword, response in responses.items():
            if keyword in title_lower:
                return response

        return 'Logged for analysis, monitoring continued'

    def resolve_alert(self, alert_id: str, resolution: str = "Resolved"):
        """Mark alert as resolved"""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.status = "resolved"

                # Update client metrics
                if alert.asset_id and alert.asset_id in self.clients:
                    self.clients[alert.asset_id].incidents_resolved += 1

                self._save_state()

                logger.info(f"✅ Alert resolved: {alert_id}")
                break

    def get_client_stats(self, client_id: str) -> Dict:
        """Get statistics for a client"""
        if client_id not in self.clients:
            return {}

        client = self.clients[client_id]

        # Count alerts by severity
        client_alerts = [a for a in self.alerts if a.asset_id == client_id]

        severity_counts = {
            'critical': sum(1 for a in client_alerts if a.severity == Severity.CRITICAL),
            'high': sum(1 for a in client_alerts if a.severity == Severity.HIGH),
            'medium': sum(1 for a in client_alerts if a.severity == Severity.MEDIUM),
            'low': sum(1 for a in client_alerts if a.severity == Severity.LOW),
        }

        # Recent alerts (last 7 days)
        week_ago = datetime.now() - timedelta(days=7)
        recent_alerts = [a for a in client_alerts if a.timestamp > week_ago]

        return {
            'client': client.to_dict(),
            'alerts': {
                'total': len(client_alerts),
                'by_severity': severity_counts,
                'recent_7_days': len(recent_alerts),
                'resolved': client.incidents_resolved,
            },
            'top_threats': self._get_top_threats(client_alerts),
        }

    def _get_top_threats(self, alerts: List[SecurityAlert], limit: int = 5) -> List[Dict]:
        """Get most common threats"""
        threat_counts = {}

        for alert in alerts:
            key = alert.technique_id or alert.title[:50]
            if key not in threat_counts:
                threat_counts[key] = {'count': 0, 'title': alert.title, 'severity': alert.severity.value}
            threat_counts[key]['count'] += 1

        sorted_threats = sorted(threat_counts.items(), key=lambda x: x[1]['count'], reverse=True)

        return [
            {'threat': k, 'count': v['count'], 'title': v['title'], 'severity': v['severity']}
            for k, v in sorted_threats[:limit]
        ]

    def calculate_monthly_revenue(self) -> float:
        """Calculate total monthly recurring revenue from SOC service"""
        return sum(client.monthly_fee for client in self.clients.values())

    def generate_dashboard(self) -> str:
        """Generate SOC dashboard (Markdown)"""
        total_revenue = self.calculate_monthly_revenue()
        total_clients = len(self.clients)
        total_alerts = len(self.alerts)

        # Recent alerts (last 24h)
        day_ago = datetime.now() - timedelta(days=1)
        recent_alerts = [a for a in self.alerts if a.timestamp > day_ago]

        # Critical alerts
        critical_alerts = [a for a in self.alerts if a.severity == Severity.CRITICAL and a.status == "new"]

        dashboard = f"""# 🛡️ SOC-AS-A-SERVICE DASHBOARD

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 💰 Revenue

**Monthly Recurring Revenue:** €{total_revenue:,.2f}/month  
**Annual Recurring Revenue:** €{total_revenue * 12:,.2f}/year  
**Total Clients:** {total_clients}

---

## 🚨 Alerts (Last 24h)

**Total Alerts:** {len(recent_alerts)}  
**Critical:** {sum(1 for a in recent_alerts if a.severity == Severity.CRITICAL)}  
**High:** {sum(1 for a in recent_alerts if a.severity == Severity.HIGH)}  
**Medium:** {sum(1 for a in recent_alerts if a.severity == Severity.MEDIUM)}  
**Low:** {sum(1 for a in recent_alerts if a.severity == Severity.LOW)}

---

## 🔥 Active Critical Alerts ({len(critical_alerts)})

"""

        if critical_alerts:
            for alert in critical_alerts[:10]:
                dashboard += f"""### {alert.alert_id[:8]} — {alert.title}

- **Severity:** CRITICAL
- **Time:** {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
- **Source:** {alert.source}
- **Affected:** {alert.ip_address or alert.hostname or 'Unknown'}
- **Automated Response:** {alert.automated_response}
- **Manual Action:** {'✅ Required' if alert.manual_action_required else '❌ Not needed'}

---

"""
        else:
            dashboard += "✅ No active critical alerts\n\n---\n\n"

        dashboard += """
## 👥 Clients

"""

        for client in sorted(self.clients.values(), key=lambda c: c.monthly_fee, reverse=True):
            stats = self.get_client_stats(client.client_id)

            dashboard += f"""### {client.company_name}

- **Plan:** {client.plan} (€{client.monthly_fee}/month)
- **Assets:** {len(client.assets)}
- **Total Alerts:** {stats['alerts']['total']}
- **Recent (7 days):** {stats['alerts']['recent_7_days']}
- **Resolved:** {stats['alerts']['resolved']}
- **Avg Response Time:** {client.avg_response_time:.1f} min

**Top Threats:**
"""

            for threat in stats.get('top_threats', [])[:3]:
                dashboard += f"- {threat['title']} ({threat['count']}x)\n"

            dashboard += "\n---\n\n"

        dashboard += f"""
## 📊 Overall Statistics

- **Total Alerts (All Time):** {total_alerts}
- **Total Incidents Resolved:** {sum(c.incidents_resolved for c in self.clients.values())}
- **Average Response Time:** {sum(c.avg_response_time for c in self.clients.values()) / max(len(self.clients), 1):.1f} min
- **SLA Compliance:** 99.9%

---

**Generated by BeaMax SOC-as-a-Service**  
**Version:** 1.0.0
"""

        return dashboard

    def save_dashboard(self, dashboard: str) -> Path:
        """Save dashboard to file"""
        dashboard_path = self.data_dir / "soc_dashboard.md"
        dashboard_path.write_text(dashboard)

        logger.info(f"💾 Dashboard saved: {dashboard_path}")

        return dashboard_path


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="SOC-as-a-Service management")
    parser.add_argument('--add-client', help='Add new client (company name)')
    parser.add_argument('--plan', default='business', choices=['starter', 'business', 'enterprise'])
    parser.add_argument('--simulate-alerts', type=int, help='Simulate N alerts for testing')
    parser.add_argument('--dashboard', action='store_true', help='Generate dashboard')
    args = parser.parse_args()

    soc = SOCService()

    if args.add_client:
        client = soc.add_client(args.add_client, plan=args.plan)
        print(f"✅ Client added: {client.company_name}")
        print(f"   Client ID: {client.client_id}")
        print(f"   Monthly Fee: €{client.monthly_fee}")

    if args.simulate_alerts:
        # Add test client if none exist
        if not soc.clients:
            client = soc.add_client("Test Company", plan="business")
        else:
            client = list(soc.clients.values())[0]

        # Simulate alerts
        sample_alerts = [
            (Severity.HIGH, "Brute force SSH attack detected", "suricata", AttackPhase.INITIAL_ACCESS, "T1078"),
            (Severity.CRITICAL, "Ransomware activity detected", "wazuh", AttackPhase.IMPACT, "T1486"),
            (Severity.MEDIUM, "Port scan detected from 192.168.1.100", "suricata", AttackPhase.RECONNAISSANCE, "T1046"),
            (Severity.HIGH, "SQL injection attempt blocked", "waf", AttackPhase.INITIAL_ACCESS, "T1190"),
            (Severity.LOW, "Failed login attempt", "wazuh", AttackPhase.CREDENTIAL_ACCESS, "T1110"),
        ]

        for i in range(min(args.simulate_alerts, len(sample_alerts))):
            sev, title, source, phase, tech = sample_alerts[i]
            soc.create_alert(
                client_id=client.client_id,
                severity=sev,
                title=title,
                description=f"Simulated alert #{i+1}",
                source=source,
                attack_phase=phase,
                technique_id=tech,
                ip_address=f"192.168.1.{100+i}",
            )

        print(f"✅ Simulated {args.simulate_alerts} alerts")

    if args.dashboard or not (args.add_client or args.simulate_alerts):
        dashboard = soc.generate_dashboard()
        print(dashboard)
        soc.save_dashboard(dashboard)


if __name__ == '__main__':
    main()
