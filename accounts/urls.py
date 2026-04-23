# campusalert/accounts/urls.py

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    DeviceTokenUpdateView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    RegisterView,
)

app_name = 'accounts'

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('device/', DeviceTokenUpdateView.as_view(), name='device_token_update'),
    path('password/change/', PasswordChangeView.as_view(), name='password_change'),
]

