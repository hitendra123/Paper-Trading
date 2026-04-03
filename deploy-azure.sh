#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Azure App Service Deployment Script
# Account : hitendra@nubitsaitech.com
# Resource Group : market
# App Name : market
# ─────────────────────────────────────────────────────────────────────────────
set -e

RESOURCE_GROUP="market"
APP_NAME="market"
LOCATION="eastasia"          # change if preferred: centralindia, southeastasia
SKU="B1"                     # B1 = Basic (Always On + WebSockets supported)
PYTHON_VERSION="PYTHON:3.11"

echo "==> Logging in to Azure..."
az login --use-device-code

echo "==> Setting account to hitendra@nubitsaitech.com..."
az account set --subscription "$(az account list --query "[?user.name=='hitendra@nubitsaitech.com'].id" -o tsv | head -1)"

echo "==> Creating resource group '$RESOURCE_GROUP' (skipped if exists)..."
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" 2>/dev/null || true

echo "==> Deploying app '$APP_NAME' to App Service..."
az webapp up \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --runtime "$PYTHON_VERSION" \
  --sku "$SKU" \
  --location "$LOCATION"

echo "==> Enabling WebSockets (required for Streamlit)..."
az webapp config set \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --web-sockets-enabled true

echo "==> Enabling Always On (keeps bot alive during market hours)..."
az webapp config set \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --always-on true

echo "==> Setting startup command..."
az webapp config set \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --startup-file "bash startup.sh"

echo ""
echo "✅ Deployment complete!"
echo "   App URL : https://${APP_NAME}.azurewebsites.net"
echo ""
