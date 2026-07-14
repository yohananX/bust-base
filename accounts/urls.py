from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView
from accounts.views import PostLoginRedirectView

urlpatterns = [
    path('', RedirectView.as_view(url='/accounts/login/'), name='accounts_root'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('redirect/', PostLoginRedirectView.as_view(), name='post_login_redirect'),
]
