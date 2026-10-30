# 🗳️ Election Data Analysis

## 🔍 About the Project

In this project, I analyzed UK election survey data to understand **what drives party preference** (Labour vs. Conservative), then compared 8 machine learning models to predict how a person will vote.

---

## 📂 Dataset

* **1,525 survey records** (1,517 after removing 8 duplicates), with no missing values
* Vote choice (Labour / Conservative)
* Age and gender
* Views of the national and household economy (1–5)
* Ratings of party leaders Blair and Hague (1–5)
* Attitude towards Europe (1–11, higher = more Eurosceptic)
* Political knowledge (0–3)

About **70% voted Labour** and 30% Conservative, so the classes are imbalanced.

---

## 🛠 Tools Used

* Python (Pandas, NumPy)
* Matplotlib, Seaborn
* Scikit-learn, imbalanced-learn (SMOTE)

---

## 🔍 What I Did

### 🧹 Data Cleaning & Preparation

* Removed 8 duplicate records
* Capped outliers using the IQR method
* Converted vote and gender into numeric (dummy) variables
* Scaled numeric columns with Min-Max scaling
* Split the data 70% train / 30% test

### 📊 Exploratory Data Analysis

* Checked each variable with descriptive statistics, histograms, and box plots
* Compared Labour and Conservative voters across every variable
* Used a pair plot and correlation heatmap to see how variables relate
* Calculated how each group voted (by leader rating, attitude towards Europe, age, and gender)

### 🤖 Model Comparison

* Built and compared 8 models: Logistic Regression, LDA, Naive Bayes, KNN, Random Forest, Bagging, AdaBoost, and Gradient Boosting
* Tuned Logistic Regression with GridSearchCV
* Tested SMOTE to handle the class imbalance, and used 10-fold cross-validation

---

## 📈 Key Findings

* **Leader ratings matter most.** 98% of people who gave Blair the top rating voted Labour, and 81% who gave Hague the top rating voted Conservative.
* **Attitude towards Europe:** only 5% of the most pro-Europe voters chose Conservative, compared with about 50% of the most Eurosceptic.
* **Economy:** Labour voters rated the national economy higher on average (3.4 vs. 2.8 out of 5).
* **Age:** voters over 60 were more likely to vote Conservative (37%) than voters under 40 (25%).
* **Gender** made little difference (32% of women vs. 29% of men voted Conservative).
* **Models:** most models reached about 81–83% accuracy on test data. Logistic Regression was a strong, simple choice (83% accuracy, AUC 0.89). Random Forest and Bagging scored 100% on training data but only about 83% on test data, a sign of overfitting.

---

## 💡 What I Learned

* How to explore survey data before modeling
* How to compare many models fairly on the same test data
* How to spot overfitting by comparing training and test scores
* How class imbalance affects model results

---

## 🔮 Future Improvements

* Build an interactive dashboard to show the voter groups visually
* Perform deeper segmentation of voters
* Expand the analysis with additional datasets

---

## 🙌 Final Thoughts

This project helped me focus on **thinking like a data analyst: understanding the data first and using it to explain real-world behavior**, rather than just building models.
