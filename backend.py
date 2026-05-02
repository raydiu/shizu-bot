from flask import Flask, request, jsonify
import stripe
import os
import requests
import hmac
import hashlib
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://raydiu.github.io/shizu-bot')

# Configuration CORS pour le développement et GitHub Pages
ALLOWED_ORIGINS = {
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    FRONTEND_URL
}

@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin in ALLOWED_ORIGINS:
        response.headers.add('Access-Control-Allow-Origin', origin)
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Configuration Stripe (optionnel pour développement)
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', 'dev_webhook_secret')
BOT_WEBHOOK_URL = os.getenv('BOT_WEBHOOK_URL', 'http://localhost:8080/webhooks/payment')
BOT_WEBHOOK_SECRET = os.getenv('BOT_WEBHOOK_SECRET', 'dev_bot_secret')
# Prix mensuel (en cents)
PREMIUM_PRICE = 500  # 5€

# Mode développement
DEV_MODE = not STRIPE_SECRET_KEY

if not DEV_MODE:
    stripe.api_key = STRIPE_SECRET_KEY

@app.route('/')
def home():
    return jsonify({
        'status': 'Backend Shizu Bot Premium - Mode Développement',
        'endpoints': {
            'POST /create-checkout-session': 'Créer une session de paiement Stripe',
            'POST /webhook/stripe': 'Webhook Stripe (production)',
            'POST /dev/activate-premium': 'Activer premium sans paiement (dev)',
            'GET /test': 'Page de test pour vérifier le backend'
        },
        'dev_mode': DEV_MODE
    })

@app.route('/test')
def test_page():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Backend Shizu Bot</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #0a1030; color: #eff8ff; }
            .container { max-width: 800px; margin: 0 auto; }
            h1 { color: #65efff; }
            .endpoint { background: rgba(10, 16, 48, 0.9); padding: 20px; margin: 10px 0; border-radius: 8px; border: 1px solid rgba(101, 239, 255, 0.3); }
            .method { color: #7fffd0; font-weight: bold; }
            pre { background: #000; padding: 10px; border-radius: 4px; overflow-x: auto; }
            button { background: #65efff; color: #03111c; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin: 5px; }
            button:hover { background: #4fc3d6; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🧪 Test Backend Shizu Bot Premium</h1>
            <p>Backend opérationnel en mode développement</p>
            
            <div class="endpoint">
                <h3><span class="method">POST</span> /dev/activate-premium</h3>
                <p>Activer le premium sans paiement (pour tests)</p>
                <button onclick="testActivatePremium()">Tester l'activation Premium</button>
                <pre id="result"></pre>
            </div>
            
            <div class="endpoint">
                <h3><span class="method">GET</span> /</h3>
                <p>Status du backend</p>
                <a href="/">Voir le status JSON</a>
            </div>
        </div>
        
        <script>
        async function testActivatePremium() {
            const result = document.getElementById('result');
            const discordId = '912076290075525140'; // ID de test fixe
            
            try {
                const response = await fetch('/dev/activate-premium', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ discord_id: discordId })
                });
                
                const data = await response.json();
                result.textContent = JSON.stringify(data, null, 2);
            } catch (error) {
                result.textContent = 'Erreur: ' + error.message;
            }
        }
        </script>
    </body>
    </html>
    '''

# Prix mensuel (en cents)
PREMIUM_PRICE = 500  # 5€

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        guild_id = data.get('guild_id', '123456789012345678')

        if not discord_id:
            return jsonify({'error': 'Discord ID requis'}), 400

        if DEV_MODE:
            # Mode développement - simuler une session Stripe
            frontend_origin = request.headers.get('Origin') or request.headers.get('Referer')
            if frontend_origin:
                frontend_origin = frontend_origin.split('?')[0].split('#')[0].rstrip('/')
            else:
                frontend_origin = FRONTEND_URL
            fake_session_url = f"{frontend_origin}/success.html?session_id=dev_{discord_id}"
            return jsonify({'url': fake_session_url})

        # Créer une session Stripe Checkout
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {
                        'name': 'Shizu Bot Premium',
                        'description': 'Accès Premium mensuel au bot Discord',
                    },
                    'unit_amount': PREMIUM_PRICE,
                },
                'quantity': 1,
            }],
            mode='subscription',  # Abonnement mensuel
            success_url=f"{FRONTEND_URL}/success.html?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/",
            metadata={
                'discord_user_id': discord_id,
                'guild_id': guild_id,
                'provider': 'stripe'
            }
        )

        return jsonify({'url': session.url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    if DEV_MODE:
        # Mode développement - accepter tous les webhooks
        return '', 200

    payload = request.get_data()
    sig_header = request.headers.get('stripe-signature')

    try:
        # Vérifier la signature Stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400

    # Traiter l'événement
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']

        # Extraire les métadonnées
        discord_user_id = session.get('metadata', {}).get('discord_user_id')
        guild_id = session.get('metadata', {}).get('guild_id')

        if discord_user_id and guild_id:
            # Calculer la date d'expiration (1 mois)
            expire_at = datetime.utcnow() + timedelta(days=30)

            # Préparer les données pour le bot
            bot_payload = {
                'provider': 'stripe',
                'event_id': session['id'],
                'user_id': int(discord_user_id),
                'guild_id': int(guild_id),
                'status': 'completed',
                'expire_at': expire_at.isoformat(),
                'days': 30
            }

            # Envoyer au webhook du bot
            headers = {}
            if BOT_WEBHOOK_SECRET:
                # Calculer la signature sur le JSON sérialisé (comme attendu par le bot)
                payload_json = json.dumps(bot_payload, separators=(',', ':'))
                signature = hmac.new(
                    BOT_WEBHOOK_SECRET.encode('utf-8'),
                    payload_json.encode('utf-8'),
                    hashlib.sha256
                ).hexdigest()
                headers['X-Shizu-Signature'] = f"sha256={signature}"
                headers['Content-Type'] = 'application/json'

            try:
                response = requests.post(BOT_WEBHOOK_URL, data=payload_json, headers=headers, timeout=10)
                if response.status_code == 200:
                    print(f"Premium activé pour user {discord_user_id}")
                else:
                    print(f"Erreur bot webhook: {response.status_code}")
            except Exception as e:
                print(f"Erreur envoi bot: {e}")

    return '', 200

@app.route('/dev/activate-premium', methods=['POST'])
def dev_activate_premium():
    """Endpoint de développement pour activer le premium sans Stripe"""
    if not DEV_MODE:
        return jsonify({'error': 'Mode développement uniquement'}), 403

    try:
        data = request.get_json()
        discord_id = data.get('discord_id')
        guild_id = data.get('guild_id', '123456789012345678')

        if not discord_id:
            return jsonify({'error': 'Discord ID requis'}), 400

        # Calculer la date d'expiration (1 mois)
        expire_at = datetime.utcnow() + timedelta(days=30)

        # Préparer les données pour le bot
        bot_payload = {
            'provider': 'dev',
            'event_id': f"dev_{discord_id}_{int(datetime.utcnow().timestamp())}",
            'user_id': int(discord_id),
            'guild_id': int(guild_id),
            'status': 'completed',
            'expire_at': expire_at.isoformat(),
            'days': 30
        }

        # Envoyer au webhook du bot
        headers = {}
        if BOT_WEBHOOK_SECRET:
            # Calculer la signature sur le JSON sérialisé (comme attendu par le bot)
            payload_json = json.dumps(bot_payload, separators=(',', ':'))
            signature = hmac.new(
                BOT_WEBHOOK_SECRET.encode('utf-8'),
                payload_json.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            headers['X-Shizu-Signature'] = f"sha256={signature}"
            headers['Content-Type'] = 'application/json'

        try:
            response = requests.post(BOT_WEBHOOK_URL, data=payload_json, headers=headers, timeout=10)
            if response.status_code == 200:
                return jsonify({'success': True, 'message': f'Premium activé pour user {discord_id}'})
            else:
                return jsonify({'error': f'Erreur bot webhook: {response.status_code} - {response.text}'}), 500
        except Exception as e:
            # En mode développement, on simule le succès même si le bot n'est pas disponible
            if DEV_MODE:
                print(f"Erreur webhook: {str(e)}")  # Log pour debug
                return jsonify({
                    'success': True,
                    'message': f'Premium activé pour user {discord_id} (mode dev - bot non connecté)',
                    'note': f'Erreur réelle: {str(e)}',
                    'expire_at': expire_at.isoformat()
                })
            else:
                return jsonify({'error': f'Erreur envoi bot: {str(e)}'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 Démarrage du backend Shizu Bot Premium")
    if DEV_MODE:
        print("⚠️  MODE DÉVELOPPEMENT - Pas de Stripe configuré")
        print("💡 Utilisez /dev/activate-premium pour tester sans paiement")
    else:
        print("💳 Mode production avec Stripe")
    port = int(os.getenv('PORT', '5001'))
    app.run(debug=True, host='0.0.0.0', port=port)