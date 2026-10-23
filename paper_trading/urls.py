#paper_trading/urls.py
from django.urls import path
from . import views

app_name = 'paper_trading'

urlpatterns = [
    path('order/', views.create_order_view, name='create_order'),
    path('close/<int:trade_id>/', views.close_order_view, name='close_order'),
    path('reset/', views.reset_account_view, name='reset_account'),
    path('auto-trade/toggle/', views.toggle_auto_trade_view, name='toggle_auto_trade'),
    path('status/', views.account_status_api, name='account_status'),
]
