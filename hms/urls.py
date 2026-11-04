from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name='dashboard'),
    path("superadmin/", views.superadmin_dashboard, name='superadmin_dashboard'),
    path("superadmin/ajax/live-stats/", views.live_dashboard_stats, name='live_dashboard_stats'),

    # Enterprise Dynamic Dashboard (Non-Super Admin Roles)
    path("dynamic-dashboard/", views.dynamic_dashboard, name='dynamic_dashboard'),
    path("dashboard/ajax/live-kpis/", views.dashboard_live_kpis, name='dashboard_live_kpis'),
    path("dashboard/ajax/save-widgets/", views.dashboard_save_widgets, name='dashboard_save_widgets'),
    path("dashboard/ajax/quick-approve-leave/<int:leave_id>/", views.dashboard_quick_approve_leave, name='dashboard_quick_approve_leave'),
    path("dashboard/ajax/quick-verify-exit/<int:leave_id>/", views.dashboard_quick_verify_exit, name='dashboard_quick_verify_exit'),

    # Staff Management
    path("staff/", views.staff_list, name='staff_list'),
    path("staff/create/", views.staff_create, name='staff_create'),
    path("staff/<int:pk>/edit/", views.staff_edit, name='staff_edit'),
    path("staff/<int:pk>/delete/", views.staff_delete, name='staff_delete'),
    path("staff/<int:pk>/toggle-status/", views.staff_toggle_status, name='staff_toggle_status'),
    path("staff/duties/", views.duty_list, name='duty_list'),
    path("staff/duties/assign/", views.duty_assign, name='duty_assign'),
    path("staff/duties/<int:pk>/edit/", views.duty_edit, name='duty_edit'),
    path("staff/duties/<int:pk>/delete/", views.duty_delete, name='duty_delete'),
    path("staff/duties/definitions/create/", views.duty_create, name='duty_create'),
    path("staff/duties/definitions/<int:pk>/edit/", views.duty_edit_definition, name='duty_edit_definition'),
    path("staff/duties/definitions/<int:pk>/delete/", views.duty_delete_definition, name='duty_delete_definition'),
    path("staff/duties/<int:pk>/approve/", views.duty_approve, name='duty_approve'),
    path("staff/duties/<int:pk>/reject/", views.duty_reject, name='duty_reject'),
    path("staff/duties/<int:pk>/handover/", views.duty_handover, name='duty_handover'),
    path("staff/duties/<int:pk>/revoke/", views.duty_revoke, name='duty_revoke'),
    path("staff/duties/ajax/get-floors/", views.get_floors_for_building, name='duty_get_floors'),
    path("staff/duties/ajax/get-rooms/", views.get_rooms_for_building_floor, name='duty_get_rooms'),
    path("staff/duties/ajax/check-conflict/", views.check_duty_conflict_ajax, name='duty_check_conflict'),
    
    # Complaint Management
    path("complaints/", views.complaint_list, name='complaint_list'),
    path("complaints/<int:pk>/assign/", views.complaint_assign, name='complaint_assign'),
    path("complaints/<int:pk>/resolve/", views.complaint_resolve, name='complaint_resolve'),

    # Reports
    path("reports/", views.reports_dashboard, name='reports_dashboard'),
    path("reports/export/<str:module>/", views.export_report, name='export_report'),
]
