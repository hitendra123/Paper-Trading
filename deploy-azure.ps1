# Azure App Service Deployment Script (Windows PowerShell)
# Account       : hitendra@nubitsaitech.com
# Resource Group: market
# App Name      : market-trading-bot  (globally unique)

$RESOURCE_GROUP = "market"
$APP_NAME       = "market-trading-bot"
$LOCATION       = "centralindia"
$SKU            = "B1"
$ACCOUNT        = "hitendra@nubitsaitech.com"
$SUB_ID         = "51b6e948-3d25-4d59-8ed2-b2d30815242b"

Write-Host "==> Logging in as $ACCOUNT ..." -ForegroundColor Cyan
az login --username $ACCOUNT

Write-Host "==> Setting Microsoft Azure Sponsorship subscription..." -ForegroundColor Cyan
az account set --subscription $SUB_ID
Write-Host "    Active: $(az account show --query name -o tsv)" -ForegroundColor Green

Write-Host "==> Creating resource group '$RESOURCE_GROUP'..." -ForegroundColor Cyan
az group create --name $RESOURCE_GROUP --location $LOCATION

Write-Host "==> Deploying app '$APP_NAME' to Azure App Service (~3 min)..." -ForegroundColor Cyan
az webapp up --name $APP_NAME --resource-group $RESOURCE_GROUP --runtime "PYTHON:3.11" --sku $SKU --location $LOCATION

Write-Host "==> Enabling WebSockets (required for Streamlit)..." -ForegroundColor Cyan
az webapp config set --name $APP_NAME --resource-group $RESOURCE_GROUP --web-sockets-enabled true

Write-Host "==> Enabling Always On..." -ForegroundColor Cyan
az webapp config set --name $APP_NAME --resource-group $RESOURCE_GROUP --always-on true

Write-Host "==> Setting startup command..." -ForegroundColor Cyan
az webapp config set --name $APP_NAME --resource-group $RESOURCE_GROUP --startup-file "bash startup.sh"

Write-Host ""
Write-Host "Deployment complete!" -ForegroundColor Green
Write-Host "   App URL: https://$APP_NAME.azurewebsites.net" -ForegroundColor Green


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
