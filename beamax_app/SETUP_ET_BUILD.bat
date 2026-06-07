@echo off
REM ================================================================
REM  BEA MAX — Setup complet + Build APK
REM  Ce script installe Flutter, configure l'environnement,
REM  et génère l'APK release.
REM ================================================================
setlocal enabledelayedexpansion

echo.
echo  ============================================================
echo   BEA MAX — Setup et Build APK
echo  ============================================================
echo.

REM ── Étape 1 : Vérifier si Flutter est déjà dispo ──────────────
where flutter >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Flutter detecte :
    flutter --version
    goto :BUILD
)

echo [INFO] Flutter non trouve. Vérification de C:\flutter...
if exist "C:\flutter\bin\flutter.bat" (
    echo [OK] Flutter SDK existe dans C:\flutter
    set PATH=C:\flutter\bin;%PATH%
    goto :BUILD
)

REM ── Étape 2 : Télécharger Flutter si pas dispo ────────────────
echo.
echo [1/4] Téléchargement Flutter SDK (~700MB)...
echo        Cela peut prendre 5-15 minutes selon votre connexion.
echo.

powershell -Command "& {
    $url = 'https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.27.4-stable.zip'
    $dest = 'C:\flutter_sdk.zip'
    if (Test-Path $dest) {
        Write-Host '[INFO] Fichier deja telecharge.'
    } else {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($url, $dest)
        Write-Host '[OK] Téléchargement termine.'
    }
}"

if %errorlevel% neq 0 (
    echo [ERREUR] Téléchargement échoué.
    echo.
    echo  Téléchargez manuellement depuis :
    echo  https://docs.flutter.dev/get-started/install/windows/mobile
    echo.
    pause
    exit /b 1
)

REM ── Étape 3 : Extraire ────────────────────────────────────────
echo.
echo [2/4] Extraction dans C:\flutter...
powershell -Command "Expand-Archive -Path 'C:\flutter_sdk.zip' -DestinationPath 'C:\' -Force"

if %errorlevel% neq 0 (
    echo [ERREUR] Extraction échouée.
    pause
    exit /b 1
)

echo [OK] Flutter extrait dans C:\flutter
set PATH=C:\flutter\bin;%PATH%

REM ── Étape 4 : Vérification ────────────────────────────────────
echo.
echo [3/4] Vérification Flutter...
C:\flutter\bin\flutter --version
C:\flutter\bin\flutter doctor

REM ── Build ─────────────────────────────────────────────────────
:BUILD
echo.
echo [4/4] BUILD APK RELEASE...
echo.

cd /d "%~dp0"

echo [a] flutter pub get...
flutter pub get
if %errorlevel% neq 0 (
    echo [ERREUR] pub get failed. Voir message ci-dessus.
    pause
    exit /b 1
)

echo.
echo [b] flutter build apk --release...
flutter build apk --release
if %errorlevel% neq 0 (
    echo.
    echo [ERREUR] Build échoué.
    echo Essayez avec : flutter build apk --release --no-shrink
    echo.
    flutter build apk --release --no-shrink
)

REM ── Résultat ──────────────────────────────────────────────────
set APK=build\app\outputs\flutter-apk\app-release.apk

if exist "%APK%" (
    echo.
    echo ============================================================
    echo  APK GENERE AVEC SUCCES !
    echo.
    echo  Fichier : %APK%
    echo.
    echo  Pour installer sur votre téléphone :
    echo    adb install "%APK%"
    echo  Ou transférez le fichier APK sur votre appareil Android
    echo  et ouvrez-le pour installer.
    echo ============================================================
    explorer build\app\outputs\flutter-apk\
) else (
    echo [ERREUR] APK introuvable. Vérifiez les erreurs ci-dessus.
)

echo.
pause
