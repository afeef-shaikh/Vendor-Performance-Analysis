import os
import sqlite3
import logging

import numpy as np
import pandas as pd

from ingestion_db import ingest_db

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    filename="logs/get_vendor_summary.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filemode="a"
)

OUTPUT_CSV = "vendor_sales_summary.csv"


def create_vendor_summary(conn):
    '''Merge purchases, prices, sales and invoices into one row per vendor-brand.

    Freight is only recorded per vendor invoice, so this query returns the
    vendor's total freight (VendorFreightCost). clean_data() allocates it to
    brands. Summing VendorFreightCost across brand rows would count the same
    freight once per brand.
    '''
    vendor_sales_summary = pd.read_sql_query("""WITH FreightSummary AS (
        SELECT
            VendorNumber,
            SUM(Freight) AS VendorFreightCost
        FROM vendor_invoice
        GROUP BY VendorNumber
    ),

    PurchaseSummary AS (
        -- One row per vendor-brand. Grouping by name, description or price as well
        -- would split a brand whose text or price varies, and each split row would
        -- pick up the brand's full sales in the join below.
        SELECT
            p.VendorNumber,
            MAX(TRIM(p.VendorName)) AS VendorName,
            p.Brand,
            MAX(TRIM(p.Description)) AS Description,
            SUM(p.Dollars) * 1.0 / SUM(p.Quantity) AS PurchasePrice,
            MAX(pp.Price) AS ActualPrice,
            MAX(pp.Volume) AS Volume,
            SUM(p.Quantity) AS TotalPurchaseQuantity,
            SUM(p.Dollars) AS TotalPurchaseDollars
        FROM purchases p
        JOIN purchase_prices pp
            ON p.Brand = pp.Brand
        WHERE p.PurchasePrice > 0
        GROUP BY p.VendorNumber, p.Brand
    ),

    SalesSummary AS (
        SELECT
            VendorNo,
            Brand,
            SUM(SalesQuantity) AS TotalSalesQuantity,
            SUM(SalesDollars) AS TotalSalesDollars,
            SUM(SalesPrice) AS TotalSalesPrice,
            SUM(ExciseTax) AS TotalExciseTax
        FROM sales
        GROUP BY VendorNo, Brand
    )

    SELECT
        ps.VendorNumber,
        ps.VendorName,
        ps.Brand,
        ps.Description,
        ps.PurchasePrice,
        ps.ActualPrice,
        ps.Volume,
        ps.TotalPurchaseQuantity,
        ps.TotalPurchaseDollars,
        ss.TotalSalesQuantity,
        ss.TotalSalesDollars,
        ss.TotalSalesPrice,
        ss.TotalExciseTax,
        fs.VendorFreightCost
    FROM PurchaseSummary ps
    LEFT JOIN SalesSummary ss
        ON ps.VendorNumber = ss.VendorNo
        AND ps.Brand = ss.Brand
    LEFT JOIN FreightSummary fs
        ON ps.VendorNumber = fs.VendorNumber
    ORDER BY ps.TotalPurchaseDollars DESC""", conn)

    return vendor_sales_summary


def clean_data(df):
    '''Clean the summary table and add the analysis columns.'''
    df = df.copy()
    df['Volume'] = df['Volume'].astype('float')

    # brands with no sales or no invoices come back as NULL from the LEFT JOINs
    fill_cols = ['TotalSalesQuantity', 'TotalSalesDollars', 'TotalSalesPrice',
                 'TotalExciseTax', 'VendorFreightCost']
    df[fill_cols] = df[fill_cols].fillna(0)

    df['VendorName'] = df['VendorName'].str.strip()
    df['Description'] = df['Description'].str.strip()

    # A few vendor numbers appear under two names (e.g. after a rename).
    # Use the most common name per vendor number so vendor-level totals don't split.
    canonical_name = df.groupby('VendorNumber')['VendorName'].agg(lambda s: s.value_counts().index[0])
    df['VendorName'] = df['VendorNumber'].map(canonical_name)

    # Allocate each vendor's freight to its brands by share of purchase dollars,
    # so FreightCost can be summed across rows without double counting.
    vendor_purchases = df.groupby('VendorNumber')['TotalPurchaseDollars'].transform('sum')
    df['FreightCost'] = np.where(
        vendor_purchases > 0,
        df['VendorFreightCost'] * df['TotalPurchaseDollars'] / vendor_purchases,
        0.0
    )

    # Cost of goods sold = units sold x unit cost. Subtracting total purchase
    # dollars instead would count unsold stock as a loss.
    df['COGS'] = df['TotalSalesQuantity'] * df['PurchasePrice']
    df['GrossProfit'] = df['TotalSalesDollars'] - df['COGS']
    df['ProfitMargin'] = np.where(
        df['TotalSalesDollars'] > 0,
        df['GrossProfit'] / df['TotalSalesDollars'] * 100,
        np.nan
    )
    df['ProfitAfterFreight'] = df['GrossProfit'] - df['FreightCost']

    df['StockTurnover'] = df['TotalSalesQuantity'] / df['TotalPurchaseQuantity']
    df['SalesToPurchaseRatio'] = np.where(
        df['TotalPurchaseDollars'] > 0,
        df['TotalSalesDollars'] / df['TotalPurchaseDollars'],
        np.nan
    )

    # Stock bought this period that did not sell this period, valued at cost.
    # Ignores opening inventory, so it is an estimate of inventory build-up.
    df['UnsoldUnits'] = (df['TotalPurchaseQuantity'] - df['TotalSalesQuantity']).clip(lower=0)
    df['UnsoldInventoryValue'] = df['UnsoldUnits'] * df['PurchasePrice']

    return df


if __name__ == '__main__':
    conn = sqlite3.connect('inventory.db')

    logging.info('Creating Vendor Summary Table.....')
    summary_df = create_vendor_summary(conn)
    logging.info(summary_df.head())

    logging.info('Cleaning Data.....')
    clean_df = clean_data(summary_df)
    logging.info(clean_df.head())

    logging.info('Ingesting data.....')
    ingest_db(clean_df, 'vendor_sales_summary', conn)
    clean_df.to_csv(OUTPUT_CSV, index=False)
    logging.info(f'Wrote {OUTPUT_CSV} ({len(clean_df)} rows)')
    logging.info('Completed')
