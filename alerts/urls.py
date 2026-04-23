# campusalert/alerts/urls.py

from django.urls import path

from .views import (
    AdminAlertListView,
    AlertAcknowledgeView,
    AlertComposeView,
    AlertDeliveryStatusView,
    AlertDetailView,
    AlertFeedView,
    MissedAlertsView,
)

app_name = 'alerts'

urlpatterns = [
    # Student & Staff endpoints
    path('', AlertFeedView.as_view(), name='feed'),
    path('missed/', MissedAlertsView.as_view(), name='missed'),
    path('<uuid:pk>/', AlertDetailView.as_view(), name='detail'),
    path('<uuid:pk>/acknowledge/', AlertAcknowledgeView.as_view(), name='acknowledge'),

    # Admin-only endpoints
    path('compose/', AlertComposeView.as_view(), name='compose'),
    path('admin/', AdminAlertListView.as_view(), name='admin_list'),
    path('<uuid:pk>/delivery-status/', AlertDeliveryStatusView.as_view(), name='delivery_status'),
]

