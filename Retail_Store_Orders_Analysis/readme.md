# 🛒 Retail Store Orders Analysis

## 🔍 About the Project

In this project, I used SQL to answer business questions about an online retail store's orders, customers, products, and shipping.

The data is spread across 8 related tables, so most questions needed joining several tables together.

---

## 📂 Dataset

The `orders` database has 8 tables (about 470 rows in total):

| Table | What it holds | Rows |
|---|---|---|
| ORDER_HEADER | Order date, status, payment, shipper | 70 |
| ORDER_ITEMS | Products and quantities in each order | 205 |
| ONLINE_CUSTOMER | Customer details | 52 |
| ADDRESS | Customer city, state, country | 57 |
| PRODUCT | Price, stock, size, and weight of each product | 60 |
| PRODUCT_CLASS | Product categories | 14 |
| CARTON | Box sizes available for packing | 7 |
| SHIPPER | Shipping companies | 6 |

---

## 🛠 Tools Used

* **MySQL** – database setup and analysis

---

## ❓ Business Questions I Answered

1. **Which carton should we use?**
   For a given order, find the smallest carton that can hold all its items, using product size (length × width × height) and quantity.

2. **Who are our bulk buyers?**
   Find customers who bought more than 10 products in a single shipped order.

3. **How much did each recent order ship?**
   Show the total quantity shipped for each order after order ID 10060, with customer details.

4. **What sells best outside India and the USA?**
   Find the product category with the highest shipped quantity in international markets, along with its total value.

---

## 🧠 SQL Concepts Used

* Joins across up to 6 tables (LEFT JOIN)
* Subqueries
* Aggregations (SUM) with GROUP BY and HAVING
* Filtering with WHERE, sorting with ORDER BY, and LIMIT

---

## 📊 Key Findings

* **Packaging:** Carton 40 is the smallest box that fits all items in order 10006.
* **Bulk buyers:** 11 shipped orders had more than 10 items, placed by 8 customers. The biggest was Komal's order of 53 items, and Anita placed the most bulk orders (3).
* **Recent orders:** The 6 shipped orders after ID 10060 were all small (1 to 8 items each).
* **International markets:** Stationery shipped the most items outside India and the USA (13 items). But Furniture earned the most money ($6,500) from just 2 items, so the top-selling category is not the top-earning one.

---

## ▶️ How to Run

1. Run `SettingData.sql` in MySQL. It creates the `orders` database, builds the tables, and loads the data.
2. Run `RetailStoreOrderAnlaysis.sql` to see the analysis queries and results.

---

## 📁 Project Files

| File | Description |
|---|---|
| `SettingData.sql` | Creates the database and loads the data |
| `RetailStoreOrderAnlaysis.sql` | Analysis queries for the 4 business questions |

---

## 💡 What I Learned

* How to break a business question into SQL steps
* How to join many related tables correctly
* How to use subqueries to compare values (like carton volume vs. total item volume)
* Why clean, well-structured data matters before analysis
