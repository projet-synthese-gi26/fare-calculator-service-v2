import numpy as np

def charger_donnees(fichier_csv):
    """
    Charge les données du CSV et retourne X (features) et Y (target).
    """
    try:
        # Indices des colonnes pour X (15 features)
        # Indices des colonnes pour X (13 features)
        # 0:depart_lat, 1:depart_lon, 3:arrivee_lat, 4:arrivee_lon, 
        # 7:distance_km, 8:duree_min, 
        # 9:sinuosite_indice, 10:nb_virages, 11:force_virages, 
        # 12:congestion_moyen, 
        # 13:meteo_bin, 14:periode_bin, 15:zone_bin
        cols_X = (0, 1, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14, 15)
        col_Y = 6 # Prix
        
        data_X = np.genfromtxt(fichier_csv, delimiter=',', skip_header=1, usecols=cols_X)
        data_Y = np.genfromtxt(fichier_csv, delimiter=',', skip_header=1, usecols=col_Y)
        
        return data_X, data_Y
    except Exception as e:
        print(f"Erreur lors du chargement: {e}")
        return None, None

def calculer_poids_regression(X, Y):
    """
    Calcule les poids (coefficients) à l'aide de la régression linéaire (Moindres Carrés).
    """
    # 1. Standardisation des données (Important pour comparer les coefficients)
    mean = np.mean(X, axis=0)
    std = np.std(X, axis=0)
    std[std == 0] = 1.0
    
    X_std = (X - mean) / std
    
    # 2. Ajout de la colonne de biais (intercept) pour la régression
    X_b = np.c_[np.ones((X_std.shape[0], 1)), X_std]
    
    # 3. Résolution de l'équation normale
    theta, residuals, rank, s = np.linalg.lstsq(X_b, Y, rcond=None)
    
    # Le premier coefficient est l'intercept (biais), les suivants sont les poids des features
    coeffs = theta[1:]
    
    return coeffs

def get_optimal_weights(fichier_csv="trajets_taxi.csv"):
    """
    Charge les données, calcule les poids par régression et retourne 
    une liste de poids normalisés (somme ~ 10) pour KNN.
    """
    X, Y = charger_donnees(fichier_csv)
    if X is None:
        # Fallback si erreur - 13 features
        return [1.0] * 13
        
    coeffs = calculer_poids_regression(X, Y)
    
    # Valeur absolue pour KNN (distances)
    abs_coeffs = np.abs(coeffs)
    
    # Normalisation pour avoir une somme autour de 10 (échelle lisible)
    total = np.sum(abs_coeffs)
    if total == 0:
        return [1.0] * 13
        
    normalized_weights = abs_coeffs / total * 10
    
    # Retourne une liste Python standard
    return list(np.round(normalized_weights, 2))

if __name__ == "__main__":
    print("--- Calcul des Poids par Régression Linéaire (Taxi Dataset) ---")
    
    fichier_csv = "trajets_taxi.csv"
    X, Y = charger_donnees(fichier_csv)
    
    if X is None:
        exit()
        
    print(f"Données chargées: {X.shape} trajets")
    
    coeffs = calculer_poids_regression(X, Y)
    
    # Noms des features pour l'affichage
    feature_names = [
        "Latitude Depart", "Longitude Depart", 
        "Latitude Arrivee", "Longitude Arrivee",
        "Distance", "Duree",
        "Sinuosite", "Nb Virages", "Force Virages",
        "Congestion", 
        "Congestion", 
        "Meteo", "Heure de Pointe", "Zone"
    ]
    
    print("\nImportance des Features (Coefficients Standardisés) :")
    print("-" * 50)
    
    # Affichage trié par valeur absolue (importance)
    indices_tries = np.argsort(np.abs(coeffs))[::-1]
    
    for i in indices_tries:
        print(f"{feature_names[i]:<20} : {coeffs[i]:.4f}")
        
    print("-" * 50)
    
    # Proposition de poids normalisés (valeur absolue) pour KNN
    abs_coeffs = np.abs(coeffs)
    normalized_weights = abs_coeffs / np.sum(abs_coeffs) * 10 
    
    print("\nProposition de Poids pour KNN (Normalisés sur 10) :")
    print(list(np.round(normalized_weights, 2)))
