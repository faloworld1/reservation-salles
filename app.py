import streamlit as st
import pyodbc
import pandas as pd
from datetime import datetime, date, time, timedelta
import hashlib
import os
from typing import Optional, Dict, Any

# Configuration de la page
st.set_page_config(
    page_title="Système de Réservation de Salles",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Configuration de la base de données
@st.cache_resource
def init_connection():
    connection_string = (
        f"Driver={{ODBC Driver 17 for SQL Server}};"
        f"Server={st.secrets['database']['server']};"
        f"Database={st.secrets['database']['database']};"
        f"UID={st.secrets['database']['username']};"
        f"PWD={st.secrets['database']['password']};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=yes;"
        f"Connection Timeout=30;"
    )
    return pyodbc.connect(connection_string)

def execute_query(query: str, params: tuple = None) -> pd.DataFrame:
    conn = init_connection()  # Le nom ici doit matcher celui de la fonction au-dessus
    if conn is None:
        return pd.DataFrame()
    try:
        if params:
            df = pd.read_sql(query, conn, params=params)
        else:
            df = pd.read_sql(query, conn)
        return df
    except Exception as e:
        st.error(f"Erreur lors de l'exécution de la requête: {e}")
        return pd.DataFrame()
    # PAS de conn.close() ici !



def execute_procedure(proc_name: str, params: Dict[str, Any]) -> bool:
    conn = init_connection()
    if conn is None:
        return False

    try:
        cursor = conn.cursor()
        param_values = list(params.values())
        # Attention : le nombre de '?' doit correspondre au nombre de paramètres !
        call = f"EXEC {proc_name} " + ', '.join(['?' for _ in param_values])
        cursor.execute(call, param_values)
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Erreur lors de l'exécution de la procédure: {e}")
        return False

def hash_password(password: str) -> str:
    """Hash un mot de passe"""
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(email: str, password: str) -> Optional[Dict]:
    """Authentifie un utilisateur (sans hash, mot de passe en clair)"""
    query = """
    SELECT UserID, Nom, Prenom, Email, Role, Actif
    FROM Utilisateurs 
    WHERE Email = ? AND MotDePasse = ? AND Actif = 1
    """
    result = execute_query(query, (email, password))  # mot de passe en clair
    
    if not result.empty:
        return result.iloc[0].to_dict()
    return None


def get_salles() -> pd.DataFrame:
    """Récupère la liste des salles disponibles"""
    query = """
    SELECT SalleID, NomSalle, Capacite, Equipements, Localisation
    FROM Salles 
    WHERE Disponible = 1
    ORDER BY NomSalle
    """
    return execute_query(query)

def get_types_evenements() -> pd.DataFrame:
    """Récupère les types d'événements"""
    query = """
    SELECT TypeID, NomType, Description, DureeMin, DureeMax
    FROM TypesEvenements
    ORDER BY NomType
    """
    return execute_query(query)

def get_reservations_user(user_id: int) -> pd.DataFrame:
    """Récupère les réservations d'un utilisateur"""
    query = """
    SELECT r.ReservationID, s.NomSalle, r.ObjetReunion, r.DateReservation,
           r.HeureDebut, r.HeureFin, r.Statut, te.NomType
    FROM Reservations r
    INNER JOIN Salles s ON r.SalleID = s.SalleID
    INNER JOIN TypesEvenements te ON r.TypeID = te.TypeID
    WHERE r.UserID = ?
    ORDER BY r.DateReservation DESC, r.HeureDebut DESC
    """
    return execute_query(query, (user_id,))

def get_reservations_pending():
    """Récupère les réservations en attente pour les managers"""
    query = """
    SELECT r.ReservationID, u.Nom + ' ' + u.Prenom AS Demandeur,
           s.NomSalle, r.ObjetReunion, r.DateReservation,
           r.HeureDebut, r.HeureFin, te.NomType, r.DateCreation
    FROM Reservations r
    INNER JOIN Utilisateurs u ON r.UserID = u.UserID
    INNER JOIN Salles s ON r.SalleID = s.SalleID
    INNER JOIN TypesEvenements te ON r.TypeID = te.TypeID
    WHERE r.Statut = 'EnAttente'
    ORDER BY r.DateCreation ASC
    """
    return execute_query(query)

def check_availability(salle_id: int, date_res: date, heure_debut: time, heure_fin: time) -> bool:
    """Vérifie la disponibilité d'une salle"""
    query = """
    SELECT dbo.fn_SalleDisponible(?, ?, ?, ?) as Disponible
    """
    result = execute_query(query, (salle_id, date_res, heure_debut, heure_fin))
    return bool(result.iloc[0]['Disponible']) if not result.empty else False

# Interface utilisateur
def login_page():
    """Page de connexion"""
    st.title("🏢 Système de Réservation de Salles")
    st.markdown("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.subheader("Connexion")
        
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="votre.email@entreprise.com")
            password = st.text_input("Mot de passe", type="password")
            submit = st.form_submit_button("Se connecter", use_container_width=True)
            
            if submit:
                if email and password:
                    user = authenticate_user(email, password)
                    if user:
                        st.session_state.user = user
                        st.success("Connexion réussie!")
                        st.rerun()
                    else:
                        st.error("Email ou mot de passe incorrect")
                else:
                    st.error("Veuillez remplir tous les champs")

def reservation_page():
    """Page de réservation"""
    st.title("📅 Nouvelle Réservation")
    
    # Récupération des données
    salles = get_salles()
    types_evenements = get_types_evenements()
    
    if salles.empty or types_evenements.empty:
        st.error("Impossible de charger les données")
        return
    
    with st.form("reservation_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            salle_selected = st.selectbox(
                "Salle",
                options=salles['SalleID'].tolist(),
                format_func=lambda x: f"{salles[salles['SalleID']==x]['NomSalle'].iloc[0]} (Capacité: {salles[salles['SalleID']==x]['Capacite'].iloc[0]})"
            )
            
            type_selected = st.selectbox(
                "Type d'événement",
                options=types_evenements['TypeID'].tolist(),
                format_func=lambda x: types_evenements[types_evenements['TypeID']==x]['NomType'].iloc[0]
            )
            
            date_reservation = st.date_input(
                "Date de réservation",
                min_value=date.today(),
                value=date.today()
            )
        
        with col2:
            heure_debut = st.time_input("Heure de début", value=time(9, 0))
            heure_fin = st.time_input("Heure de fin", value=time(10, 0))
            
            objet_reunion = st.text_area("Objet de la réunion", height=100)
        
        # Affichage des informations de la salle sélectionnée
        if salle_selected:
            salle_info = salles[salles['SalleID'] == salle_selected].iloc[0]
            st.info(f"**Équipements:** {salle_info['Equipements']} | **Localisation:** {salle_info['Localisation']}")
        
        submit = st.form_submit_button("Réserver", use_container_width=True)
        
        if submit:
            # Validation des données
            if not objet_reunion.strip():
                st.error("L'objet de la réunion est obligatoire")
                return
            
            if heure_fin <= heure_debut:
                st.error("L'heure de fin doit être supérieure à l'heure de début")
                return
            
            # Vérification de la disponibilité
            if not check_availability(salle_selected, date_reservation, heure_debut, heure_fin):
                st.error("La salle n'est pas disponible pour ce créneau")
                return
            
            # Tentative de réservation
            params = {
    'UserID': st.session_state.user['UserID'],
    'SalleID': salle_selected,
    'TypeID': type_selected,
    'ObjetReunion': objet_reunion.strip(),
    'DateReservation': date_reservation,
    'HeureDebut': heure_debut,
    'HeureFin': heure_fin,
    'ReservationID': 0  # Ajout obligatoire !
}
            
            if execute_procedure('sp_ReserverSalle', params):
                st.success("Réservation créée avec succès! En attente de validation.")
                st.rerun()

def mes_reservations_page():
    """Page des réservations de l'utilisateur"""
    st.title("📋 Mes Réservations")
    
    reservations = get_reservations_user(st.session_state.user['UserID'])
    
    if reservations.empty:
        st.info("Vous n'avez aucune réservation")
        return
    
    # Filtres
    col1, col2 = st.columns(2)
    with col1:
        statut_filter = st.selectbox(
            "Filtrer par statut",
            options=['Tous'] + reservations['Statut'].unique().tolist()
        )
    
    # Application du filtre
    if statut_filter != 'Tous':
        reservations_filtered = reservations[reservations['Statut'] == statut_filter]
    else:
        reservations_filtered = reservations
    
    # Affichage des réservations
    for _, reservation in reservations_filtered.iterrows():
        with st.container():
            col1, col2, col3 = st.columns([3, 2, 1])
            
            with col1:
                st.write(f"**{reservation['ObjetReunion']}**")
                st.write(f"🏠 {reservation['NomSalle']} | 📅 {reservation['DateReservation']}")
                st.write(f"🕐 {reservation['HeureDebut']} - {reservation['HeureFin']} | 📝 {reservation['NomType']}")
            
            with col2:
                if reservation['Statut'] == 'EnAttente':
                    st.warning("⏳ En attente")
                elif reservation['Statut'] == 'Validee':
                    st.success("✅ Validée")
                elif reservation['Statut'] == 'Refusee':
                    st.error("❌ Refusée")
                else:
                    st.info("🚫 Annulée")
            
            with col3:
                if reservation['Statut'] in ['EnAttente', 'Validee']:
                    if st.button("Annuler", key=f"cancel_{reservation['ReservationID']}"):
                        params = {
                            'UserID': st.session_state.user['UserID'],
                            'ReservationID': reservation['ReservationID']
                        }
                        if execute_procedure('sp_AnnulerReservation', params):
                            st.success("Réservation annulée")
                            st.rerun()
            
            st.markdown("---")

def validation_page():
    """Page de validation pour les managers"""
    if st.session_state.user['Role'] not in ['Manager', 'Admin']:
        st.error("Accès non autorisé")
        return
    
    st.title("✅ Validation des Réservations")
    
    reservations = get_reservations_pending()
    
    if reservations.empty:
        st.info("Aucune réservation en attente de validation")
        return
    
    st.write(f"**{len(reservations)} réservation(s) en attente**")
    
    for _, reservation in reservations.iterrows():
        with st.expander(f"{reservation['Demandeur']} - {reservation['ObjetReunion']}"):
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.write(f"**Demandeur:** {reservation['Demandeur']}")
                st.write(f"**Salle:** {reservation['NomSalle']}")
                st.write(f"**Date:** {reservation['DateReservation']}")
                st.write(f"**Horaire:** {reservation['HeureDebut']} - {reservation['HeureFin']}")
                st.write(f"**Type:** {reservation['NomType']}")
                st.write(f"**Objet:** {reservation['ObjetReunion']}")
                
                commentaires = st.text_area(
                    "Commentaires (optionnel)",
                    key=f"comment_{reservation['ReservationID']}"
                )
            
            with col2:
                col_val, col_ref = st.columns(2)
                
                with col_val:
                    if st.button("✅ Valider", key=f"validate_{reservation['ReservationID']}", use_container_width=True):
                        params = {
                            'ManagerID': st.session_state.user['UserID'],
                            'ReservationID': reservation['ReservationID'],
                            'Commentaires': commentaires if commentaires else None
                        }
                        if execute_procedure('sp_ValiderReservation', params):
                            st.success("Réservation validée")
                            st.rerun()
                
                with col_ref:
                    if st.button("❌ Refuser", key=f"refuse_{reservation['ReservationID']}", use_container_width=True):
                        # Pour refuser, on peut utiliser la procédure d'annulation
                        params = {
                            'UserID': st.session_state.user['UserID'],
                            'ReservationID': reservation['ReservationID'],
                            'Commentaires': f"Refusée par manager: {commentaires}" if commentaires else "Refusée par manager"
                        }
                        if execute_procedure('sp_AnnulerReservation', params):
                            st.success("Réservation refusée")
                            st.rerun()

def tableau_bord_page():
    """Tableau de bord avec statistiques"""
    st.title("📊 Tableau de Bord")
    
    # Statistiques générales
    today = date.today()
    
    # Requêtes pour les métriques
    reservations_today = execute_query("""
        SELECT COUNT(*) as count FROM Reservations 
        WHERE DateReservation = ? AND Statut = 'Validee'
    """, (today,))
    
    reservations_week = execute_query("""
        SELECT COUNT(*) as count FROM Reservations 
        WHERE DateReservation BETWEEN ? AND ? AND Statut = 'Validee'
    """, (today, today + timedelta(days=7)))
    
    salles_occupees = execute_query("""
        SELECT COUNT(DISTINCT SalleID) as count FROM Reservations 
        WHERE DateReservation = ? AND Statut = 'Validee'
        AND CAST(GETDATE() AS time) BETWEEN HeureDebut AND HeureFin
    """, (today,))
    
    # Affichage des métriques
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Réservations aujourd'hui", 
                 reservations_today.iloc[0]['count'] if not reservations_today.empty else 0)
    
    with col2:
        st.metric("Réservations cette semaine", 
                 reservations_week.iloc[0]['count'] if not reservations_week.empty else 0)
    
    with col3:
        st.metric("Salles occupées maintenant", 
                 salles_occupees.iloc[0]['count'] if not salles_occupees.empty else 0)
    
    with col4:
        total_salles = len(get_salles())
        st.metric("Total salles disponibles", total_salles)
    
    # Graphiques
    st.markdown("---")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Réservations par statut")
        reservations_stats = execute_query("""
            SELECT Statut, COUNT(*) as Nombre
            FROM Reservations
            WHERE DateReservation >= DATEADD(day, -30, GETDATE())
            GROUP BY Statut
        """)
        
        if not reservations_stats.empty:
            st.bar_chart(reservations_stats.set_index('Statut'))
    
    with col2:
        st.subheader("Salles les plus utilisées")
        salles_stats = execute_query("""
            SELECT TOP 5 s.NomSalle, COUNT(*) as Reservations
            FROM Reservations r
            INNER JOIN Salles s ON r.SalleID = s.SalleID
            WHERE r.Statut = 'Validee' AND r.DateReservation >= DATEADD(day, -30, GETDATE())
            GROUP BY s.SalleID, s.NomSalle
            ORDER BY COUNT(*) DESC
        """)
        
        if not salles_stats.empty:
            st.bar_chart(salles_stats.set_index('NomSalle'))

def main():
    """Fonction principale"""
    
    # Vérification de la connexion
    if 'user' not in st.session_state:
        login_page()
        return
    
    # Sidebar avec menu
    with st.sidebar:
        st.write(f"**Connecté:** {st.session_state.user['Prenom']} {st.session_state.user['Nom']}")
        st.write(f"**Rôle:** {st.session_state.user['Role']}")
        st.markdown("---")
        
        menu_options = ["📊 Tableau de bord", "📅 Nouvelle réservation", "📋 Mes réservations"]
        if st.session_state.user['Role'] in ['Manager', 'Admin']:
            menu_options.append("✅ Validation")
        
        choice = st.radio("Navigation", menu_options)
        
        st.markdown("---")
        if st.button("🚪 Déconnexion"):
            del st.session_state.user
            st.rerun()
    
    # Navigation
    if "Tableau de bord" in choice:
        tableau_bord_page()
    elif "Nouvelle réservation" in choice:
        reservation_page()
    elif "Mes réservations" in choice:
        mes_reservations_page()
    elif "Validation" in choice:
        validation_page()

if __name__ == "__main__":
    main()