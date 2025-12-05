import csv
import math

# --- FONCTIONS DU FICHIER ORIGINAL (prediction_from_csv.py) ---

def standardiser_donnees(data_X, params=None):
    """
    Standardise les données (Z-score) : (x - moyenne) / écart-type.
    """
    if not data_X:
        return [data_X, [], []]

    nb_features = len(data_X[0])
    nb_trajets = len(data_X)

    donnees_standardisees = []

    if params is None:
        # --- CALCUL DES PARAMÈTRES (Phase d'Entraînement) ---
        moyennes = []
        ecarts_types = []

        # Calculer la somme et les carrés pour chaque feature
        for j in range(nb_features):
            somme = 0.0
            for i in range(nb_trajets):
                somme += data_X[i][j]

            moyenne = somme / nb_trajets
            moyennes.append(moyenne)

            somme_carres_ecarts = 0.0
            for i in range(nb_trajets):
                somme_carres_ecarts += (data_X[i][j] - moyenne) ** 2

            # Écart-type d'échantillon
            ecart_type = math.sqrt(somme_carres_ecarts / nb_trajets)
            ecarts_types.append(ecart_type if ecart_type > 1e-6 else 1.0)

        # --- Standardisation avec les Nouveaux Paramètres ---
        for i in range(nb_trajets):
            trajet_standardise = []
            for j in range(nb_features):
                valeur_norm = (data_X[i][j] - moyennes[j]) / ecarts_types[j]
                trajet_standardise.append(valeur_norm)
            donnees_standardisees.append(trajet_standardise)

        return [donnees_standardisees, moyennes, ecarts_types]

    else:
        # --- APPLICATION DES PARAMÈTRES (Phase de Test/Prédiction) ---
        moyennes = params[0]
        ecarts_types = params[1]

        for i in range(nb_trajets):
            trajet_standardise = []
            for j in range(nb_features):
                valeur_norm = (data_X[i][j] - moyennes[j]) / ecarts_types[j]
                trajet_standardise.append(valeur_norm)
            donnees_standardisees.append(trajet_standardise)

        return [donnees_standardisees, None, None]


def selection_trajets_a_utiliser(k, matrice_historique_X_standardisee, vecteur_prix_Y, vecteur_poids_W,
                                 nouvelle_entree_X_standardisee):
    """
    Calcule les distances pondérées et sélectionne les k plus proches voisins.
    """
    somme_poids_W = sum(vecteur_poids_W)
    if somme_poids_W == 0:
        return []

    poids_normalises = [w / somme_poids_W for w in vecteur_poids_W]
    distances_et_prix = []

    for i, trajet_historique in enumerate(matrice_historique_X_standardisee):
        somme_carres_ponderee = 0.0

        for j, (q_j, d_j) in enumerate(zip(nouvelle_entree_X_standardisee, trajet_historique)):
            difference = q_j - d_j
            poids = poids_normalises[j]
            somme_carres_ponderee += poids * (difference ** 2)

        distance = math.sqrt(somme_carres_ponderee)
        distances_et_prix.append((distance, vecteur_prix_Y[i]))

    distances_et_prix.sort(key=lambda x: x[0])
    return distances_et_prix[:k]


def calcul_prix_et_incertitude(k_plus_proches, prix_reel_Y_test=None):
    """
    Calcule le prix estimé, le niveau de confiance et l'erreur.
    """
    erreur_absolue = -1.0
    erreur_relative = -1.0
    prix_estime = float('nan')
    niveau_confiance_pourcent = 0.0

    if not k_plus_proches:
        return [prix_estime, erreur_absolue, erreur_relative, niveau_confiance_pourcent]

    somme_prix_pondere = 0.0
    somme_poids_inverse = 0.0
    somme_distances = 0.0
    epsilon = 1e-6

    for distance, prix in k_plus_proches:
        somme_distances += distance
        if distance < epsilon:
            prix_estime = prix
            break
        poids_inverse = 1.0 / (distance + epsilon)
        somme_prix_pondere += prix * poids_inverse
        somme_poids_inverse += poids_inverse
    else:
        if somme_poids_inverse > 0:
            prix_estime = somme_prix_pondere / somme_poids_inverse

    k = len(k_plus_proches)
    if k > 0:
        niveau_confiance_pourcent = (k / (k + somme_distances)) * 100

    if prix_reel_Y_test is not None:
        if prix_estime is not float('nan'):
            erreur_absolue = abs(prix_estime - prix_reel_Y_test)
            if prix_reel_Y_test != 0:
                erreur_relative = (erreur_absolue / prix_reel_Y_test) * 100
            else:
                erreur_relative = float('inf')

    return [prix_estime, erreur_absolue, erreur_relative, niveau_confiance_pourcent]


# --- NOUVELLES FONCTIONS POUR TAXI ---

def charger_donnees_taxi(fichier_csv):
    """
    Charge les données de trajets_taxi.csv et extrait X_train et Y_train.
    """
    X_data = []
    Y_data = []
    
    # Indices des colonnes (0-based dans le CSV):
    # 0:depart_lat, 1:depart_lon, 3:arrivee_lat, 4:arrivee_lon, 
    # 7:distance_km, 8:duree_min, 
    # 9:sinuosite_indice, 10:nb_virages, 11:force_virages, 
    # 12:congestion_moyen, 
    # 13:code_categorical_4bits, 14:code_categorical_bin, 
    # 15:meteo_bin, 16:periode_bin, 17:zone_bin
    
    indices_X = [0, 1, 3, 4, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
    index_Y = 6 # Prix
    
    try:
        with open(fichier_csv, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            for row in reader:
                try:
                    # Extraction des features X
                    features = [float(row[i]) for i in indices_X]
                    X_data.append(features)
                    
                    # Extraction du target Y (prix)
                    prix = float(row[index_Y])
                    Y_data.append(prix)
                except ValueError:
                    continue # Skip malformed rows
                    
    except FileNotFoundError:
        print(f"Erreur: Le fichier {fichier_csv} est introuvable.")
        return [], []
        
    return X_data, Y_data

# --- MATH & ALGEBRE LINEAIRE (Pure Python) ---

def transpose(matrix):
    """Retourne la transposée d'une matrice."""
    return list(map(list, zip(*matrix)))

def matmul(A, B):
    """Multiplication matricielle A * B."""
    rows_A = len(A)
    cols_A = len(A[0])
    rows_B = len(B)
    cols_B = len(B[0])

    if cols_A != rows_B:
        raise ValueError("Dimensions incompatibles pour multiplication matricielle")

    C = [[0 for _ in range(cols_B)] for _ in range(rows_A)]
    for i in range(rows_A):
        for j in range(cols_B):
            for k in range(cols_A):
                C[i][j] += A[i][k] * B[k][j]
    return C

def identity(n):
    """Retourne une matrice identité de taille n x n."""
    return [[1 if i == j else 0 for j in range(n)] for i in range(n)]

def inverse(matrix):
    """
    Inverse une matrice carrée avec l'élimination de Gauss-Jordan.
    Retourne None si la matrice est singulière.
    """
    n = len(matrix)
    # Créer une matrice augmentée [A | I]
    aug = [row[:] + identity(n)[i] for i, row in enumerate(matrix)]

    # Élimination de Gauss-Jordan
    for i in range(n):
        # Recherche du pivot
        pivot_row = i
        for k in range(i + 1, n):
            if abs(aug[k][i]) > abs(aug[pivot_row][i]):
                pivot_row = k
        
        # Échange des lignes
        aug[i], aug[pivot_row] = aug[pivot_row], aug[i]
        
        pivot = aug[i][i]
        if abs(pivot) < 1e-10:
            return None # Matrice singulière

        # Normalisation de la ligne du pivot
        for j in range(i, 2 * n):
            aug[i][j] /= pivot
        
        # Élimination des autres lignes
        for k in range(n):
            if k != i:
                factor = aug[k][i]
                for j in range(i, 2 * n):
                    aug[k][j] -= factor * aug[i][j]

    # Extraction de la matrice inverse (partie droite de la matrice augmentée)
    inv = [row[n:] for row in aug]
    return inv

def mean_std(data):
    """Calcul la moyenne et l'écart-type de chaque colonne."""
    if not data:
        return [], []
    
    rows = len(data)
    cols = len(data[0])
    
    means = [0.0] * cols
    stds = [0.0] * cols
    
    for j in range(cols):
        col_sum = sum(row[j] for row in data)
        means[j] = col_sum / rows
        
        sq_diff_sum = sum((row[j] - means[j])**2 for row in data)
        stds[j] = math.sqrt(sq_diff_sum / rows)
        if stds[j] == 0: stds[j] = 1.0 # Éviter division par zéro
        
    return means, stds

def get_optimal_weights(fichier_csv="trajets_taxi.csv"):
    """
    Calcule les poids optimaux par régression linéaire (Moindres Carrés)
    en pur Python, sans NumPy.
    """
    X, Y = charger_donnees_taxi(fichier_csv)
    if not X:
        return [1.0] * 15

    # 1. Standardisation
    means, stds = mean_std(X)
    X_std = []
    for row in X:
        norm_row = [(val - m) / s for val, m, s in zip(row, means, stds)]
        X_std.append(norm_row)

    # 2. Ajout du biais (colonne de 1 au début)
    X_b = [[1.0] + row for row in X_std]
    
    # 3. Équation normale: theta = (X^T * X)^-1 * X^T * Y
    # Y doit être un vecteur colonne pour la multiplication
    Y_col = [[y] for y in Y]
    
    X_T = transpose(X_b)
    
    try:
        XT_X = matmul(X_T, X_b)
        
        # --- Regularisation Ridge (L2) ---
        # Ajout d'une petite valeur sur la diagonale pour rendre la matrice inversible
        # (XT * X + lambda * I)
        lambda_reg = 0.1
        n_cols = len(XT_X)
        for i in range(n_cols):
            XT_X[i][i] += lambda_reg
            
        XT_X_inv = inverse(XT_X)
        
        if XT_X_inv is None:
            print("Attention: Matrice singulière malgré la régularisation.")
            return [1.0] * 15
            
        XT_Y = matmul(X_T, Y_col)
        theta = matmul(XT_X_inv, XT_Y)
        
        # Le premier coefficient est le biais, les suivants sont les poids
        coeffs = [row[0] for row in theta[1:]]
        
        # 4. Normalisation des poids pour KNN (somme ~ 10)
        abs_coeffs = [abs(c) for c in coeffs]
        total = sum(abs_coeffs)
        
        if total == 0:
            return [1.0] * 15
            
        normalized_weights = [(c / total) * 10 for c in abs_coeffs]
        return [round(w, 2) for w in normalized_weights]

    except Exception as e:
        print(f"Erreur lors du calcul des poids: {e}")
        return [1.0] * 15


# --- MAIN ---

if __name__ == "__main__":
    print("--- Prédiction de Prix de Taxi (Pure Python) ---")
    
    # 1. Chargement des données
    fichier_csv = "trajets_taxi.csv"
    X_train, Y_train = charger_donnees_taxi(fichier_csv)
    
    if not X_train:
        exit()
        
    print(f"Données chargées: {len(X_train)} trajets")
    
    # 2. Calcul des poids optimaux (Pure Python)
    print("Calcul des poids optimaux via régression (Pure Python)...")
    W = get_optimal_weights(fichier_csv)
        
    print(f"Poids appliqués: {W}")
    
    k_voisins = 5
    
    # 3. Standardisation des données d'entraînement
    print("Standardisation des données d'entraînement...")
    resultats_std_train = standardiser_donnees(X_train)
    X_train_standardise = resultats_std_train[0]
    params_standardisation = [resultats_std_train[1], resultats_std_train[2]]
    
    # 4. Prédiction pour un nouveau trajet
    # Exemple: Ligne 2 du CSV
    nouveau_trajet = [
        3.855302, 11.547589, 3.864589, 11.496399, # Coords
        8.6, 8.7, # Dist, Dur
        1.49, 21, 0.3, # Sin, Vir, Force
        20.0, # Congestion
        0, 0, 0, 0, 0 # Cats
    ]
    
    print("\n--- Prédiction pour un nouveau trajet (Test) ---")
    
    # Standardisation du nouveau trajet
    resultats_std_nouveau = standardiser_donnees([nouveau_trajet], params_standardisation)
    X_nouveau_standardise = resultats_std_nouveau[0][0]
    
    # Sélection des voisins
    k_plus_proches = selection_trajets_a_utiliser(
        k_voisins,
        X_train_standardise,
        Y_train,
        W,
        X_nouveau_standardise
    )
    
    # Calcul du prix
    resultats = calcul_prix_et_incertitude(k_plus_proches)
    prix_estime, niveau_confiance = resultats[0], resultats[3]
    
    print(f"-> Prix Estimé : {prix_estime:.0f} FCFA")
    print(f"-> Niveau de Confiance : {niveau_confiance:.2f} %")
