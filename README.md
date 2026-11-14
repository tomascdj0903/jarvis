# J.A.R.V.I.S. — assistant vocal Windows

Dis **« Hey Jarvis »** (ou « OK Jarvis »), attends le bip, puis donne ta commande.

## Télécharger (le plus simple, sans Python)
1. Va dans **Releases** → télécharge `Jarvis-Windows.zip`.
2. Dézippe où tu veux, lance `Jarvis.exe`.
3. Les mises à jour sont proposées automatiquement au lancement (ou clic droit sur l'icône → « Rechercher une mise à jour »).

## Publier une mise à jour
Change le numéro dans `jarvis/__init__.py` (ex. `1.0.1`) et pousse sur `main` : GitHub fabrique
`Jarvis.exe` et publie la release ; les Jarvis installés la proposent au prochain lancement.

## Installation depuis le code
1. Installe **Python 3.11 (Windows x64)** depuis python.org — coche « Add Python to PATH ».
   Sur Snapdragon, la version x64 tourne en émulation et a toutes les bibliothèques nécessaires.
2. Crée une clé gratuite sur **console.groq.com** → API Keys → Create API Key.
3. Double-clique **1_installer.bat**.
4. Double-clique **2_lancer.bat** : Jarvis demande ta clé, ton nom, et s'il doit démarrer avec Windows.
5. Pour le logiciel final : **3_creer_exe.bat** → `dist\Jarvis\Jarvis.exe` (garde tout le dossier `Jarvis`).

## Exemples
- « Lance Spotify » · « Change de musique » · « Pause » · « Monte le son »
- « Mets du Dua Lipa » (ouvre la recherche Spotify)
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
- `wake_threshold` : sensibilité de « Hey Jarvis » (0.3 = plus sensible, 0.7 = moins de faux réveils)
- `allowed_folders` : dossiers où Jarvis peut chercher/ouvrir des fichiers
- `llm_model` : modèle Groq

## Sécurité
- L'écoute du mot « Jarvis » est 100 % locale ; seule la phrase après le bip part chez Groq.
- Arrêt, redémarrage et rangement demandent un « oui » vocal. Jarvis ne supprime jamais de fichier.

## Si ça ne marche pas
- Pas de réaction : Paramètres Windows → Confidentialité → Microphone → autoriser les applis de bureau.
- Voix muette : il faut internet (voix Microsoft Edge).
- Regarde le Journal (clic droit sur l'icône).
