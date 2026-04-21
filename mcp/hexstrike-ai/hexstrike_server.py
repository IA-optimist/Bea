#!/usr/bin/env python3
"""
HexStrike AI - Advanced Penetration Testing Framework Server

Enhanced with AI-Powered Intelligence & Automation
🚀 Bug Bounty | CTF | Red Team | Security Research

RECENT ENHANCEMENTS (v6.0):
✅ Complete color consistency with reddish hacker theme
✅ Removed duplicate classes (PythonEnvironmentManager, CVEIntelligenceManager)
✅ Enhanced visual output with ModernVisualEngine
✅ Organized code structure with proper section headers
✅ 100+ security tools with intelligent parameter optimization
✅ AI-driven decision engine for tool selection
✅ Advanced error handling and recovery systems

Architecture: Two-script system (hexstrike_server.py + hexstrike_mcp.py)
Framework: FastMCP integration for AI agent communication
"""

import argparse
import logging
import os
import sys
import traceback
import threading
import time
from flask import Flask, request, jsonify

# ============================================================================
# LOGGING CONFIGURATION (MUST BE FIRST)
# ============================================================================

# Configure logging with fallback for permission issues
try:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('hexstrike.log')
        ]
    )
except PermissionError:
    # Fallback to console-only logging if file creation fails
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
logger = logging.getLogger(__name__)

# Flask app configuration
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# API Configuration
API_PORT = int(os.environ.get('HEXSTRIKE_PORT', 8888))
API_HOST = os.environ.get('HEXSTRIKE_HOST', '127.0.0.1')

# ============================================================================
# MODERN VISUAL ENGINE (v2.0 ENHANCEMENT)
# ============================================================================

# ── ModernVisualEngine déplacée dans mcp/hexstrike-ai/visual_engine.py ──
# Ré-export pour backward-compat — 222 références internes à
# ModernVisualEngine.COLORS[...] continuent de fonctionner.
from visual_engine import ModernVisualEngine  # noqa: E402

# ── Attack intelligence subsystem déplacé dans attack_intelligence.py ──
# 6 classes : TargetType, TechnologyStack, TargetProfile, AttackStep,
# AttackChain, IntelligentDecisionEngine (~1100 lignes extraites).
from attack_intelligence import (  # noqa: E402,F401
    TargetType, TechnologyStack, TargetProfile,
    AttackStep, AttackChain, IntelligentDecisionEngine,
)





# ── Error handling déplacé dans error_handling.py ──
from error_handling import (  # noqa: E402,F401
    ErrorType, RecoveryAction, ErrorContext, RecoveryStrategy,
    IntelligentErrorHandler, GracefulDegradation,
)







# Global error handler and degradation manager instances

# ============================================================================
# BUG BOUNTY HUNTING SPECIALIZED WORKFLOWS (v6.0 ENHANCEMENT)
# ============================================================================

# ── Bug bounty déplacé dans bug_bounty.py ──
from bug_bounty import (  # noqa: E402,F401
    BugBountyTarget, BugBountyWorkflowManager, FileUploadTestingFramework,
)



# ============================================================================

# ── CTF subsystem déplacé dans ctf.py ──
from ctf import (  # noqa: E402,F401
    CTFChallenge, CTFWorkflowManager, CTFToolManager,
    CTFChallengeAutomator, CTFTeamCoordinator,
)



# ============================================================================


# ============================================================================

# ── Detection/recovery déplacé dans detection.py ──
from detection import (  # noqa: E402,F401
    TechnologyDetector, RateLimitDetector,
    FailureRecoverySystem, ParameterOptimizer,
)








# ── Enhanced process + dashboard déplacés dans enhanced_process.py ──
from enhanced_process import (  # noqa: E402,F401
    PerformanceDashboard, EnhancedProcessManager,
)




# Global instances
# (singleton moved to router)
# (singleton moved to router)
failure_recovery = FailureRecoverySystem()
performance_monitor = PerformanceMonitor()
parameter_optimizer = ParameterOptimizer()
# (singleton moved to router)

# Global CTF framework instances

# ============================================================================
# PROCESS MANAGEMENT FOR COMMAND TERMINATION (v5.0 ENHANCEMENT)
# ============================================================================

# Process management for command termination
active_processes = {}  # pid -> process info
process_lock = threading.Lock()



# ── CVEIntelligenceManager déplacé dans cve_intelligence.py ──
from cve_intelligence import CVEIntelligenceManager  # noqa: E402,F401

# ── Tools_misc (5 classes) déplacé dans tools_misc.py ──
from tools_misc import (  # noqa: E402,F401
    ColoredFormatter, FileOperationsManager,
    HTTPTestingFramework, BrowserAgent, AIPayloadGenerator,
)


# Enhanced logging setup
def setup_logging():
    """Setup enhanced logging with colors and formatting"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter(
        "[🔥 HexStrike AI] %(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(console_handler)

    return logger

# Configuration (using existing API_PORT from top of file)
DEBUG_MODE = os.environ.get("DEBUG_MODE", "0").lower() in ("1", "true", "yes", "y")
COMMAND_TIMEOUT = 300  # 5 minutes default timeout
# ── HexStrikeCache déplacé dans mcp/hexstrike-ai/hex_cache.py ──
# Ré-export pour backward-compat ; cache = singleton shared.
from hex_cache import cache, CACHE_SIZE, CACHE_TTL  # noqa: E402


# ── TelemetryCollector, ResourceMonitor, PerformanceMonitor déplacés dans monitoring.py ──
from monitoring import TelemetryCollector, ResourceMonitor, PerformanceMonitor  # noqa: E402,F401


# ── Command execution subsystem déplacé dans command_execution.py ──
from command_execution import (  # noqa: E402,F401
    EnhancedCommandExecutor, AIExploitGenerator, VulnerabilityCorrelator,
)


# ============================================================================
# DUPLICATE CLASSES REMOVED - Using the first definitions above
# ============================================================================

# ============================================================================
# AI-POWERED EXPLOIT GENERATION SYSTEM (v6.0 ENHANCEMENT)
# ============================================================================
#
# This section contains advanced AI-powered exploit generation capabilities
# for automated vulnerability exploitation and proof-of-concept development.
#
# Features:
# - Automated exploit template generation from CVE data
# - Multi-architecture support (x86, x64, ARM)
# - Evasion technique integration
# - Custom payload generation
# - Exploit effectiveness scoring
#
# ============================================================================





# Global intelligence managers
# (singleton moved to router)
# (singleton moved to router)
# (singleton moved to router)

# ── Execution framework déplacé dans execution_framework.py ──
# 4 helpers + 2 singletons (error_handler, degradation_manager).
from execution_framework import (  # noqa: E402,F401
    execute_command, execute_command_with_recovery,
    _rebuild_command_with_params, _determine_operation_type,
    error_handler, degradation_manager,
)





# File Operations Manager

# Global file operations manager
# (singleton moved to router)

# API Routes

@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint with comprehensive tool detection"""

    essential_tools = [
        "nmap", "gobuster", "dirb", "nikto", "sqlmap", "hydra", "john", "hashcat"
    ]

    network_tools = [
        "rustscan", "masscan", "autorecon", "nbtscan", "arp-scan", "responder",
        "nxc", "enum4linux-ng", "rpcclient", "enum4linux"
    ]

    web_security_tools = [
        "ffuf", "feroxbuster", "dirsearch", "dotdotpwn", "xsser", "wfuzz",
        "gau", "waybackurls", "arjun", "paramspider", "x8", "jaeles", "dalfox",
        "httpx", "wafw00f", "burpsuite", "zaproxy", "katana", "hakrawler"
    ]

    vuln_scanning_tools = [
        "nuclei", "wpscan", "graphql-scanner", "jwt-analyzer"
    ]

    password_tools = [
        "medusa", "patator", "hash-identifier", "ophcrack", "hashcat-utils"
    ]

    binary_tools = [
        "gdb", "radare2", "binwalk", "ropgadget", "checksec", "objdump",
        "ghidra", "pwntools", "one-gadget", "ropper", "angr", "libc-database",
        "pwninit"
    ]

    forensics_tools = [
        "volatility3", "vol", "steghide", "hashpump", "foremost", "exiftool",
        "strings", "xxd", "file", "photorec", "testdisk", "scalpel", "bulk-extractor",
        "stegsolve", "zsteg", "outguess"
    ]

    cloud_tools = [
        "prowler", "scout-suite", "trivy", "kube-hunter", "kube-bench",
        "docker-bench-security", "checkov", "terrascan", "falco", "clair"
    ]

    osint_tools = [
        "amass", "subfinder", "fierce", "dnsenum", "theharvester", "sherlock",
        "social-analyzer", "recon-ng", "maltego", "spiderfoot", "shodan-cli",
        "censys-cli", "have-i-been-pwned"
    ]

    exploitation_tools = [
        "metasploit", "exploit-db", "searchsploit"
    ]

    api_tools = [
        "api-schema-analyzer", "postman", "insomnia", "curl", "httpie", "anew", "qsreplace", "uro"
    ]

    wireless_tools = [
        "kismet", "wireshark", "tshark", "tcpdump"
    ]

    additional_tools = [
        "smbmap", "volatility", "sleuthkit", "autopsy", "evil-winrm",
        "paramspider", "airmon-ng", "airodump-ng", "aireplay-ng", "aircrack-ng",
        "msfvenom", "msfconsole", "graphql-scanner", "jwt-analyzer"
    ]

    all_tools = (
        essential_tools + network_tools + web_security_tools + vuln_scanning_tools +
        password_tools + binary_tools + forensics_tools + cloud_tools +
        osint_tools + exploitation_tools + api_tools + wireless_tools + additional_tools
    )
    tools_status = {}

    for tool in all_tools:
        try:
            result = execute_command(f"which {tool}", use_cache=True)
            tools_status[tool] = result["success"]
        except Exception:
            tools_status[tool] = False

    all_essential_tools_available = all(tools_status[tool] for tool in essential_tools)

    category_stats = {
        "essential": {"total": len(essential_tools), "available": sum(1 for tool in essential_tools if tools_status.get(tool, False))},
        "network": {"total": len(network_tools), "available": sum(1 for tool in network_tools if tools_status.get(tool, False))},
        "web_security": {"total": len(web_security_tools), "available": sum(1 for tool in web_security_tools if tools_status.get(tool, False))},
        "vuln_scanning": {"total": len(vuln_scanning_tools), "available": sum(1 for tool in vuln_scanning_tools if tools_status.get(tool, False))},
        "password": {"total": len(password_tools), "available": sum(1 for tool in password_tools if tools_status.get(tool, False))},
        "binary": {"total": len(binary_tools), "available": sum(1 for tool in binary_tools if tools_status.get(tool, False))},
        "forensics": {"total": len(forensics_tools), "available": sum(1 for tool in forensics_tools if tools_status.get(tool, False))},
        "cloud": {"total": len(cloud_tools), "available": sum(1 for tool in cloud_tools if tools_status.get(tool, False))},
        "osint": {"total": len(osint_tools), "available": sum(1 for tool in osint_tools if tools_status.get(tool, False))},
        "exploitation": {"total": len(exploitation_tools), "available": sum(1 for tool in exploitation_tools if tools_status.get(tool, False))},
        "api": {"total": len(api_tools), "available": sum(1 for tool in api_tools if tools_status.get(tool, False))},
        "wireless": {"total": len(wireless_tools), "available": sum(1 for tool in wireless_tools if tools_status.get(tool, False))},
        "additional": {"total": len(additional_tools), "available": sum(1 for tool in additional_tools if tools_status.get(tool, False))}
    }

    return jsonify({
        "status": "healthy",
        "message": "HexStrike AI Tools API Server is operational",
        "version": "6.0.0",
        "tools_status": tools_status,
        "all_essential_tools_available": all_essential_tools_available,
        "total_tools_available": sum(1 for tool, available in tools_status.items() if available),
        "total_tools_count": len(all_tools),
        "category_stats": category_stats,
        "cache_stats": cache.get_stats(),
        "telemetry": telemetry.get_stats(),
        "uptime": time.time() - telemetry.stats["start_time"]
    })

@app.route("/api/command", methods=["POST"])
def generic_command():
    """Execute any command provided in the request with enhanced logging"""
    try:
        params = request.json
        command = params.get("command", "")
        use_cache = params.get("use_cache", True)

        if not command:
            logger.warning("⚠️  Command endpoint called without command parameter")
            return jsonify({
                "error": "Command parameter is required"
            }), 400

        result = execute_command(command, use_cache=use_cache)
        return jsonify(result)
    except Exception as e:
        logger.error(f"💥 Error in command endpoint: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": f"Server error: {str(e)}"
        }), 500

# File Operations API Endpoints

# ── files endpoints (4 routes) déplacés dans router_files.py ──
from router_files import files_bp  # noqa: E402,F401
app.register_blueprint(files_bp)





# Payload Generation Endpoint
# ── payloads endpoints (1 routes) déplacés dans router_payloads.py ──
from router_payloads import payloads_bp  # noqa: E402,F401
app.register_blueprint(payloads_bp)


# Cache Management Endpoint
# ── cache endpoints (2 routes) déplacés dans router_cache.py ──
from router_cache import cache_bp  # noqa: E402,F401
app.register_blueprint(cache_bp)



# Telemetry Endpoint
@app.route("/api/telemetry", methods=["GET"])
def get_telemetry():
    """Get system telemetry"""
    return jsonify(telemetry.get_stats())

# ============================================================================
# PROCESS MANAGEMENT API ENDPOINTS (v5.0 ENHANCEMENT)
# ============================================================================

# ── processes endpoints (6 routes) déplacés dans router_processes.py ──
from router_processes import processes_bp  # noqa: E402,F401
app.register_blueprint(processes_bp)







# ── visual endpoints (3 routes) déplacés dans router_visual.py ──
from router_visual import visual_bp  # noqa: E402,F401
app.register_blueprint(visual_bp)




# ============================================================================
# INTELLIGENT DECISION ENGINE API ENDPOINTS
# ============================================================================

# ── intelligence endpoints (6 routes) déplacés dans router_intelligence.py ──
from router_intelligence import intelligence_bp  # noqa: E402,F401
app.register_blueprint(intelligence_bp)






# Helper functions for intelligent smart scan tool execution
# ── Tool wrappers (16 execute_*_scan) déplacés dans tool_wrappers.py ──
from tool_wrappers import (  # noqa: E402,F401
    execute_nmap_scan, execute_gobuster_scan, execute_nuclei_scan,
    execute_nikto_scan, execute_sqlmap_scan, execute_ffuf_scan,
    execute_feroxbuster_scan, execute_katana_scan, execute_httpx_scan,
    execute_wpscan_scan, execute_dirsearch_scan, execute_arjun_scan,
    execute_paramspider_scan, execute_dalfox_scan, execute_amass_scan,
    execute_subfinder_scan,
)


















# ============================================================================
# BUG BOUNTY HUNTING WORKFLOW API ENDPOINTS
# ============================================================================

# ── bugbounty endpoints (6 routes) déplacés dans router_bugbounty.py ──
from router_bugbounty import bugbounty_bp  # noqa: E402,F401
app.register_blueprint(bugbounty_bp)







# ============================================================================
# SECURITY TOOLS API ENDPOINTS
# ============================================================================

# ── Tools endpoints (90 routes) déplacés dans router_tools.py ──
from router_tools import tools_bp, http_framework, browser_agent  # noqa: E402,F401
app.register_blueprint(tools_bp)




# ============================================================================
# CLOUD SECURITY TOOLS
# ============================================================================



# ============================================================================
# ENHANCED CLOUD AND CONTAINER SECURITY TOOLS (v6.0)
# ============================================================================

























# ============================================================================
# ENHANCED NETWORK PENETRATION TESTING TOOLS (v6.0)
# ============================================================================












# ============================================================================
# BINARY ANALYSIS & REVERSE ENGINEERING TOOLS
# ============================================================================









# ============================================================================
# ENHANCED BINARY ANALYSIS AND EXPLOITATION FRAMEWORK (v6.0)
# ============================================================================









# ============================================================================
# ADDITIONAL WEB SECURITY TOOLS
# ============================================================================





# ============================================================================
# ENHANCED WEB APPLICATION SECURITY TOOLS (v6.0)
# ============================================================================














# ============================================================================
# ADVANCED WEB SECURITY TOOLS CONTINUED
# ============================================================================

# ============================================================================
# ENHANCED HTTP TESTING FRAMEWORK (BURP SUITE ALTERNATIVE)
# ============================================================================



# Global instances
# (singleton moved to router)
# (singleton moved to router)








# Python Environment Management Endpoints
# ── python endpoints (2 routes) déplacés dans router_python.py ──
from router_python import python_bp  # noqa: E402,F401
app.register_blueprint(python_bp)



# ============================================================================
# AI-POWERED PAYLOAD GENERATION (v5.0 ENHANCEMENT) UNDER DEVELOPMENT
# ============================================================================


# Global AI payload generator
# (singleton moved to router)

# ── ai endpoints (3 routes) déplacés dans router_ai.py ──
from router_ai import ai_bp  # noqa: E402,F401
app.register_blueprint(ai_bp)



# ============================================================================
# ADVANCED API TESTING TOOLS (v5.0 ENHANCEMENT)
# ============================================================================





# ============================================================================
# ADVANCED CTF TOOLS (v5.0 ENHANCEMENT)
# ============================================================================






# ============================================================================
# BUG BOUNTY RECONNAISSANCE TOOLS (v5.0 ENHANCEMENT)
# ============================================================================


# ============================================================================
# ADVANCED VULNERABILITY INTELLIGENCE API ENDPOINTS (v6.0 ENHANCEMENT)
# ============================================================================

# ── vuln_intel endpoints (5 routes) déplacés dans router_vuln_intel.py ──
from router_vuln_intel import vuln_intel_bp  # noqa: E402,F401
app.register_blueprint(vuln_intel_bp)







# ============================================================================
# CTF COMPETITION EXCELLENCE FRAMEWORK API ENDPOINTS (v8.0 ENHANCEMENT)
# ============================================================================

# ── CTF endpoints (7 routes) déplacés dans router_ctf.py ──
# Enregistré via app.register_blueprint(ctf_bp) plus bas.
from router_ctf import (  # noqa: E402,F401
    ctf_bp,
    ctf_manager, ctf_tools, ctf_automator, ctf_coordinator,
)
app.register_blueprint(ctf_bp)








# ============================================================================
# ADVANCED PROCESS MANAGEMENT API ENDPOINTS (v10.0 ENHANCEMENT)
# ============================================================================

# ── process endpoints (11 routes) déplacés dans router_process.py ──
from router_process import process_bp  # noqa: E402,F401
app.register_blueprint(process_bp)












# ============================================================================
# BANNER AND STARTUP CONFIGURATION
# ============================================================================

# ============================================================================
# INTELLIGENT ERROR HANDLING API ENDPOINTS
# ============================================================================

# ── error_handling endpoints (7 routes) déplacés dans router_error_handling.py ──
from router_error_handling import error_handling_bp  # noqa: E402,F401
app.register_blueprint(error_handling_bp)








# Create the banner after all classes are defined
BANNER = ModernVisualEngine.create_banner()

if __name__ == "__main__":
    # Display the beautiful new banner
    print(BANNER)

    parser = argparse.ArgumentParser(description="Run the HexStrike AI API Server")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--port", type=int, default=API_PORT, help=f"Port for the API server (default: {API_PORT})")
    args = parser.parse_args()

    if args.debug:
        DEBUG_MODE = True
        logger.setLevel(logging.DEBUG)

    if args.port != API_PORT:
        API_PORT = args.port

    # Enhanced startup messages with beautiful formatting
    startup_info = f"""
{ModernVisualEngine.COLORS['MATRIX_GREEN']}{ModernVisualEngine.COLORS['BOLD']}╭─────────────────────────────────────────────────────────────────────────────╮{ModernVisualEngine.COLORS['RESET']}
{ModernVisualEngine.COLORS['BOLD']}│{ModernVisualEngine.COLORS['RESET']} {ModernVisualEngine.COLORS['NEON_BLUE']}🚀 Starting HexStrike AI Tools API Server{ModernVisualEngine.COLORS['RESET']}
{ModernVisualEngine.COLORS['BOLD']}├─────────────────────────────────────────────────────────────────────────────┤{ModernVisualEngine.COLORS['RESET']}
{ModernVisualEngine.COLORS['BOLD']}│{ModernVisualEngine.COLORS['RESET']} {ModernVisualEngine.COLORS['CYBER_ORANGE']}🌐 Port:{ModernVisualEngine.COLORS['RESET']} {API_PORT}
{ModernVisualEngine.COLORS['BOLD']}│{ModernVisualEngine.COLORS['RESET']} {ModernVisualEngine.COLORS['WARNING']}🔧 Debug Mode:{ModernVisualEngine.COLORS['RESET']} {DEBUG_MODE}
{ModernVisualEngine.COLORS['BOLD']}│{ModernVisualEngine.COLORS['RESET']} {ModernVisualEngine.COLORS['ELECTRIC_PURPLE']}💾 Cache Size:{ModernVisualEngine.COLORS['RESET']} {CACHE_SIZE} | TTL: {CACHE_TTL}s
{ModernVisualEngine.COLORS['BOLD']}│{ModernVisualEngine.COLORS['RESET']} {ModernVisualEngine.COLORS['TERMINAL_GRAY']}⏱️  Command Timeout:{ModernVisualEngine.COLORS['RESET']} {COMMAND_TIMEOUT}s
{ModernVisualEngine.COLORS['BOLD']}│{ModernVisualEngine.COLORS['RESET']} {ModernVisualEngine.COLORS['MATRIX_GREEN']}✨ Enhanced Visual Engine:{ModernVisualEngine.COLORS['RESET']} Active
{ModernVisualEngine.COLORS['MATRIX_GREEN']}{ModernVisualEngine.COLORS['BOLD']}╰─────────────────────────────────────────────────────────────────────────────╯{ModernVisualEngine.COLORS['RESET']}
"""

    for line in startup_info.strip().split('\n'):
        if line.strip():
            logger.info(line)

    app.run(host="0.0.0.0", port=API_PORT, debug=DEBUG_MODE)
