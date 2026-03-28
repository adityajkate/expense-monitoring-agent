"""
ML-Based Transaction Categorization
Replaces keyword matching with Random Forest classifier
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import os
from typing import Tuple, Dict, List


class MLCategorizer:
    """Machine Learning based transaction categorizer"""

    def __init__(self, model_path: str = "models/categorizer_model.pkl"):
        self.model_path = model_path
        self.model = None
        self.vectorizer = None
        self.categories = [
            "Cloud Services",
            "Travel",
            "Food & Dining",
            "Office Expenses",
            "Software",
            "Marketing",
            "Operations",
            "Miscellaneous"
        ]

    def _create_features(self, df: pd.DataFrame) -> np.ndarray:
        """Create feature matrix from transaction data"""
        # Combine vendor and description for text features
        text_data = df['vendor'].fillna('') + ' ' + df['description'].fillna('')

        # TF-IDF vectorization
        if self.vectorizer is None:
            self.vectorizer = TfidfVectorizer(
                max_features=200,
                ngram_range=(1, 2),
                min_df=2,
                stop_words='english'
            )
            X_text = self.vectorizer.fit_transform(text_data)
        else:
            X_text = self.vectorizer.transform(text_data)

        # Numerical features
        amount_normalized = (df['amount'] - df['amount'].mean()) / df['amount'].std()
        X_amount = amount_normalized.values.reshape(-1, 1)

        # Combine features
        X = np.hstack([X_text.toarray(), X_amount])

        return X

    def train(self, df: pd.DataFrame, test_size: float = 0.2) -> Dict:
        """
        Train the ML model on labeled data

        Args:
            df: DataFrame with columns: vendor, description, amount, category
            test_size: Fraction of data to use for testing

        Returns:
            Dictionary with training metrics
        """
        print(f"Training ML categorizer on {len(df)} transactions...")

        # Create features
        X = self._create_features(df)
        y = df['category'].values

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        # Train Random Forest
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=20,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )

        self.model.fit(X_train, y_train)

        # Evaluate
        y_pred = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        print(f"\nTraining complete!")
        print(f"Accuracy: {accuracy:.2%}")
        print("\nClassification Report:")
        print(classification_report(y_test, y_pred))

        # Save model
        self._save_model()

        return {
            "accuracy": accuracy,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "categories": self.categories
        }

    def predict(self, vendor: str, description: str, amount: float) -> Tuple[str, float]:
        """
        Predict category for a single transaction

        Args:
            vendor: Vendor name
            description: Transaction description
            amount: Transaction amount

        Returns:
            Tuple of (category, confidence)
        """
        if self.model is None:
            self._load_model()

        # Create DataFrame for feature extraction
        df = pd.DataFrame([{
            'vendor': vendor,
            'description': description,
            'amount': amount
        }])

        # Create features
        X = self._create_features(df)

        # Predict with probabilities
        category = self.model.predict(X)[0]
        probabilities = self.model.predict_proba(X)[0]
        confidence = probabilities.max()

        return category, confidence

    def predict_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Predict categories for multiple transactions

        Args:
            df: DataFrame with columns: vendor, description, amount

        Returns:
            DataFrame with added columns: category_ml, confidence_ml
        """
        if self.model is None:
            self._load_model()

        # Create features
        X = self._create_features(df)

        # Predict
        categories = self.model.predict(X)
        probabilities = self.model.predict_proba(X)
        confidences = probabilities.max(axis=1)

        # Add to dataframe
        df['category_ml'] = categories
        df['confidence_ml'] = confidences

        return df

    def _save_model(self):
        """Save trained model and vectorizer to disk"""
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)

        model_data = {
            'model': self.model,
            'vectorizer': self.vectorizer,
            'categories': self.categories
        }

        joblib.dump(model_data, self.model_path)
        print(f"\nModel saved to {self.model_path}")

    def _load_model(self):
        """Load trained model from disk"""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Model not found at {self.model_path}. Please train the model first."
            )

        model_data = joblib.load(self.model_path)
        self.model = model_data['model']
        self.vectorizer = model_data['vectorizer']
        self.categories = model_data['categories']

        print(f"Model loaded from {self.model_path}")

    def is_trained(self) -> bool:
        """Check if model is trained and saved"""
        return os.path.exists(self.model_path)


def generate_training_data_from_keywords(df: pd.DataFrame) -> pd.DataFrame:
    """
    Bootstrap training data using existing keyword-based categorization
    This creates initial labeled data for ML training

    Args:
        df: DataFrame with vendor, description, amount columns

    Returns:
        DataFrame with added 'category' column
    """
    CATEGORIES = {
        "Cloud Services": ["aws", "azure", "gcp", "cloud", "hosting", "digitalocean", "heroku", "linode"],
        "Travel": ["uber", "lyft", "flight", "hotel", "airbnb", "taxi", "airline", "booking", "delta", "marriott"],
        "Food & Dining": ["starbucks", "chipotle", "subway", "panera", "restaurant", "cafe", "zomato", "swiggy", "doordash"],
        "Office Expenses": ["office", "supplies", "furniture", "depot", "staples", "ikea"],
        "Software": ["adobe", "microsoft", "slack", "zoom", "github", "atlassian", "jetbrains"],
        "Marketing": ["google ads", "facebook", "linkedin", "mailchimp", "hubspot", "salesforce"],
        "Operations": ["utilities", "rent", "insurance", "payroll", "legal", "accounting", "electric", "internet"]
    }

    def assign_category(row):
        vendor_desc = (str(row["vendor"]) + " " + str(row["description"])).lower()
        scores = {}

        for category, keywords in CATEGORIES.items():
            score = sum(1 for kw in keywords if kw in vendor_desc)
            if score > 0:
                scores[category] = score

        if not scores:
            if row["amount"] > 5000:
                return "Operations"
            return "Miscellaneous"

        max_score = max(scores.values())
        top_categories = [cat for cat, score in scores.items() if score == max_score]

        if len(top_categories) > 1:
            return "Miscellaneous"

        return top_categories[0]

    df['category'] = df.apply(assign_category, axis=1)
    return df


if __name__ == "__main__":
    """
    Training script - run this to train the ML model
    """
    print("=" * 80)
    print("ML CATEGORIZER TRAINING")
    print("=" * 80)

    # Load sample data
    data_path = "../data/sample_expenses.csv"

    if not os.path.exists(data_path):
        print(f"Error: Sample data not found at {data_path}")
        print("Please generate sample data first: python data_generator.py")
        exit(1)

    df = pd.read_csv(data_path)
    print(f"\nLoaded {len(df)} transactions from {data_path}")

    # Generate training labels using keyword method
    print("\nGenerating training labels from keyword-based categorization...")
    df = generate_training_data_from_keywords(df)

    # Show category distribution
    print("\nCategory Distribution:")
    print(df['category'].value_counts())

    # Train ML model
    categorizer = MLCategorizer()
    metrics = categorizer.train(df)

    print("\n" + "=" * 80)
    print("TRAINING COMPLETE")
    print("=" * 80)
    print(f"Model saved and ready to use!")
    print(f"Accuracy: {metrics['accuracy']:.2%}")
