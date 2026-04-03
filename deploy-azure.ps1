# Azure App Service Deployment Script (Windows PowerShell)
# Account       : hitendra@nubitsaitech.com
# Resource Group: market
# App Name      : market

$RESOURCE_GROUP = "market"
$APP_NAME       = "market"
$LOCATION       = "centralindia"
$SKU            = "B1"

Write-Host "==> Logging in to Azure..." -ForegroundColor Cyan
az login

Write-Host ""
Write-Host "==> Available subscriptions:" -ForegroundColor Cyan
az account list --output table

Write-Host ""
Write-Host "==> Selecting Microsoft Azure Sponsorship subscription..." -ForegroundColor Cyan
$SUB_ID = "51b6e948-3d25-4d59-8ed2-b2d30815242b"
az account set --subscription $SUB_ID
Write-Host "    Active subscription: Microsoft Azure Sponsorship ($SUB_ID)" -ForegroundColor Green

Write-Host "==> Creating resource group '$RESOURCE_GROUP'..." -ForegroundColor Cyan
az group create --name $RESOURCE_GROUP --location $LOCATION

Write-Host "==> Deploying app to Azure App Service (this takes ~3 min)..." -ForegroundColor Cyan
az webapp up --name $APP_NAME --resource-group $RESOURCE_GROUP --runtime "PYTHON:3.11" --sku $SKU --location $LOCATION

Write-Host "==> Enabling WebSockets (required for Streamlit)..." -ForegroundColor Cyan
az webapp config set --name $APP_NAME --resource-group $RESOURCE_GROUP --web-sockets-enabled true

Write-Host "==> Enabling Always On..." -ForegroundColor Cyan
az webapp config set --name $APP_NAME --resource-group $RESOURCE_GROUP --always-on true

Write-Host "==> Setting startup command..." -ForegroundColor Cyan
az webapp config set --name $APP_NAME --resource-group $RESOURCE_GROUP --startup-file "bash startup.sh"

Write-Host ""
Write-Host "✅ Deployment complete!" -ForegroundColor Green
Write-Host "   App URL: https://$APP_NAME.azurewebsites.net" -ForegroundColor Green
