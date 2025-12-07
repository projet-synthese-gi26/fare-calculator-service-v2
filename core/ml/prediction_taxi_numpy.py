import numpy as np

def charger_donnees(fichier_csv):
    """
    Charge les données du CSV et retourne X_train et Y_train.
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

def predict_knn(X_train, Y_train, X_new, W, k=3):
    """
    Effectue la prédiction k-NN avec pondération des features.
    """
    # 1. Standardisation (Z-score)
    mean = np.mean(X_train, axis=0)
    std = np.std(X_train, axis=0)
    std[std == 0] = 1.0 # Éviter division par zéro
    
    X_train_std = (X_train - mean) / std
    X_new_std = (X_new - mean) / std 
    
    # 2. Normalisation des poids
    W = np.array(W)
    W_norm = W / np.sum(W)
    
    # 3. Calcul des distances pondérées
    predictions = []
    confiances = []
    
    if X_new_std.ndim == 1:
        X_new_std = X_new_std.reshape(1, -1)
        
    for x_query in X_new_std:
        diff_sq = (X_train_std - x_query) ** 2
        weighted_dist_sq = np.sum(W_norm * diff_sq, axis=1)
        distances = np.sqrt(weighted_dist_sq)
        
        # 4. Sélection des k voisins
        k_indices = np.argsort(distances)[:k]
        k_distances = distances[k_indices]
        k_prix = Y_train[k_indices]
        
        # 5. Calcul du prix pondéré inverse de la distance
        epsilon = 1e-6
        weights_inv = 1.0 / (k_distances + epsilon)
        
        prix_estime = np.sum(k_prix * weights_inv) / np.sum(weights_inv)
        
        # 6. Calcul de la confiance
        confiance = (k / (k + np.sum(k_distances))) * 100
        
        predictions.append(prix_estime)
        confiances.append(confiance)
        
    return predictions, confiances

if __name__ == "__main__":
    print("--- Prédiction de Prix de Taxi (Numpy) ---")
    
    fichier_csv = "trajets_taxi.csv"
    X_train, Y_train = charger_donnees(fichier_csv)
    
    if X_train is None:
        exit()
        
    print(f"Données chargées: {X_train.shape} trajets")
    
    # Importation des poids optimaux calculés par régression
    try:
        from calculate_weights_taxi import get_optimal_weights
        print("Calcul des poids optimaux via régression...")
        W = get_optimal_weights(fichier_csv)
    except ImportError:
        print("Module calculate_weights_taxi non trouvé, utilisation des poids par défaut.")
        # Poids par défaut (13 features)
        W = [1.0] * 13
    
    print(f"Poids appliqués: {W}")
    
    # Exemple de nouveau trajet (basé sur la ligne 2 du CSV pour test)
    # 3.855302,11.547589,essomba,3.864589,11.496399,melen,400,8.6,8.7,1.49,21,0.3,20.0,0,0,0,0,0
    nouveau_trajet = np.array([
        3.855302, 11.547589, 3.864589, 11.496399, # Coords
        8.6, 8.7, # Dist, Dur
        1.49, 21, 0.3, # Sin, Vir, Force
        20.0, # Congestion
        0, 0, 0, 0, 0 # Cats
    ])
    
    print("\n--- Prédiction pour un nouveau trajet (Test) ---")
    prix_estimes, confiances = predict_knn(X_train, Y_train, nouveau_trajet, W, k=5)
    
    print(f"-> Prix Estimé : {prix_estimes[0]:.0f} FCFA")
    print(f"-> Niveau de Confiance : {confiances[0]:.2f} %")
