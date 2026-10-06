# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Panel Admin Django
    path('admin/', admin.site.urls),
    
    # Rute utama diarahkan ke aplikasi trading_dashboard
    path('', include('trading_dashboard.urls')),
]

# Dukungan file statis jika berjalan di mode debug
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)