from django.apps import AppConfig

# Example stock splits dictionary
stock_splits = {
    "AAPL": [("2020-08-31", 4)],
    "TSLA": [("2020-08-31", 5)],
    "NVDA": [("2021-07-20", 4)],
}


class PortfolioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'portfolio'
