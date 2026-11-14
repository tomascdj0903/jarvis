# J.A.R.V.I.S. — assistant vocal Windows

Dis **« Hey Jarvis »** (prononcé « hé djarvis »), attends le bip, puis donne ta commande.
Autres façons de le réveiller : **Ctrl + Alt + J**, ou **clic sur l'orbe** en bas à droite.

L'**orbe de veille** reste visible en bas à droite : elle respire doucement et grossit quand
le micro capte du son. Si elle ne bouge pas quand tu parles, c'est le micro (voir plus bas).
Les erreurs s'affichent dans une bulle à côté de l'orbe.

## Télécharger (le plus simple, sans Python)
1. Va dans **Releases** → télécharge `Jarvis-Windows.zip`.
2. Dézippe où tu veux, lance `Jarvis.exe`.
3. Les mises à jour sont proposées automatiquement au lancement (ou clic droit sur l'icône → « Rechercher une mise à jour »).

## Publier une mise à jour
Change le numéro dans `jarvis/__init__.py` (ex. `1.3.1`) et pousse sur `main`. C'est tout :
GitHub fabrique `Jarvis.exe` et publie la release tout seul (au push, sinon dans les 15 minutes),
puis chaque Jarvis installé la propose au lancement suivant.

## Installation depuis le code
1. Installe **Python 3.11 (Windows x64)** depuis python.org — coche « Add Python to PATH ».
   Sur Snapdragon, la version x64 tourne en émulation et a toutes les bibliothèques nécessaires.
2. Crée une clé gratuite sur **console.groq.com** → API Keys → Create API Key.
3. Double-clique **1_installer.bat**.
4. Double-clique **2_lancer.bat** : Jarvis demande ta clé, ton nom, et s'il doit démarrer avec Windows.
5. Pour le logiciel final : **3_creer_exe.bat** → `dist\Jarvis\Jarvis.exe` (garde tout le dossier `Jarvis`).

## Exemples
- « Lance Spotify » · « Change de musique » · « Pause » · « Monte le son »
- « Mets du Dua Lipa », « Joue Stromae sur Spotify » — YouTube, YouTube Music, Spotify ou Deezer (au choix dans Réglages), sans compte Premium ni clé API
- « Lance Brawlhalla » / « Ouvre Discord » · « Ferme Chrome »
- « Ouvre mes téléchargements » · « Range mes téléchargements » · « Trouve mon fichier Volvo »
- « Cherche la météo à Nice » · « Ouvre youtube.com »
- « Mets un minuteur de 10 minutes » · « Quelle heure est-il ? »
- « Verrouille le PC » · « Éteins le PC » (Jarvis demande confirmation)

## Icône près de l'horloge (clic droit)
Micro en pause · Lancer au démarrage · Réindexer les applications · Réglages · Journal · Quitter

## Réglages — `%APPDATA%\Jarvis\config.json`
- `user_name` : comment il t'appelle
- `voice` : voix (`fr-FR-HenriNeural`, `fr-FR-DeniseNeural`, `fr-FR-RemyMultilingualNeural`…)
- `wake_threshold` : sensibilité de « Hey Jarvis » (0.25 = très sensible, 0.35 par défaut, 0.6 = moins de faux réveils)
- `allowed_folders` : dossiers où Jarvis peut chercher/ouvrir des fichiers
- `llm_model` : modèle Groq

## Sécurité
- L'écoute du mot « Jarvis » est 100 % locale ; seule la phrase après le bip part chez Groq.
- Arrêt, redémarrage et rangement demandent un « oui » vocal. Jarvis ne supprime jamais de fichier.

## Si ça ne marche pas
- Pas de réaction : Paramètres Windows → Confidentialité → Microphone → autoriser les applis de bureau.
- Voix muette : il faut internet (voix Microsoft Edge).
- Regarde le Journal (clic droit sur l'icône).
