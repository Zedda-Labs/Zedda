<#
.SYNOPSIS
    Builds Zedda using Clang-cl on Windows with native CPU optimization and LTO.
.DESCRIPTION
    Configures and builds fasteda_core with clang-cl, using -O3, -march=native,
    and link-time optimization for maximum throughput.
    Requires: LLVM installed (e.g. winget install LLVM.LLVM).
#>

[CmdletBinding()]
param(
    [string]$BuildDir = "build_clang",
    [switch]$Install = $true
)

$ErrorActionPreference = "Stop"

Write-Host "=== Zedda Clang-cl Optimized Build ===" -ForegroundColor Cyan

# Check for clang-cl
$clangcl = Get-Command "clang-cl" -ErrorAction SilentlyContinue
if (-not $clangcl) {
    Write-Warning "clang-cl not found in PATH. Please install LLVM: winget install LLVM.LLVM"
    Write-Host "Attempting fallback to standard CMake detection..."
}

Write-Host "Configuring CMake with Clang-cl and Release flags..." -ForegroundColor Yellow
cmake -B $BuildDir -DUSE_CLANG_CL=ON -DCMAKE_BUILD_TYPE=Release -DZEDDA_ENABLE_LTO=ON .

Write-Host "Building Zedda..." -ForegroundColor Yellow
cmake --build $BuildDir --config Release --parallel

if ($Install) {
    Write-Host "Installing in development mode..." -ForegroundColor Yellow
    pip install -e . --no-build-isolation
}

Write-Host "Build and installation complete!" -ForegroundColor Green
