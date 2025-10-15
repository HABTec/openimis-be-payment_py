from django.urls import path
from .views import handle_matching_payment

urlpatterns = [
     path('payments/offline/bulk', handle_matching_payment),
]