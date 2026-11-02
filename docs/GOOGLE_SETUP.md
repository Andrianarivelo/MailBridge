# Connecter Google Agenda (5 minutes, une seule fois)

Google Agenda n'accepte pas les mots de passe d'application. Pour écrire dans votre agenda,
GmailBridge a besoin d'un **accès OAuth** que vous créez vous-même dans votre compte Google.
C'est gratuit, et cet accès n'appartient qu'à vous : personne d'autre (pas même l'auteur de
GmailBridge) ne peut l'utiliser.

> Pourquoi les outils commerciaux n'ont pas cette étape ? Ils fournissent leur propre accès,
> validé par Google après un audit payant. GmailBridge est un outil personnel et libre : chacun
> utilise son propre accès.

## Le plus simple : l'assistant de GmailBridge

GmailBridge > ligne **Google Agenda**. Le panneau indique toujours où vous en êtes
(**Non connecté**, **Presque prêt**, **Connecté et vérifié**) et chaque ligne ouvre
directement la bonne page Google. Restez connecté avec votre Gmail dans le navigateur.

| # | Page ouverte | Ce qu'il faut y faire |
|---|---|---|
| 1 | [Activer l'API Google Agenda](https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com) | Créez le projet `GmailBridge` si Google le propose, puis **Activer**. |
| 2 | [Déclarer l'application](https://console.developers.google.com/auth/branding) | **Commencer** · nom `GmailBridge` · votre Gmail · audience **Externe** · coordonnées · **Créer**. |
| 3 | [Publier l'application](https://console.developers.google.com/auth/audience) | **Publier l'application** > Confirmer (état **En production**). |
| 4 | [Créer et télécharger l'accès](https://console.developers.google.com/auth/clients) | **Créer un client** · type **Application de bureau** · **Créer** · **Télécharger le JSON**. |

*Étape 3 importante :* en mode « Test », Google coupe l'accès au bout de 7 jours (ou bloque la
connexion avec « Accès bloqué »). En production, l'accès dure. Aucune validation par Google
n'est nécessaire pour votre usage personnel.

Ensuite, **rien à importer à la main** : tant que le panneau est ouvert, GmailBridge surveille le
dossier Téléchargements et importe tout seul le fichier `client_secret_….json` dès qu'il
arrive (le fichier d'origine n'est pas modifié). Boutons de secours : **Choisir le fichier…**,
ou coller l'identifiant et le secret.

La connexion s'ouvre alors automatiquement dans le navigateur. Google affiche
« Google n'a pas validé cette application » : c'est normal, c'est **votre** application.
Cliquez sur **Paramètres avancés** > **Accéder à GmailBridge (non sécurisé)** (ou le nom donné à l'étape 2, par exemple MailBridge si l'accès a été créé avant le changement de nom) > cochez l'accès à
Google Agenda > **Continuer**.

GmailBridge **vérifie ensuite réellement l'accès** (lecture de la liste de vos agendas) et
affiche **Connecté et vérifié · N agendas modifiables**, puis lance la première synchro.
En cas de problème, le message dit lequel et un bouton ouvre la page Google qui le corrige :

| Message | Cause | Correction |
|---|---|---|
| L'API Google Agenda n'est pas activée | étape 1 oubliée ou autre projet sélectionné | page 1 |
| Connexion refusée / Accès bloqué | application encore en mode Test | page 3 |
| Accès « Application Web » | mauvais type de client | page 4, type **Application de bureau** |
| Google ne reconnaît plus cet accès | client supprimé ou secret changé | page 4, retéléchargez le JSON |
| Autorisation expirée chaque semaine | application restée en mode Test | page 3, puis reconnectez |

Enfin : **Ajouter un calendrier**, choisissez le compte Outlook et l'agenda Google de
destination (un nouvel agenda « GmailBridge · … » est conseillé).

## Ce que GmailBridge fait (et ne fait pas) dans votre agenda

* Il crée, met à jour et supprime **uniquement** les événements qu'il a lui-même copiés
  (ils portent une étiquette invisible). Vos autres événements ne sont jamais touchés.
* Sens unique Outlook → Google, fenêtre de 30 jours passés à 180 jours à venir, toutes les 15 min.
* Les rendez-vous refusés ou annulés ne sont pas copiés ; les rappels Google sont désactivés
  sur les copies pour éviter les doubles notifications.
* Le jeton d'accès est rangé dans le Gestionnaire d'identifiants Windows (`MailBridge/google`).
  Pour tout révoquer : GmailBridge > Google Agenda > **Déconnecter**, ou
  <https://myaccount.google.com/permissions>.
