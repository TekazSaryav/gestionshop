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

### 2) Configurer le webhook SellAuth
- URL webhook à renseigner côté SellAuth:
  - `https://ton-domaine.com/webhooks/sellauth`
- Secret webhook:
  - Copier le secret dans `.env` -> `SELLAUTH_WEBHOOK_SECRET`
- Le serveur webhook interne écoute `WEBHOOK_HOST:WEBHOOK_PORT`.

### 3) Vérification manuelle
- Staff: `/order verify order_id:<TKZ-...> sellauth_order_id:<id>`
- Cooldown: 5 vérifs / minute / staff.

## Notes sécurité
- Livraison (`/stock deliver` ou bouton Mark Delivered) bloquée si paiement non confirmé.
- Accepté si:
  - commande en `Paid`, ou
  - check SellAuth positif de moins de 10 minutes.
