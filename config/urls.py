from django.urls import path
from monitor import views
urlpatterns = [path('', views.home, name='home'), path('programs/<slug:slug>/', views.passport, name='passport'), path('explore/', views.explore, name='explore'), path('upload/', views.upload, name='upload'), path('history/', views.history, name='history')]
