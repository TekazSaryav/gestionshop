# Tekaz Shop Manager

Bot Discord `discord.py 2.x` pour gérer commandes, tickets, preuves, stock et vouches.

## Installation

1. Créer un environnement Python 3.11+.
2. Installer dépendances:
   ```bash
   pip install -r requirements.txt
   ```
3. Copier `.env.example` vers `.env` et renseigner le token:
   ```bash
   cp .env.example .env
   ```
4. Activer intents dans le portail Discord Developer:
   - Server Members Intent
   - Message Content Intent
5. Lancer le bot:
   ```bash
   python main.py
   ```

## Structure

- `main.py`: bootstrap bot + chargement cogs
- `core/`: DB, permissions, logger, helpers, constantes
- `cogs/`: fonctionnalités métier par module
