from django.urls import path
from core import views,presentation,coordination,resource_changes,billing,account_access
from core.rest import operation
from core import appointment_queries
urlpatterns=[path('healthz',views.health),path('api/auth/login',views.login),path('api/auth/scope',views.switch),path('api/workspace',views.workspace),
 path('api/auth/options',account_access.options),path('api/auth/wechat',account_access.wechat),
 path('api/auth/wechat/select',account_access.select),path('api/auth/wechat/bind',account_access.bind),
 path('api/auth/register',account_access.register),path('api/auth/recovery',account_access.recovery),path('api/auth/reset-password',account_access.reset_password),
 path('api/appointment-queue',appointment_queries.queue),path('api/appointment-location',appointment_queries.location),path('api/clinic-overview',appointment_queries.clinic_overview),path('api/booking/options',presentation.booking_options),path('api/clinic-directory',presentation.clinic_directory),path('api/duties/calendar',presentation.staff_duty_calendar),path('api/clinics/<int:pk>/calendar-options',presentation.staff_calendar_options),path('api/appointments/<int:pk>',presentation.appointment_detail),
 path('api/patients/<int:pk>',presentation.patient_record),path('api/patient-journey',presentation.patient_journey),
 path('api/duties/preview',coordination.duty_preview),path('api/duties/<int:pk>',coordination.duty_detail),
 path('api/resources/impact',resource_changes.resource_impact),
 path('api/billing/<int:pk>',billing.review),
 path('api/reports/<int:pk>',presentation.frozen_report),
 path('api/audit/<int:pk>/source',views.audit_source),
 path('api/use-cases/<str:code>',views.usecase),path('api/slots',views.slot_list),path('api/invoices/<int:pk>',views.invoice_detail),
 path('api/encounters/<int:pk>',views.encounter_detail),path('api/plans/<int:pk>',views.plan_detail),path('api/reports',views.report_view),path('api/audit',views.audit_view),path('api/records',views.records),
 path('api/appointments',operation,{'kind':'book'}),path('api/appointments/<str:no>/reschedule',operation,{'kind':'reschedule'}),
 path('api/duties/<str:no>/replace',operation,{'kind':'replace'}),path('api/duties/<str:no>/stop',operation,{'kind':'stop'}),
 path('api/encounters/<str:no>/sign',operation,{'kind':'sign'}),path('api/encounters/<str:no>/invoice',operation,{'kind':'invoice'}),
 path('api/invoices/<str:no>/revisions',operation,{'kind':'invoice-revision'}),
 path('api/plans/<str:no>/revisions/<int:version>/confirm',operation,{'kind':'plan-confirm'}),
 path('api/cost-sources/<str:no>/revisions/<int:version>/review',operation,{'kind':'cost-review'}),
 path('api/quarters/<str:period>/reports/confirm',operation,{'kind':'report-confirm'})]
