# Downloading the Windows app

1. Go to the **Releases** page of this repository and open the newest release.
2. Under **Assets**, download **AssistantApp.exe**.
3. Double-click it. Your browser opens the assistant at http://127.0.0.1:8000.

Windows may warn that the app is from an unknown publisher. Click **More info**, then **Run anyway**.
Keep the black window open while you use the app.

To publish a new version (maintainers only): create a tag such as `v1.0.0` and push it. GitHub Actions builds the app and attaches it to a new release.

    git tag v1.0.0
    git push origin v1.0.0
