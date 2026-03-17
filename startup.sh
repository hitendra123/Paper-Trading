#!/bin/bash
# Azure App Service startup command for Streamlit
pip install -r requirements.txt
streamlit run streamlit_app.py --server.port 8000 --server.address 0.0.0.0 --server.enableCORS false --server.enableXsrfProtection false
