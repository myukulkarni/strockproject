from django.shortcuts import render
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import yfinance as yf

stock_splits = {
    "AAPL": [("2020-08-31", 4)],
    "TSLA": [("2020-08-31", 5), ("2022-08-25", 3)],
}

exchange_rates = {
    "2020-08-31": 74.0,
    "2022-08-25": 79.0,
    "default": 75.0,
}

usd_to_eur = 0.85
usd_to_gbp = 0.75

def apply_stock_splits(df, splits_dict):
    for stock, splits in splits_dict.items():
        for split_date, ratio in splits:
            split_dt = datetime.strptime(split_date, "%Y-%m-%d")
            mask = (df["Stock"] == stock) & (df["Date"] < split_dt)
            df.loc[mask, "Quantity"] *= ratio
            df.loc[mask, "Price"] /= ratio
    return df

def get_exchange_rate(date):
    date_str = date.strftime("%Y-%m-%d")
    return exchange_rates.get(date_str, exchange_rates["default"])

def calculate_xirr(cash_flows):
    try:
        def xirr():
            return np.irr([cf for _, cf in cash_flows])
        return round(xirr() * 100, 2)
    except:
        return None

def get_adjusted_close_price(symbol, date):
    try:
        data = yf.download(
            symbol,
            start=date - timedelta(days=2),
            end=date + timedelta(days=2),
            progress=False,
            auto_adjust=True  # fixes the FutureWarning
        )
        if data.empty or 'Close' not in data.columns:
            print(f"Error fetching price for {symbol} on {date}: 'Close' column missing")
            return None
        closest_date = data.index[0]
        return round(float(data.loc[closest_date]["Close"]), 2)
    except Exception as e:
        print(f"Error fetching price for {symbol} on {date}: {e}")
        return None

def upload_files(request):
    if request.method == "POST":
        file1 = request.FILES.get("file1")
        file2 = request.FILES.get("file2")
        file3 = request.FILES.get("file3")

        dfs = []
        for f in [file1, file2, file3]:
            if f:
                try:
                    df = pd.read_csv(f, encoding="utf-8-sig")
                    df.columns = df.columns.str.strip()

                    expected_cols = {
                        "Symbol": "Symbol",
                        "Quantity": "Quantity",
                        "T. Price": "Price",
                        "Date/Time": "Date"
                    }

                    if not set(expected_cols.keys()).issubset(df.columns):
                        return render(request, "upload.html", {
                            "error": f"File {f.name} must contain columns: {', '.join(expected_cols.keys())}"
                        })

                    df = df[list(expected_cols.keys())].rename(columns=expected_cols)
                    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
                    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
                    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                    df.dropna(subset=["Quantity", "Price", "Date"], inplace=True)
                    df.rename(columns={"Symbol": "Stock"}, inplace=True)

                    df = apply_stock_splits(df, stock_splits)

                    # Yahoo adjusted price
                    df["Yahoo Adjusted Price"] = df.apply(
                        lambda row: get_adjusted_close_price(row["Stock"], row["Date"]), axis=1
                    )

                    df["INR Price"] = df.apply(lambda row: row["Price"] * get_exchange_rate(row["Date"]), axis=1)
                    df["EUR Price"] = df["Price"] * usd_to_eur
                    df["GBP Price"] = df["Price"] * usd_to_gbp

                    df["Total INR"] = df["INR Price"] * df["Quantity"]
                    df["Total EUR"] = df["EUR Price"] * df["Quantity"]
                    df["Total GBP"] = df["GBP Price"] * df["Quantity"]

                    df["Cashflow"] = -1 * df["Total INR"]

                    dfs.append(df)

                except Exception as e:
                    return render(request, "upload.html", {"error": f"Error processing {f.name}: {e}"})

        if not dfs:
            return render(request, "upload.html", {"error": "Please upload at least one valid file."})

        combined_df = pd.concat(dfs)

        summary = combined_df.groupby("Stock", as_index=False).agg({
            "Quantity": "sum",
            "Total INR": "sum",
            "Total EUR": "sum",
            "Total GBP": "sum"
        })

        summary["Buy/Sell"] = summary["Quantity"].apply(
            lambda q: "Buy" if q > 0 else "Sell" if q < 0 else "Neutral"
        )

        xirr_results = []
        for stock in combined_df["Stock"].unique():
            stock_df = combined_df[combined_df["Stock"] == stock]
            cash_flows = list(zip(stock_df["Date"], stock_df["Cashflow"]))
            latest_date = stock_df["Date"].max()
            last_value = stock_df["Total INR"].sum()
            cash_flows.append((latest_date, last_value))
            xirr_val = calculate_xirr(cash_flows)
            xirr_results.append((stock, xirr_val))

        xirr_df = pd.DataFrame(xirr_results, columns=["Stock", "XIRR (%)"])
        final_summary = pd.merge(summary, xirr_df, on="Stock", how="left")

        latest_price_df = combined_df.sort_values("Date").groupby("Stock").last().reset_index()
        portfolio = summary[["Stock", "Quantity"]].merge(
            latest_price_df[["Stock", "Price"]], on="Stock", how="left"
        )
        portfolio["Holding Value (USD)"] = portfolio["Quantity"] * portfolio["Price"]
        portfolio["Holding Value (INR)"] = portfolio["Holding Value (USD)"] * get_exchange_rate(datetime.now())
        portfolio["Holding Value (EUR)"] = portfolio["Holding Value (USD)"] * usd_to_eur
        portfolio["Holding Value (GBP)"] = portfolio["Holding Value (USD)"] * usd_to_gbp

        final_summary = final_summary.merge(
            portfolio[["Stock", "Holding Value (USD)", "Holding Value (INR)", "Holding Value (EUR)", "Holding Value (GBP)"]],
            on="Stock",
            how="left"
        )

        final_summary = final_summary.round(2)

        combined_df = combined_df.sort_values("Date")
        start_date = combined_df["Date"].min()
        end_date = combined_df["Date"].max()

        portfolio_timeseries = {}
        date_range = pd.date_range(start=start_date, end=end_date)

        for date in date_range:
            daily_df = combined_df[combined_df["Date"] <= date]
            holdings = daily_df.groupby("Stock", as_index=False)["Quantity"].sum()
            latest_prices = daily_df.sort_values("Date").groupby("Stock").last().reset_index()[["Stock", "Price"]]
            merged = pd.merge(holdings, latest_prices, on="Stock", how="inner")
            merged["Value (USD)"] = merged["Quantity"] * merged["Price"]
            total_usd = merged["Value (USD)"].sum()
            portfolio_timeseries[date.strftime("%Y-%m-%d")] = {
                "USD": total_usd,
                "INR": total_usd * get_exchange_rate(date),
                "EUR": total_usd * usd_to_eur,
                "GBP": total_usd * usd_to_gbp
            }

        return render(request, "upload.html", {
            "message": "✅ Files processed successfully!",
            "data": final_summary.to_html(index=False, classes="table table-striped"),
            "raw": combined_df.to_html(index=False, classes="table table-sm", border=0),
            "timeseries": portfolio_timeseries
        })

    return render(request, "upload.html")
