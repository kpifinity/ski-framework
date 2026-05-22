#!/usr/bin/env powershell
# Restore git repository and push linting fixes

Write-Host "Removing corrupted .git directory..." -ForegroundColor Yellow
Remove-Item -Path ".\.git" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Initializing fresh git repository..." -ForegroundColor Yellow
git init
git config user.email "rahulkapai@gmail.com"
git config user.name "Rahul Kapai"

Write-Host "Adding remote repository..." -ForegroundColor Yellow
git remote add origin https://github.com/kpifinity/ski-framework.git

Write-Host "Fetching from origin..." -ForegroundColor Yellow
git fetch origin main

Write-Host "Resetting to origin/main..." -ForegroundColor Yellow
git reset --hard origin/main

Write-Host "Staging all changes..." -ForegroundColor Yellow
git add -A

Write-Host "Verifying ruff checks..." -ForegroundColor Yellow
python -m ruff check .

if ($LASTEXITCODE -eq 0) {
    Write-Host "Committing changes..." -ForegroundColor Green
    git commit -m "fix: Clean up linting errors and formatting

- Remove unused imports across 11+ files
- Fix f-strings without placeholders
- Resolve undefined name errors
- Clean up test files with trailing content
- All ruff checks pass"

    Write-Host "Pushing to main..." -ForegroundColor Green
    git push origin main

    Write-Host "✓ Complete! All fixes committed and pushed." -ForegroundColor Green
} else {
    Write-Host "✗ Ruff checks failed. Please fix issues before pushing." -ForegroundColor Red
}
