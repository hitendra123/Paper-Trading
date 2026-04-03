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
Write-Host "==> Selecting Microsoft Sponsored Subscription..." -ForegroundColor Cyan
$SUB_ID = az account list --query "[?contains(name,'Sponsored') || contains(name,'sponsored') || contains(name,'Visual Studio') || contains(name,'Free') || contains(name,'Student')].id" -o tsv | Select-Object -First 1

if ($SUB_ID) {
    Write-Host "    Found sponsored subscription: $SUB_ID" -ForegroundColor Green
    az account set --subscription $SUB_ID
} else {
    Write-Host "    No sponsored subscription auto-detected." -ForegroundColor Yellow
    Write-Host "    Copy a Subscription ID from the table above and paste it:" -ForegroundColor Yellow
    $SUB_ID = Read-Host "    Subscription ID"
    az account set --subscription $SUB_ID
}

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
