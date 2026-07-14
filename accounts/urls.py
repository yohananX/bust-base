from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic.base import RedirectView, TemplateView
from accounts.views import PostLoginRedirectView

urlpatterns = [
    path('', RedirectView.as_view(url='/accounts/login/'), name='accounts_root'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='logout_complete'), name='logout'),
    path('logout/complete/', TemplateView.as_view(template_name='accounts/logged_out.html', extra_context={'title': 'Logged Out'}), name='logout_complete'),
    path('redirect/', PostLoginRedirectView.as_view(), name='post_login_redirect'),
]
