# Shizu Bot - Système de Paiement Premium

Ce guide explique comment configurer le système de paiement Premium complet pour Shizu Bot.

## Architecture

- **Frontend**: Site statique sur GitHub Pages (HTML/CSS/JS)
- **Backend**: API Flask (Python) hébergée sur un serveur (Heroku, Railway, etc.)
- **Bot Discord**: Reçoit les webhooks et gère la DB SQLite
- **Paiement**: Stripe Checkout avec abonnements mensuels

## 1. Configuration Stripe

1. Créez un compte sur [Stripe Dashboard](https://dashboard.stripe.com)
2. Activez les webhooks pour votre endpoint backend
3. Récupérez vos clés API

## 2. Configuration du Backend

### Installation des dépendances
```bash
pip install -r requirements.txt
```

### Variables d'environnement
Créez un fichier `.env` basé sur `.env.example`:

```env
# Clés Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# URL du webhook du bot
BOT_WEBHOOK_URL=http://localhost:8080/webhooks/payment

# Secret pour signer les requêtes vers le bot
BOT_WEBHOOK_SECRET=votre_secret_bot

# URL de votre site frontend
FRONTEND_URL=https://votredomaine.github.io
```

### Lancement du backend
```bash
python backend.py
```

### Déploiement
Déployez sur Heroku, Railway, ou tout service supportant Python/Flask.

## 3. Configuration du Bot Discord

### Variables d'environnement du bot
Ajoutez dans le `.env` du bot:

```env
# Port pour le webhook de paiement
PAYMENT_WEBHOOK_HOST=0.0.0.0
PAYMENT_WEBHOOK_PORT=8080

# Secret pour valider les signatures webhook
PAYMENT_WEBHOOK_SECRET=votre_secret_bot

# Jours par défaut pour le premium
PAYMENT_DEFAULT_DAYS=30

# ID du rôle Premium
PREMIUM_ROLE_ID=123456789012345678

# Nom du rôle Premium
PREMIUM_ROLE_NAME=Premium
```

### Lancement du bot
Le bot démarre automatiquement le serveur webhook sur le port configuré.

## 4. Configuration du Frontend

### Mise à jour de l'URL du backend
Dans `script.js`, remplacez l'URL de fetch par votre URL de backend déployé:

```javascript
const response = await fetch('https://votredomaine.herokuapp.com/create-checkout-session', {
```

### Déploiement sur GitHub Pages
1. Poussez les fichiers sur GitHub
2. Activez GitHub Pages dans les settings du repo
3. Mettez à jour `FRONTEND_URL` dans le `.env` du backend

## 5. Configuration Stripe Webhook

1. Dans le dashboard Stripe, allez dans "Webhooks"
2. Ajoutez un endpoint: `https://votredomaine.herokuapp.com/webhook/stripe`
3. Sélectionnez l'événement: `checkout.session.completed`
4. Copiez le webhook secret dans `STRIPE_WEBHOOK_SECRET`

## 6. Test du système

1. Lancez le bot Discord
2. Lancez le backend Flask
3. Ouvrez le site web
4. Cliquez sur "Devenir Premium"
5. Entrez un Discord ID de test
6. Procédez au paiement avec une carte de test Stripe
7. Vérifiez que le rôle Premium est attribué sur Discord

## Sécurité

- Les webhooks Stripe sont validés avec HMAC
- Les requêtes vers le bot sont signées
- Validation des données avant insertion en DB
- Protection contre les abus (vérification des événements dupliqués)

## Support

Pour toute question, contactez zeyratw sur Discord.