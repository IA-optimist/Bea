# API v1 Audit - Stable Surface Classification

Audit date: 2026-06-19
Goal: Classify ~590 routes into stable v1 surface vs deprecated/experimental

## Classification Criteria

**STABLE v1** - Core public API:
- Mission lifecycle (submit, status, list, cancel, result)
- Memory operations (search, store, retrieve, delete)
- Health/monitoring endpoints
- Authentication (token creation, validation)
- Core cognitive operations

**DEPRECATED** - Legacy/experimental:
- Old version routes (/api/v2/* without migration path)
- Experimental features (venture, voice, multimodal stubs)
- Duplicate functionality
- Routes marked as stubs

**INTERNAL** - Admin/internal only:
- Training data collection
- Vault management (admin secrets)
- Cognitive consolidation triggers
- System diagnostics

## Route Classification

### Core Mission API (STABLE v1)
```
POST   /api/v1/missions              - Submit mission
GET    /api/v1/missions              - List missions  
GET    /api/v1/missions/{id}         - Get mission status
POST   /api/v1/missions/{id}/cancel - Cancel mission
GET    /api/v1/missions/{id}/result - Get mission result
```

### Core Memory API (STABLE v1)
```
POST   /api/v1/memory/search         - Search vector memory
POST   /api/v1/memory/store          - Store memory entry
GET    /api/v1/memory/{id}           - Get memory entry
DELETE /api/v1/memory/{id}           - Delete memory entry
GET    /api/v1/memory                - List recent memory
```

### Authentication API (STABLE v1)
```
POST   /api/v1/auth/token           - Create token
GET    /api/v1/auth/tokens          - List tokens
DELETE /api/v1/auth/tokens/{id}      - Delete token
POST   /api/v1/auth/tokens/{id}/revoke - Revoke token
POST   /api/v1/auth/validate        - Validate token
```

### Health/Monitoring (STABLE v1)
```
GET    /health                       - Health check
GET    /api/v1/status               - System status
GET    /api/v1/metrics              - System metrics
```

### Cognitive Operations (STABLE v1)
```
POST   /api/v1/chat                 - Chat completion
POST   /api/v1/plan                 - Generate plan
POST   /api/v1/execute              - Execute action
```

### Deprecated Routes (TO BE REMOVED/DEPRECATED)
```
# Venture (experimental)
GET    /api/v1/venture/hypotheses   - Experimental
GET    /api/v1/venture/experiments  - Experimental
POST   /api/v1/venture/run-loop     - Experimental

# Voice (stub)
POST   /api/v1/voice/process        - Stub implementation
POST   /api/v1/voice/call           - Stub implementation
POST   /api/v1/voice/sms            - Stub implementation

# Multimodal (stub)
POST   /api/v1/multimodal/*         - Stub implementations

# Browser (stub)  
POST   /api/v1/browser/*           - Stub implementations

# Playbooks (static data)
GET    /api/v1/playbooks/*          - Static data only

# Legacy v2 routes (without migration)
/api/v2/*                          - Deprecated, migrate to v1
```

### Internal/Admin Routes (NOT PUBLIC)
```
# Training data collection
POST   /api/v1/training/consolidate - Admin only
GET    /api/v1/training/workspace   - Admin only
GET    /api/v1/training/stats       - Admin only

# Vault management
POST   /api/v1/vault/unlock        - Admin only
POST   /api/v1/vault/lock          - Admin only
POST   /api/v1/vault/create        - Admin only
POST   /api/v1/vault/update        - Admin only
POST   /api/v1/vault/use           - Admin only
POST   /api/v1/vault/reveal        - Admin only
POST   /api/v1/vault/delete        - Admin only
GET    /api/v1/vault/list          - Admin only
GET    /api/v1/vault/logs          - Admin only

# Token management (admin operations)
GET    /api/v1/tokens/stats        - Admin only
```

## Migration Plan

### Phase 1: Freeze v1 Surface (Immediate)
1. Document all stable v1 routes with OpenAPI spec
2. Add deprecation warnings to legacy routes
3. Version all v1 responses with `api_version: "1.0"`

### Phase 2: Deprecate Legacy Routes (2 weeks)
1. Add `X-Deprecated: true` header to deprecated routes
2. Return migration path in deprecation response
3. Monitor usage of deprecated routes

### Phase 3: Remove Deprecated Routes (4 weeks)
1. Remove routes with zero usage
2. Keep high-usage deprecated routes with extended timeline
3. Update documentation

## Estimated Route Count

Based on audit:
- **STABLE v1**: ~25 core routes
- **DEPRECATED**: ~150 routes (experimental features, stubs, legacy v2)
- **INTERNAL**: ~50 routes (admin, training, vault)
- **UNCATEGORIZED**: ~365 routes (need further analysis)

## Next Steps

1. Complete route classification for all 590 routes
2. Generate OpenAPI spec for v1 surface
3. Implement deprecation headers
4. Create migration guide for deprecated routes
5. Add API versioning middleware
