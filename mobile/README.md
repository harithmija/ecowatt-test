# EcoWatt AI Flutter app

This is a native Flutter client for the existing FastAPI service. It includes resident sign-in/sign-up, overview, monthly report, appliance monitoring and action logging, energy advisor, savings simulator, and sustainability pages.

## Create the Android and iOS runner projects

### Install Flutter on Windows first

`flutter` is a command-line tool, not a package in this project. Install the Flutter SDK by following the [official Windows installation guide](https://docs.flutter.dev/get-started/install/windows/mobile). During setup, install Android Studio and its Android SDK if you want to run or build the Android app.

Add the Flutter SDK's `bin` folder to your Windows `Path` (for example, `C:\src\flutter\bin`). Close and reopen PowerShell or the VS Code terminal after changing `Path`, then verify Flutter is available:

```powershell
flutter --version
flutter doctor
```

If PowerShell still says `flutter` is not recognized, check that the SDK's `bin` folder is in `Path` and restart the terminal. Flutter must be installed before running the project commands below.

### Generate the Android and iOS runner projects

From the `mobile` folder, scaffold the native runners in a separate directory:

```powershell
flutter create --platforms android,ios --project-name ecowatt_mobile mobile_runner
Copy-Item .\lib\*.dart .\mobile_runner\lib\
Copy-Item .\pubspec.yaml, .\analysis_options.yaml .\mobile_runner\
Set-Location .\mobile_runner
flutter pub get
```

This leaves the app source in `mobile/` untouched while Flutter generates Android and iOS runner projects in `mobile/mobile_runner/`.

Windows can build and run the Android app. Building or running the iOS app requires macOS and Xcode.

## Connect to the FastAPI server

The mobile app is a separate client. The Python server must be running and reachable from the device.

- Android emulator default: `http://10.0.2.2:8000`
- iOS simulator default: `http://127.0.0.1:8000`
- Physical phone: use the development computer's LAN IP, or a deployed HTTPS URL.

To use a custom base address:

```powershell
flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000
```

Replace the example address with the development computer's actual LAN IP. Start Uvicorn so other devices on the LAN can reach it:

```powershell
python -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

For a physical device on a local network, allow inbound connections to port 8000 in the computer firewall. Plain HTTP is only for local development; deploy behind HTTPS for real use. Android may require enabling cleartext traffic in the generated `android/app/src/main/AndroidManifest.xml` for local HTTP testing. Do not enable cleartext traffic in a production build.

Run on Android (from `mobile/mobile_runner`):

```powershell
flutter run
```

Build an Android APK:

```powershell
flutter build apk --release
```

The backend currently serves the existing account endpoints with HTTP-only cookies. The Flutter app persists its cookie jar locally. Google sign-in is not yet wired into the native app; use email/password sign-in in this version. All resident accounts still share the demo household data from the backend.
