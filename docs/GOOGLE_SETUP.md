# Connecter Google Agenda (5 minutes, une seule fois)

Google Agenda n'accepte pas les mots de passe d'application. Pour écrire dans votre agenda,
MailBridge a besoin d'un **accès OAuth** que vous créez vous-même dans votre compte Google.
C'est gratuit, et cet accès n'appartient qu'à vous : personne d'autre (pas même l'auteur de
MailBridge) ne peut l'utiliser.

> Pourquoi les outils commerciaux n'ont pas cette étape ? Ils fournissent leur propre accès,
> validé par Google après un audit payant. MailBridge est un outil personnel et libre : chacun
> utilise son propre accès.

## 1. Créer un projet

1. Ouvrez <https://console.cloud.google.com/> avec votre compte Gmail.
2. En haut, menu des projets > **Nouveau projet** > nom : `MailBridge` > **Créer**.
   Vérifiez que le projet `MailBridge` est bien sélectionné en haut de la page.

## 2. Activer l'API Google Calendar

1. Ouvrez <https://console.cloud.google.com/apis/library/calendar-json.googleapis.com>.
2. Cliquez sur **Activer**.

## 3. Déclarer l'application (écran de consentement)

1. Menu **API et services > Écran de consentement OAuth** (ou **Google Auth Platform**).
2. Cliquez sur **Commencer** :
   * Nom de l'application : `MailBridge` ; e-mail d'assistance : votre Gmail ;
   * Audience : **Externe** ;
   * Coordonnées : votre Gmail ; acceptez le règlement > **Créer**.
3. Section **Audience** : cliquez sur **Publier l'application** puis confirmez (état **En production**).

   *Important :* en mode « Test », Google coupe l'accès au bout de 7 jours. En production,
   l'accès dure. Aucune validation par Google n'est nécessaire pour votre usage personnel.

## 4. Créer l'accès et le télécharger

1. Section **Clients** (ou **Identifiants > Créer des identifiants > ID client OAuth**).
2. Type d'application : **Application de bureau** ; nom : `MailBridge` > **Créer**.
3. Cliquez sur **Télécharger le fichier JSON** (`client_secret_….json`).

## 5. L'importer dans MailBridge

1. MailBridge > ligne **Google Agenda** > **Importer le fichier** > choisissez le fichier JSON.
2. **Se connecter à Google** : une page Google s'ouvre dans votre navigateur.
   Google affiche « Google n'a pas validé cette application » : c'est normal, c'est **votre**
   application. Cliquez sur **Paramètres avancés** > **Accéder à MailBridge (non sécurisé)** >
   cochez l'accès à Google Agenda > **Continuer**.
3. Revenez dans MailBridge : **Ajouter un calendrier**, choisissez le compte Outlook et l'agenda
   Google de destination (un nouvel agenda « MailBridge · … » est conseillé).

## Ce que MailBridge fait (et ne fait pas) dans votre agenda

* Il crée, met à jour et supprime **uniquement** les événements qu'il a lui-même copiés
  (ils portent une étiquette invisible). Vos autres événements ne sont jamais touchés.
* Sens unique Outlook → Google, fenêtre de 30 jours passés à 180 jours à venir, toutes les 15 min.
* Les rendez-vous refusés ou annulés ne sont pas copiés ; les rappels Google sont désactivés
  sur les copies pour éviter les doubles notifications.
* Le jeton d'accès est rangé dans le Gestionnaire d'identifiants Windows (`MailBridge/google`).
  Pour tout révoquer : MailBridge > Google Agenda > **Déconnecter**, ou
  <https://myaccount.google.com/permissions>.
