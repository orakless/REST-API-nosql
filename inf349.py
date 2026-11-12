from flask import Flask, jsonify, request, redirect, url_for, render_template
from models import *
import redis_store
import requests
import datetime
import logging
import os
import uuid


logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

PRODUCTS_FILE = os.environ.get(
    'PRODUCTS_FILE',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'products.json')
)
# URL d'un service de paiement externe ; si absente, le paiement est simulé localement.
PAYMENT_URL = os.environ.get('PAYMENT_URL')

# Exécuté à l'import : fonctionne avec `flask run`, gunicorn et `python inf349.py`.
init_db(PRODUCTS_FILE)


@app.before_request
def _db_connect():
    db.connect(reuse_if_open=True)


@app.teardown_request
def _db_close(exc):
    if not db.is_closed():
        db.close()


# ---------------------------------------------------------------- helpers

def error(field, code, name, status):
    return jsonify({'errors': {field: {'code': code, 'name': name}}}), status


MISSING_PRODUCT = ('products', 'missing-fields', 'La création d\'une commande nécessite un produit', 422)
OUT_OF_INVENTORY = ('products', 'out-of-inventory', 'Le produit demandé n\'est pas en inventaire', 422)
ORDER_NOT_FOUND = ('order', 'not-found', 'La commande demandée n\'existe pas', 404)
ORDER_MISSING_FIELDS = ('order', 'missing-fields', 'Il manque un ou plusieurs champs qui sont obligatoires', 422)
CLIENT_INFO_REQUIRED = ('order', 'missing-fields', 'Les informations du client sont necessaires avant d\'appliquer une carte de credit', 422)


class OrderError(Exception):
    def __init__(self, err):
        self.err = err


def shipping_price_for(total_weight):
    """Poids en grammes."""
    if total_weight < 500:
        return 5
    if total_weight < 2000:
        return 10
    return 25


def create_order(items):
    """items : liste de (product_id, quantity). Valide, persiste dans Postgres puis Redis."""
    if not items:
        raise OrderError(MISSING_PRODUCT)

    resolved = []
    for product_id, quantity in items:
        if not isinstance(quantity, int) or quantity < 1:
            raise OrderError(MISSING_PRODUCT)
        product = Product.get_or_none(id=product_id)
        if product is None or not product.in_stock:
            raise OrderError(OUT_OF_INVENTORY)
        resolved.append((product, quantity))

    total_price = sum(p.price * q for p, q in resolved)
    total_weight = sum(p.weight * q for p, q in resolved)

    with db.atomic():
        order_items = [OrderItem.create(product=p, quantity=q) for p, q in resolved]
        order = Order.create(total_price=round(total_price, 2),
                             shipping_price=shipping_price_for(total_weight),
                             paid=False)
        order.order_items.add(order_items)

    redis_store.record_order_created(order.to_dict())
    return order


def parse_json_items(data):
    if 'products' in data:
        products = data['products']
    elif 'product' in data:
        products = [data['product']]
    else:
        raise OrderError(MISSING_PRODUCT)

    if not isinstance(products, list):
        raise OrderError(MISSING_PRODUCT)
    items = []
    for p in products:
        if not isinstance(p, dict) or 'id' not in p or 'quantity' not in p:
            raise OrderError(MISSING_PRODUCT)
        items.append((p['id'], p['quantity']))
    return items


def parse_form_items(form):
    """Formulaire HTML : productId/quantity, productId2/quantity2, ... (lignes vides ignorées)."""
    items = []
    for suffix in [''] + [str(i) for i in range(2, 11)]:
        product_id = (form.get('productId' + suffix) or '').strip()
        quantity = (form.get('quantity' + suffix) or '').strip()
        if not product_id and not quantity:
            continue
        try:
            items.append((int(product_id), int(quantity)))
        except ValueError:
            raise OrderError(MISSING_PRODUCT)
    return items


def with_product_details(order_data):
    for item in order_data['products']:
        product = Product.get_or_none(id=item['product'])
        if product:
            item['name'] = product.name
            item['price'] = product.price
    return order_data


def charge_card(card, amount):
    """Retourne (transaction_dict, None) ou (None, erreur_json)."""
    if PAYMENT_URL:
        resp = requests.post(PAYMENT_URL, json={'credit_card': card, 'amount_charged': amount}, timeout=10).json()
        if 'errors' in resp:
            return None, resp
        return resp['transaction'], None

    # Paiement simulé (même règles que l'ancien service UQAC)
    number = str(card['number']).replace(' ', '')
    today = datetime.date.today()
    try:
        expired = (int(card['expiration_year']), int(card['expiration_month'])) < (today.year, today.month)
    except (TypeError, ValueError):
        expired = True
    if expired:
        return None, {'errors': {'credit_card': {'code': 'card-expired', 'name': 'La carte de crédit est expirée'}}}
    if number != '4242424242424242':
        return None, {'errors': {'credit_card': {'code': 'card-declined', 'name': 'La carte de crédit a été déclinée'}}}
    return {'id': uuid.uuid4().hex, 'success': True, 'amount_charged': amount}, None


# ---------------------------------------------------------------- API JSON

@app.route('/', methods=['GET'])
def get_products():
    products = redis_store.get_cached_products()
    if products is None:
        products = list(Product.select().dicts())
        redis_store.cache_products(products)
    return jsonify({"products": products})


@app.route('/products/top', methods=['GET'])
def get_top_products():
    top = with_product_details({'products': redis_store.get_top_products()})
    return jsonify(top)


@app.route('/orders/recent', methods=['GET'])
def get_recent_orders():
    return jsonify({"orders": redis_store.get_recent_orders(), "stats": redis_store.get_stats()})


@app.route('/customers/<path:email>/orders', methods=['GET'])
def get_customer_orders(email):
    return jsonify({"email": email, "orders": redis_store.get_customer_orders(email)})


@app.route('/order', methods=['POST'])
def post_order():
    is_form = not request.is_json
    try:
        items = parse_form_items(request.form) if is_form else parse_json_items(request.get_json(silent=True) or {})
        order = create_order(items)
    except OrderError as e:
        return error(*e.err)

    if is_form:
        return render_template('orderInfo.html', order=with_product_details(order.to_dict()))
    return redirect(url_for('get_order', order_id=order.id), code=302)


def load_order(order_id):
    cached = redis_store.get_cached_order(order_id)
    if cached is not None:
        return cached
    order = Order.get_or_none(id=order_id)
    return order.to_dict() if order else None


@app.route('/order/<int:order_id>', methods=['GET'])
def get_order(order_id):
    order = load_order(order_id)
    if order is None:
        return error(*ORDER_NOT_FOUND)
    return jsonify({"order": order})


@app.route('/order/<int:order_id>', methods=['PUT'])
def put_order(order_id):
    data = request.get_json(silent=True) or {}
    order = Order.get_or_none(id=order_id)

    if order is None:
        return error(*ORDER_NOT_FOUND)

    if 'order' not in data:
        if 'credit_card' not in data:
            return error(*ORDER_MISSING_FIELDS)

        card_data = data['credit_card']
        if not all(k in card_data for k in ('number', 'expiration_year', 'expiration_month', 'cvv', 'name')):
            return error(*ORDER_MISSING_FIELDS)

        if order.email is None or order.shipping_information is None:
            return error(*CLIENT_INFO_REQUIRED)

        if order.paid:
            return error('order', 'already-paid', 'La commande a déjà été payée', 422)

        amount_charged = order.total_price + order.shipping_price
        transaction, err = charge_card(card_data, amount_charged)
        if err:
            return jsonify(err), 422

        with db.atomic():
            order.paid = True
            order.transaction = Transaction.create(id=transaction['id'], amount_charged=amount_charged, success=transaction['success'])
            order.credit_card = CreditCard.create(number=card_data['number'], expiration_year=card_data['expiration_year'], expiration_month=card_data['expiration_month'], cvv=card_data['cvv'], name=card_data['name'])
            order.save()

        order_dict = order.to_dict()
        redis_store.record_order_paid(order_dict, amount_charged)
        return jsonify({"order": order_dict})

    data = data['order']
    if 'shipping_information' not in data or 'email' not in data:
        return error(*ORDER_MISSING_FIELDS)

    ship_data = data['shipping_information']
    if not all(k in ship_data for k in ('country', 'address', 'postal_code', 'city', 'province')):
        return error(*ORDER_MISSING_FIELDS)

    with db.atomic():
        order.shipping_information = ShippingInformation.create(country=ship_data['country'], address=ship_data['address'], postal_code=ship_data['postal_code'], city=ship_data['city'], province=ship_data['province'])
        order.email = data['email']
        order.save()

    order_dict = order.to_dict()
    redis_store.record_order_updated(order_dict)
    return jsonify({"order": order_dict})


# ---------------------------------------------------------------- Web

@app.route('/web', methods=['GET'])
def show_products():
    products = get_products().json['products']
    return render_template('products.html', products=products)


@app.route('/web/order', methods=['GET'])
def show_order_form():
    return render_template('orderForm.html')


@app.route('/web/order', methods=['POST'])
def submit_order_form():
    return post_order()


@app.route('/web/order/<int:order_id>', methods=['GET'])
def show_order(order_id):
    order = load_order(order_id)
    if order is None:
        return error(*ORDER_NOT_FOUND)
    return render_template('orderInfo.html', order=with_product_details(order))


@app.route('/web/checkOrder', methods=['GET'])
def show_check_order_form():
    return render_template('checkOrder.html')


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
