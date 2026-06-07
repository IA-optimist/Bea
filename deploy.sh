#!/usr/bin/env bash
#
# BeaMax Production Deployment Script
# ========================================
#
# TARGET: 77.42.40.146 (production VPS)
# DOMAIN: bea.beamaxapp.co.uk
# STACK: Docker Compose (PostgreSQL, Redis, Qdrant, API, Frontend)
#
# USAGE:
#   ./deploy.sh           # Full deployment
#   ./deploy.sh --fast    # Skip tests (fast deploy)
#   ./deploy.sh --rollback # Rollback to previous version
#

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
REPO_DIR="/root/Beamax-master"
BRANCH="main"
COMPOSE_FILE="docker-compose.yml"
API_CONTAINER="beamax-api"
HEALTH_ENDPOINT="http://localhost:8000/health"
MAX_RETRIES=30
RETRY_DELAY=2

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ── Helper Functions ──────────────────────────────────────────────────────────

log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $*"
}

success() {
    echo -e "${GREEN}✓${NC} $*"
}

warning() {
    echo -e "${YELLOW}⚠${NC} $*"
}

error() {
    echo -e "${RED}✗${NC} $*" >&2
}

die() {
    error "$*"
    exit 1
}

# ── Pre-flight Checks ─────────────────────────────────────────────────────────

preflight() {
    log "Running pre-flight checks..."
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root"
    fi
    
    # Check if repo exists
    if [[ ! -d "$REPO_DIR" ]]; then
        die "Repository not found at $REPO_DIR"
    fi
    
    # Check if docker is running
    if ! docker info > /dev/null 2>&1; then
        die "Docker is not running"
    fi
    
    # Check if docker compose exists (v2 or v1)
    if ! docker compose version > /dev/null 2>&1 && ! command -v docker compose > /dev/null 2>&1; then
        die "docker compose not found (neither v2 nor v1)"
    fi
    
    success "Pre-flight checks passed"
}

# ── Git Operations ────────────────────────────────────────────────────────────

backup_current_version() {
    log "Backing up current version..."
    cd "$REPO_DIR"
    
    CURRENT_SHA=$(git rev-parse HEAD)
    echo "$CURRENT_SHA" > .last_deploy_sha
    
    success "Backed up SHA: $CURRENT_SHA"
}

pull_latest() {
    log "Pulling latest code from $BRANCH..."
    cd "$REPO_DIR"
    
    # Stash local changes (if any)
    if ! git diff-index --quiet HEAD --; then
        warning "Local changes detected, stashing..."
        git stash
    fi
    
    # Pull latest
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
    
    NEW_SHA=$(git rev-parse HEAD)
    success "Updated to SHA: $NEW_SHA"
}

rollback() {
    log "Rolling back to previous version..."
    cd "$REPO_DIR"
    
    if [[ ! -f .last_deploy_sha ]]; then
        die "No previous deployment found (.last_deploy_sha missing)"
    fi
    
    PREVIOUS_SHA=$(cat .last_deploy_sha)
    log "Rolling back to SHA: $PREVIOUS_SHA"
    
    git checkout "$PREVIOUS_SHA"
    
    success "Rolled back successfully"
}

# ── Docker Operations ─────────────────────────────────────────────────────────

build_containers() {
    log "Building Docker containers..."
    cd "$REPO_DIR"
    
    docker compose build --no-cache "$API_CONTAINER"
    
    success "Containers built"
}

restart_services() {
    log "Restarting services..."
    cd "$REPO_DIR"
    
    # Stop API container
    docker compose stop "$API_CONTAINER"
    
    # Start all services
    docker compose up -d
    
    success "Services restarted"
}

wait_for_health() {
    log "Waiting for API to be healthy..."
    
    for i in $(seq 1 "$MAX_RETRIES"); do
        if curl -f -s "$HEALTH_ENDPOINT" > /dev/null 2>&1; then
            success "API is healthy"
            return 0
        fi
        
        echo -n "."
        sleep "$RETRY_DELAY"
    done
    
    error "API failed to become healthy after $((MAX_RETRIES * RETRY_DELAY))s"
    return 1
}

# ── Testing ───────────────────────────────────────────────────────────────────

run_smoke_tests() {
    log "Running smoke tests..."
    
    # Test 1: Health endpoint
    if ! curl -f -s "$HEALTH_ENDPOINT" | grep -q '"status":"healthy"'; then
        error "Health check failed"
        return 1
    fi
    success "Health check passed"
    
    # Test 2: Database connection
    if ! docker exec "$API_CONTAINER" python3 -c "from memory.postgres_backend import PostgreSQLBackend; PostgreSQLBackend().health_check()" 2>&1 | grep -q "healthy"; then
        warning "Database health check failed (non-critical)"
    else
        success "Database connection OK"
    fi
    
    # Test 3: Redis connection
    if docker exec beamax-redis redis-cli ping | grep -q "PONG"; then
        success "Redis connection OK"
    else
        warning "Redis connection failed (non-critical)"
    fi
    
    # Test 4: Qdrant connection
    if curl -f -s http://localhost:6333/health 2>&1 | grep -q "ok"; then
        success "Qdrant connection OK"
    else
        warning "Qdrant connection failed (non-critical)"
    fi
    
    success "Smoke tests passed"
}

# ── Deployment Logs ───────────────────────────────────────────────────────────

show_logs() {
    log "Recent API logs:"
    docker logs --tail 50 "$API_CONTAINER"
}

# ── Main Deployment Flow ──────────────────────────────────────────────────────

deploy() {
    local SKIP_TESTS=false
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --fast)
                SKIP_TESTS=true
                shift
                ;;
            *)
                die "Unknown option: $1"
                ;;
        esac
    done
    
    echo ""
    log "════════════════════════════════════════════════════════════"
    log "  BeaMax Production Deployment"
    log "════════════════════════════════════════════════════════════"
    echo ""
    
    preflight
    backup_current_version
    pull_latest
    build_containers
    restart_services
    
    if ! wait_for_health; then
        error "Deployment failed: API not healthy"
        warning "Rolling back..."
        rollback
        restart_services
        wait_for_health
        die "Deployment failed and rolled back"
    fi
    
    if [[ "$SKIP_TESTS" == false ]]; then
        run_smoke_tests
    else
        warning "Skipping smoke tests (--fast mode)"
    fi
    
    echo ""
    success "═══════════════════════════════════════════════════════════"
    success "  Deployment Complete!"
    success "═══════════════════════════════════════════════════════════"
    success "API:    http://bea.beamaxapp.co.uk"
    success "Health: $HEALTH_ENDPOINT"
    success "SHA:    $(git rev-parse HEAD)"
    echo ""
}

# ── Main Entry Point ──────────────────────────────────────────────────────────

main() {
    case "${1:-deploy}" in
        deploy|--fast)
            deploy "$@"
            ;;
        rollback|--rollback)
            preflight
            rollback
            restart_services
            wait_for_health
            success "Rollback complete"
            ;;
        logs)
            show_logs
            ;;
        status)
            log "Checking service status..."
            cd "$REPO_DIR"
            docker compose ps
            echo ""
            curl -s "$HEALTH_ENDPOINT" | python3 -m json.tool || error "API not responding"
            ;;
        help|--help|-h)
            cat << EOF
BeaMax Production Deployment Script

USAGE:
    ./deploy.sh              Full deployment (with tests)
    ./deploy.sh --fast       Fast deployment (skip tests)
    ./deploy.sh rollback     Rollback to previous version
    ./deploy.sh logs         Show recent API logs
    ./deploy.sh status       Check service status
    ./deploy.sh help         Show this help

ENVIRONMENT:
    REPO_DIR:         $REPO_DIR
    BRANCH:           $BRANCH
    API_CONTAINER:    $API_CONTAINER
    HEALTH_ENDPOINT:  $HEALTH_ENDPOINT

EOF
            ;;
        *)
            die "Unknown command: $1 (use 'help' for usage)"
            ;;
    esac
}

main "$@"
