# ============================================================
# Push Jarvismax -> github.com/IA-optimist/Bea (privé)
# ============================================================
# Prérequis :
#   - gh CLI installé et authentifié : `gh auth status`
#   - Tu dois être membre de l'organisation IA-optimist (ou que ce soit ton user perso)
#
# Usage :
#   cd C:\Users\maxen\Documents\Jarvismax-master
#   powershell -ExecutionPolicy Bypass -File .\push_to_IA-optimist.ps1
#
# Note : repo name "Bea" car GitHub n'accepte pas les accents.
# Si tu veux un autre nom, modifie $RepoName ci-dessous.
# ============================================================

$ErrorActionPreference = "Stop"

# -- Paramètres ----------------------------------------------
$Org       = "IA-optimist"
$RepoName  = "Bea"            # <-- édite ici si tu veux un autre slug
$Visibility = "private"        # private | public
$RepoFull  = "$Org/$RepoName"
$RepoDir   = "C:\Users\maxen\Documents\Jarvismax-master"

Set-Location $RepoDir

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Push Jarvismax -> https://github.com/$RepoFull ($Visibility)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# -- 1. Vérifs préliminaires ---------------------------------
Write-Host "[1/7] Vérification gh CLI..." -ForegroundColor Yellow
gh auth status
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERREUR : gh CLI non authentifié. Lance 'gh auth login' d'abord." -ForegroundColor Red
    exit 1
}

# -- 2. Nettoyage des artefacts ------------------------------
Write-Host ""
Write-Host "[2/7] Nettoyage des artefacts (lock git, symlink cassé, fichiers tmp)..." -ForegroundColor Yellow

if (Test-Path ".git\index.lock") {
    Remove-Item ".git\index.lock" -Force
    Write-Host "  - Supprimé : .git\index.lock (lock obsolète)" -ForegroundColor Gray
}
if (Test-Path "test_write_perm.tmp") {
    Remove-Item "test_write_perm.tmp" -Force
    Write-Host "  - Supprimé : test_write_perm.tmp" -ForegroundColor Gray
}
if (Test-Path "latest") {
    # Symlink cassé — on supprime via cmd car PowerShell râle parfois sur les symlinks invalides
    cmd /c "del /F /Q latest 2>nul"
    Write-Host "  - Supprimé : latest (symlink cassé)" -ForegroundColor Gray
}

# -- 3. Sécurité : pas de .env tracké ------------------------
Write-Host ""
Write-Host "[3/7] Vérif sécurité : pas de .env tracké..." -ForegroundColor Yellow
$envTracked = git ls-files | Select-String -Pattern "^\.env$|^\.env\."
if ($envTracked) {
    Write-Host "ATTENTION : fichiers .env trackés détectés !" -ForegroundColor Red
    $envTracked
    $confirm = Read-Host "Continuer quand même ? (oui/non)"
    if ($confirm -ne "oui") { exit 1 }
} else {
    Write-Host "  OK : aucun .env tracké." -ForegroundColor Green
}

# -- 4. Commit des modifications -----------------------------
Write-Host ""
Write-Host "[4/7] Commit des modifications en cours..." -ForegroundColor Yellow

# On stage uniquement les fichiers déjà trackés modifiés
# (les nouveaux fichiers ne sont pas auto-stagés pour éviter les surprises)
git add -u

# Pour les nouveaux fichiers utiles, on les ajoute explicitement
$NewFilesToAdd = @(
    ".python-version",
    "tests/test_p0_hardening.py",
    "tests/test_p1_hardening.py"
)
foreach ($f in $NewFilesToAdd) {
    if (Test-Path $f) {
        git add $f
        Write-Host "  + Ajouté : $f" -ForegroundColor Gray
    }
}

$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Host "  Aucun changement à commiter, on passe directement au push." -ForegroundColor Gray
} else {
    Write-Host "  Fichiers stagés :" -ForegroundColor Gray
    $staged | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }

    $msg = @"
chore: hardening CI/Docker/API + monitoring updates

- CI workflows: align Python versions, harden checkouts
- Dockerfile + Dockerfile.nonroot: small updates
- api/{auth,main,routes/finance,routes/missions,routes/vault}: minor hardening
- core/tool_executor: safer execution path
- executor/{desktop_env/sandbox,runner}: sandbox tweaks
- mcp/hexstrike-ai: remove unused bug_bounty module
- monitoring: docs + compose alignment
- requirements: refresh lock
- tests: add p0/p1 hardening tests
"@

    git commit -m $msg
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERREUR : commit échoué. Vérifie les hooks pre-commit." -ForegroundColor Red
        exit 1
    }
}

# -- 5. Création du repo sur IA-optimist ---------------------
Write-Host ""
Write-Host "[5/7] Création du repo $RepoFull ($Visibility)..." -ForegroundColor Yellow

$exists = gh repo view $RepoFull 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Le repo $RepoFull existe déjà — on saute la création." -ForegroundColor Gray
} else {
    gh repo create $RepoFull --$Visibility --description "Jarvismax - Multi-agent AI OS"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERREUR : création du repo échouée." -ForegroundColor Red
        Write-Host "Vérifie que :" -ForegroundColor Red
        Write-Host "  - Tu as les droits sur l'org IA-optimist" -ForegroundColor Red
        Write-Host "  - gh CLI a le scope 'repo' (gh auth refresh -s repo)" -ForegroundColor Red
        exit 1
    }
}

# -- 6. Reconfiguration du remote ----------------------------
Write-Host ""
Write-Host "[6/7] Reconfiguration du remote 'origin' -> $RepoFull..." -ForegroundColor Yellow

$newUrl = "https://github.com/$RepoFull.git"
$current = git remote get-url origin 2>$null
if ($current) {
    Write-Host "  Ancien remote origin : $current" -ForegroundColor Gray
    git remote set-url origin $newUrl
} else {
    git remote add origin $newUrl
}
Write-Host "  Nouveau remote origin : $newUrl" -ForegroundColor Green

# -- 7. Push --------------------------------------------------
Write-Host ""
Write-Host "[7/7] Push de la branche 'main' vers $RepoFull..." -ForegroundColor Yellow

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERREUR : push échoué." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " OK ! Repo poussé : https://github.com/$RepoFull" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Vérif rapide :" -ForegroundColor Cyan
Write-Host "  gh repo view $RepoFull --web" -ForegroundColor Cyan
