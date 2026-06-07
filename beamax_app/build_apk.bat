@echo off
REM ================================================================
REM  BEA MAX — Build APK Release
REM ================================================================
echo.
echo  BeaMax — Build APK Release
echo  ==============================
echo.

REM Vérifier Flutter
where flutter >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Flutter n'est pas dans le PATH.
    echo.
    echo  Solutions :
    echo    1. Télécharger Flutter : https://docs.flutter.dev/get-started/install/windows
    echo    2. Ajouter C:\flutter\bin au PATH
    echo    3. Redémarrer ce terminal
    echo.
    pause
    exit /b 1
)

echo [1/3] Installation des dépendances...
flutter pub get
if %errorlevel% neq 0 (
    echo [ERREUR] flutter pub get a échoué.
    pause
    exit /b 1
)

echo.
echo [2/3] Vérification Flutter doctor...
flutter doctor -v

echo.
echo [3/3] Build APK Release...
flutter build apk --release --no-shrink
if %errorlevel% neq 0 (
    echo [ERREUR] Build échoué.
    pause
    exit /b 1
)

copy /Y build\app\outputs\flutter-apk\app-release.apk build\app\outputs\flutter-apk\Bea_app.apk >nul
echo.
echo ================================================================
echo  Bea_app.apk généré avec succès !
echo.
echo  Chemin : build\app\outputs\flutter-apk\Bea_app.apk
echo ================================================================
echo.

REM Ouvrir le dossier
explorer build\app\outputs\flutter-apk\

pause
