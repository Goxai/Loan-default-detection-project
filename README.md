# LOAN DEFAULTER DETECTION PROJECT

## The Business Problem
## A bank wants to predict which loan applicants are likely to default before approving their loans. Your job is to build a model that flags high-risk applicants.

### Your Full Project Summary

### phases of how i completed this project:

#### phase 1 - Loaded and understood 255,347 real loan records 
#### phase 1 -  Identified class imbalance, distributions, key patterns 
#### phase 2 -  Dropped identifiers, encoded 7 categorical columns 
#### Phase 2 - Scaled 9 numerical features, verified correlations 
#### Phase 3 - Built 3 ML models with pipelines 
#### Phase 3 - Evaluated with AUC, recall, confusion matrix 
#### Phase 3 - Cross validated for stability 
#### Phase 3 - Extracted feature importances 
#### Final - Wrote a CEO-level business report 


## Data Cleaning 
#### I downloaded from kaggle
#### Cleaned the dataset using python pandas

## Exploratory Data Analysis
#### from my analysis:
#### 255,347 applicants
#### 225,694 non defaulters
#### 29,653 defaulters (11.61% defaulter rate)

## problem scale
#### I analyzed the 255,347 loan applicants and 29,653 applicants defaulted(11.61%) that is 1 i every 9 applicants defaulted.
#### My analysis revealed that younger applicants from 17 - 28 with default rate of 20.02% and 29 - 39 with default rate of 14.66% both significantly higher than applicants over 50
#### who default at just 5.2%
#### Unemployed applicants with a default rate of 13.5% and it is the highest in the employment type
#### the applicant who default tends to borrow larger amounts, the median for default is $150,000 compared $125,000 for non defaulter.

## Models
#### i trained three machine learning models, logistic regression, decision tree and random forest. logistic regression performed best,
#### achieving an auc of 0.75 and correctly identifying 70% of the actual defaulters making it most useful model.

## Model Reliability
#### The model was tested across 5 different data splits and produced consistent results every time with a standard deviation of 0.002.
#### This means the model's performance is stable and reliable, it is not getting lucky on one particular set of data.

## The Confusion Matrix
#### In our test set of 51,070 applicants, the model correctly identified 4,151 defaulters before they were given loans.
#### At an average loan of $125,000, this represents approximately 519 million in avoided losses. However, 1,780 defaulters were missed
#### a potential exposure of $222 million. Additionally, 14,734 creditworthy customers were flagged as risky, which represents lost interest revenue the bank should consider.

## Top Risk Factors
#### The five strongest predictors of loan default are:
#### applicant age, interest rate on the loan, income level, loan amount, and months of employment history.
#### These five factors alone explain the majority of default risk and should be the primary inputs to any loan decision.

##  Most At-Risk Customer Profile
#### The highest risk applicant profile is:
#### under 39 years old, unemployed or part-time employed, applying for a loan above 150,000, with a high interest rate and limited employment history.
#### The bank should apply stricter criteria or request additional collateral when multiple of these factors are present together.

## Recommendations
#### I recommend the bank:
#### 1. Automatically flag applications from unemployed applicants
####   under 30 requesting loans above 150,000 for manual review
#### 2. Deploy this model as a scoring system — any applicant
####    with a predicted default probability above 30% requires
####    additional documentation or a co-signer
#### 3. Retrain the model every 6 months as new loan data comes in
#### 4. Invest in collecting more data on applicants under 28
####    as this group carries the highest default risk
