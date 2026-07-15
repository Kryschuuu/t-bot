from django.urls import path
from . import views

urlpatterns = [
    path('gate/', views.passphrase_gate_view, name='passphrase_gate'),
    path('', views.home, name='home'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('config/', views.config_view, name='config'),
    path('config/list/', views.config_list, name='config_list'), # Korrektur: config_list statt config_list_view
    path('config/detail/<int:config_id>/', views.config_detail, name='config_detail'), # Korrektur: config_detail statt config_detail_view
    path('config/edit/<int:config_id>/', views.config_update, name='config_edit'), # Korrektur: config_update statt config_edit_view
    path('config/delete/<int:config_id>/', views.config_delete, name='config_delete'),
    path('config/activate/<int:config_id>/', views.config_activate, name='config_activate'),
    path('config/deactivate/<int:config_id>/', views.config_deactivate, name='config_deactivate'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    # path('start_bot/<int:config_id>/', views.start_bot, name='start_bot'),
    # path('stop_bot/<int:config_id>/', views.stop_bot, name='stop_bot'),
    path('reset_log/<int:config_id>/', views.reset_log, name='reset_log'),
    path('api/info/<int:config_id>/', views.info_api, name='info_api'),
    path('api/logs/<int:config_id>/', views.logs_api, name='logs_api'),
    # WICHTIG: Symbol als Query-Parameter, nicht als Pfadsegment - Symbole
    # wie "BTC/USDT" enthalten einen Slash, der als Pfadsegment (auch
    # %2F-kodiert) von den meisten Servern schon vor dem Django-Routing
    # decodiert wird und die URL sonst nicht matcht (-> 404 -> "Verkauf
    # fehlgeschlagen (Netzwerkfehler)", da die HTML-Fehlerseite kein
    # gueltiges JSON ist).
    path('api/manual_sell/<int:config_id>/', views.manual_sell_view, name='manual_sell'),
    path('api/data_logs/', views.data_logs_api, name='data_logs_api'),
    path('api/trades/', views.trades_api, name='trades_api'),
    path('report/<int:config_id>/', views.generate_report, name='generate_report'),
    # Neuer URL-Eintrag für Backtesting:
    path('backtesting/<int:config_id>/', views.backtesting_form, name='backtesting_form'), # Korrektur: backtesting_form statt backtesting_view
    path('control_backtest/<int:task_id>/', views.control_backtest, name='control_backtest'),  # Neu hinzugefügt    
    path('backtesting/<int:task_id>/pdf/', views.generate_backtest_pdf, name='generate_backtest_pdf'),   
    # technische Indikatoren Analyse 
    path('analyse/', views.analyse_view, name='analyse'),
    path("api/bot/status/", views.bot_status_api, name="bot_status_api"),
    path("errors/", views.error_log_view, name="error_log"),
]
