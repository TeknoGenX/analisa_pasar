from django.urls import path
from . import views

app_name = 'trading_dashboard'

urlpatterns = [
    path('', views.main_dashboard, name='main_dashboard'),
    path('sync/', views.sync_market_data, name='sync_data'),
    path('export-csv/', views.export_csv, name='export_csv'),
]