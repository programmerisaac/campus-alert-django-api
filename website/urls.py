# campusalert/website/urls.py

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static



admin.site.site_header = "Campus Alert System"
admin.site.site_title  = "Campus Alert System"
admin.site.index_title = "Welcome to Campus Alert"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/accounts/', include('accounts.urls', namespace='accounts')),
    path('api/v1/alerts/', include('alerts.urls', namespace='alerts')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL,  document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    try:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

