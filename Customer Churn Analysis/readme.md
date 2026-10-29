# 📊 Customer Churn Analysis

## 🔍 About the Project

In this project, I analyzed customer data from an e-commerce company to understand **why customers leave (churn)** and which customers are most at risk.

My focus was on **cleaning messy real-world data, exploring patterns, and turning them into business insights.**

This project was done as part of my capstone work for the PGDM in Data Science and Business Analytics (Great Learning / UT Austin).

---

## 🎯 Business Problem

The company is facing strong competition and wants to keep its existing customers. Churn is costly here because **one account can include several customers**, so losing one account means losing more than one person.

My goals were to:

* Understand what drives churn
* Find which customers are more likely to leave
* Suggest practical ways to keep them

---

## 📂 About the Data

* **11,260 customer accounts**
* **19 columns**, including tenure, city tier, payment method, complaints, customer service contacts, revenue, cashback, and login device
* Target column: **Churn** (1 = left, 0 = stayed)

The dataset was provided as part of the course and is not included in this repository.

---

## 🛠️ Tools Used

* **Python:** Pandas, NumPy
* **Visualization:** Matplotlib, Seaborn
* **Scikit-Learn:** label encoding, scaling, K-Means clustering

---

## 🧹 Data Cleaning

The raw data was messy, so I:

* Found symbols like `#`, `$`, `@`, `*`, and `+` mixed into number columns and converted them to missing values
* Fixed inconsistent labels (for example, `F` → `Female`, `Regular +` → `Regular Plus`)
* Filled in missing values
* Capped outliers using the IQR method
* Scaled numeric columns with Min-Max scaling

---

## 📈 Exploratory Data Analysis (EDA)

* Checked the distribution of each variable with histograms and box plots
* Compared churned vs. non-churned customers
* Built a correlation heatmap to see which factors relate most to churn
* Plotted churn rates by payment method, gender, account segment, marital status, and login device

---

## 🔑 Key Findings

* **16.8% of customers churned** (1,896 out of 11,260), so the data is imbalanced: most customers stayed.
* **Complaints** had the strongest link to churn: customers who complained in the last year were more likely to leave.
* **Tenure** had the next strongest link: **newer customers churn more**, while long-term customers tend to stay.
* Customers who **contacted customer service recently** were also somewhat more likely to churn.
* **Account segment:** Regular Plus customers churned the most (about 27%), while Super Plus customers churned the least (about 5%).
* **Marital status:** Single customers churned the most (about 27%), compared with about 12% for married customers.
* **Payment method:** Cash on Delivery (about 25%) and E-wallet (about 23%) users churned the most; Credit Card users churned the least (about 14%).
* **Login device:** Computer users churned slightly more (about 20%) than mobile users (about 16%).

---

## 👥 Customer Segmentation

I used **K-Means clustering** to group customers with similar behavior, testing different numbers of groups with the **elbow method** and **silhouette score**. The segments showed clearly different churn rates, meaning some customer groups are much more at risk than others.

---

## 💡 Recommendations

* **Act fast on complaints:** complaints are the strongest warning sign, so resolve them quickly and follow up.
* **Focus on new customers:** onboarding offers and early check-ins can help during the first months, when churn is highest.
* **Use targeted offers:** focus retention offers on high-risk groups, such as Regular Plus and single customers, instead of giving discounts to everyone.
* **Encourage card payments:** Cash on Delivery and E-wallet users churn more, so small rewards for paying by card may help build loyalty.

---

## 🔄 What I Would Improve

Looking back at this project, I would:

* Make sure the final clustering uses the number of clusters chosen by the silhouette score
* Leave the Churn column out of the clustering, then compare churn rates across segments afterward
* Fill missing values with the median instead of 0
* Add a prediction model (such as logistic regression) to score each customer's churn risk

---

## 📈 What I Learned

* How to clean messy real-world data
* How to find meaningful patterns through EDA
* How to think about results from a business point of view, not just a technical one
