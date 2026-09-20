from django.urls import path
from . import views

urlpatterns = [
    path('quote', views.quote),
    path('orders', views.create_order),
    path('orders/<str:orderId>', views.get_order),
    path('orders/<str:orderId>/cancel', views.cancel_order),
    path('orders/<str:orderId>/payment', views.check_payment),
]
