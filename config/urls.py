from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from monitor import views, api
from monitor import program_views
urlpatterns = [
    path('programs/new/',program_views.program_edit,name='program-create'),
    path('programs/<slug:slug>/edit/',program_views.program_edit,name='program-edit'),
    path('imports/new/',program_views.job_upload,name='import-job-upload'),
    path('imports/<uuid:pk>/',program_views.job_detail,name='import-job'),
    path('', views.home, name='home'),
    path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='/accounts/login/'), name='logout'),
    path('admin/',admin.site.urls),
    path('healthz/',views.health,name='health'),
    path('programs/<slug:slug>/', views.passport, name='passport'),
    path('explore/', views.explore, name='explore'),
    path('upload/', views.upload, name='upload'),
    path('history/', views.history, name='history'),
    path('api/v1/indicators/',api.indicators,name='api-indicators'),
    path('api/v1/observations/',api.observations,name='api-observations'),
]
