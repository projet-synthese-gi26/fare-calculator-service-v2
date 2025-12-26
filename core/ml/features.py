import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin


class WeightedStandardScaler(BaseEstimator, TransformerMixin):
    """
    Scaler personnalisé utilisé lors de l'entraînement du modèle.
    Doit exister pour permettre le chargement du pickle.
    """

    def __init__(self, weights=None):
        self.weights = weights

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        self.mean_ = np.mean(X, axis=0)
        self.std_ = np.std(X, axis=0)
        self.std_[self.std_ == 0] = 1.0
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        X_scaled = (X - self.mean_) / self.std_
        if self.weights is not None:
            X_scaled = X_scaled * self.weights
        return X_scaled
