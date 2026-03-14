# Tekaz Shop Manager

Bot Discord `discord.py 2.x` pour gérer commandes, tickets, preuves, stock, vouches et vérification de paiements SellAuth.

## Installation

1. Python 3.11+.
2. Installer dépendances:
   ```bash
   pip install -r requirements.txt
   ```
3. Copier et remplir la config:
   ```bash
   cp .env.example .env
   ```
4. Activer intents Discord:
   - Server Members Intent
   - Message Content Intent
5. Lancer:
   ```bash
   python main.py
   ```

## SellAuth - configuration

### 1) Trouver l'API key de ton shop SellAuth
1. Connecte-toi à ton dashboard SellAuth.
2. Ouvre **Settings** (ou **Developer / API** selon l'UI).
3. Va dans la section **API Keys**.
4. Crée une clé (ou copie la clé existante) avec scope lecture commandes.
5. Mets-la dans `.env` (`SELLAUTH_API_KEY`) ou via `/config set key:sellauth_api_key value:...`.

> Ne partage jamais cette clé en public. `/config show` masque la valeur.

### 2) Webhook (optionnel)
- Le bot supporte un endpoint webhook **optionnel** (`/webhooks/sellauth` ou `/webhooks/payment`) pour recevoir des paiements depuis un relay/provider externe.
- Si tu n'as pas de webhook côté SellAuth, ce n'est **pas bloquant**: utilise simplement la vérification manuelle (`/order verify`).
- Variables utiles:
  - `ENABLE_WEBHOOK_SERVER=false` (par défaut)
  - `WEBHOOK_HOST`, `WEBHOOK_PORT`
  - `SELLAUTH_WEBHOOK_SECRET` (si ton provider signe les payloads)

### 3) Vérification manuelle
- Staff: `/order verify order_id:<TKZ-...> sellauth_order_id:<id>`
- Cooldown: 5 vérifs / minute / staff.
- Aucun webhook n'est requis pour cette méthode.

## Notes sécurité
- Livraison (`/stock deliver` ou bouton Mark Delivered) bloquée si paiement non confirmé.
- Accepté si:
  - commande en `Paid`, ou
  - check SellAuth positif de moins de 10 minutes.


## Menus déroulants produits

- Nouveau module `/catalog` avec 6 menus: Accounts, Cheat, Boosts, VPN, Tools, Formations.
- Commande staff: `/catalog setup` publie automatiquement chaque menu dans les salons `#accounts`, `#cheat`, `#boosts`, `#vpn`, `#tools`, `#formation`.
- Les choix utilisateurs sont persistés en base (`menu_state`, `menu_selections`) et restent disponibles après redémarrage.
- Commande utilisateur: `/catalog my` pour revoir les derniers choix sauvegardés.

## Redémarrage automatique

- Variable `.env`: `AUTO_RESTART_INTERVAL`
- Formats acceptés: secondes (`3600`) ou suffixes (`30m`, `6h`).
- À la fin de l'intervalle, le bot se ferme puis redémarre automatiquement (boucle `main`) sans perdre les données (SQLite).
