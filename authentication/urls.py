from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from .views import (
    RegistrationView, UserNameValidationView, EmailValidationView,
    LoginView, LogoutView, no_role_view, keep_alive_view, password_expired_view,
    role_list, role_create, role_edit, role_delete, role_clone, permission_overview, add_custom_permission_element,
    user_list, user_create, user_detail, user_edit, user_delete,
    user_toggle_status, user_lock, user_reset_password,
    user_change_role, user_export, user_audit,
    system_settings_view,
    # Legacy
    user_update_role,
)

urlpatterns = [
    # Auth
    path('register/', RegistrationView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('no-role/', no_role_view, name='no_role'),
    path('password-expired/', password_expired_view, name='password_expired'),
    path('keep-alive/', keep_alive_view, name='keep_alive'),
    path('validate-username/', csrf_exempt(UserNameValidationView.as_view()), name='validate-username'),
    path('validate-email/', csrf_exempt(EmailValidationView.as_view()), name='validate_email'),

    # Role Management
    path('roles/', role_list, name='role_list'),
    path('roles/create/', role_create, name='role_create'),
    path('roles/edit/<int:pk>/', role_edit, name='role_edit'),
    path('roles/delete/<int:pk>/', role_delete, name='role_delete'),
    path('roles/<int:pk>/clone/', role_clone, name='role_clone'),
    path('roles/custom-permission/', add_custom_permission_element, name='add_custom_permission_element'),
    path('api/user-permissions/<int:pk>/', permission_overview, name='permission_overview'),

    # User Management
    path('users/', user_list, name='user_management'),
    path('users/create/', user_create, name='user_create'),
    path('users/<int:pk>/', user_detail, name='user_detail'),
    path('users/<int:pk>/edit/', user_edit, name='user_edit'),
    path('users/<int:pk>/delete/', user_delete, name='user_delete'),
    path('users/<int:pk>/toggle-status/', user_toggle_status, name='user_toggle_status'),
    path('users/<int:pk>/lock/', user_lock, name='user_lock'),
    path('users/<int:pk>/reset-password/', user_reset_password, name='user_reset_password'),
    path('users/<int:pk>/change-role/', user_change_role, name='user_change_role'),
    path('users/export/', user_export, name='user_export'),
    path('users/<int:pk>/audit/', user_audit, name='user_audit'),

    # Legacy (for existing sidebar link)
    path('users/update-role/<int:user_id>/', user_update_role, name='user_update_role'),

    path('settings/system/', system_settings_view, name='system_settings_view'),

]
