import joblib
import pickle
import sys
import os
import binascii

# Ajouter le dossier courant au path
sys.path.append(os.getcwd())

pkl_path = 'core/ml/models/classifier_model.pkl'

print(f"--- Inspection de {pkl_path} ---")

if not os.path.exists(pkl_path):
    print(f"ERREUR CRITIQUE: Le fichier {pkl_path} n'existe pas !")
    sys.exit(1)

# 1. INSPECTION DES EN-TÊTES (Le test de vérité)
with open(pkl_path, 'rb') as f:
    header = f.read(50)
    print(f"Début du fichier (Hex): {binascii.hexlify(header)}")
    print(f"Début du fichier (Texte brut): {header}")
    
    # Vérification signature Git LFS
    if b"version https://git-lfs" in header:
        print("\n!!! ALERTE : Ce fichier est un pointeur Git LFS, pas le vrai modèle !!!")
        print("Solution : Lancez 'git lfs pull' ou téléchargez le fichier 'Raw'.")
        sys.exit(1)

print("-" * 30)

# 2. TENTATIVE AVEC JOBLIB (Standard Scikit-Learn)
try:
    print("Tentative 1 : Chargement avec joblib...")
    model = joblib.load(pkl_path)
    print("✅ SUCCÈS avec joblib !")
except Exception as e:
    print(f"❌ Echec joblib: {e}")
    
    # 3. TENTATIVE AVEC PICKLE (Fallback)
    try:
        print("\nTentative 2 : Chargement avec pickle standard...")
        with open(pkl_path, 'rb') as f:
            model = pickle.load(f)
        print("✅ SUCCÈS avec pickle !")
    except Exception as e2:
        print(f"❌ Echec pickle: {e2}")
        print("\nDiagnostic final : Le fichier semble corrompu ou illisible.")
        sys.exit(1)

# 4. ANALYSE DU MODÈLE
print("-" * 30)
print(f"Type du modèle: {type(model)}")

if hasattr(model, 'predict'):
    print("Le modèle a une méthode 'predict'.")
    
# Vérification spécifique Scikit-Learn
if hasattr(model, 'n_features_in_'):
    print(f"Nombre de features attendues: {model.n_features_in_}")
elif hasattr(model, 'n_features_'):
    print(f"Nombre de features (vieux sklearn): {model.n_features_}")
    
if hasattr(model, 'classes_'):
    print(f"Classes: {model.classes_}")