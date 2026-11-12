from flask import Flask, jsonify, request, redirect, url_for, render_template
from models import *
import requests
import redis
import json
import os
import sys


app = Flask(__name__)

db_name = os.environ.get('DB_NAME')
db_user = os.environ.get('DB_USER')
db_password = os.environ.get('DB_PASSWORD')
db_host = os.environ.get('DB_HOST')
db_port = os.environ.get('DB_PORT')
redis_host = os.environ.get('REDIS_URL')
PRODUCTS_FILE = os.environ.get(
    'PRODUCTS_FILE',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'products.json')
)
r = redis.Redis(host=redis_host, port=6379, decode_responses=True)


@app.route('/', methods=['GET'])
def get_products():
    products = Product.select().dicts()
    return jsonify({"products": list(products)})
    

@app.route('/web', methods=['GET'])
def show_products():
    products = get_products().json['products']
    return render_template('products.html', products=products)

@app.route('/web/order', methods=['GET'])
def show_order_form():
    return render_template('orderForm.html')


@app.route('/order', methods=['POST'])
def post_order():
    try :
        data = request.get_json()

        total_price = 0
        total_weight = 0

        if 'products' not in data and 'product' not in data:
            return jsonify({'errors': {'products': {'code': 'missing-fields', 'name': 'La création d\'une commande nécessite un produit'}}}), 422

        if 'products' in data:
            product_data = data['products']
            order_items  = []

            for product_data in product_data:
            
                if 'id' not in product_data or 'quantity' not in product_data:
                    return jsonify({'errors': {'products': {'code': 'missing-fields', 'name': 'La création d\'une commande nécessite un produit'}}}), 422

                product_id = product_data['id']
                quantity = product_data['quantity']

                if quantity < 1:
                    return jsonify({'errors': {'products': {'code': 'missing-fields', 'name': 'La création d\'une commande nécessite un produit'}}}), 422

                product = Product.get_or_none(id=product_id)

                if product is None or not product.in_stock:
                    return jsonify({'errors': {'products': {'code': 'out-of-inventory', 'name': 'Le produit demandé n\'est pas en inventaire'}}}), 422

                total_price += product.price * quantity
                total_weight += product.weight * quantity

                order_item = OrderItem.create(product=product, quantity=quantity) 
                order_items.append(order_item)

            if total_weight < 0.5 :
                shipping_price = 5
            elif total_weight < 2 :
                shipping_price = 10
            else :
                shipping_price = 25
            
            for order_item in order_items:
                order_item.save()

            order = Order.create(total_price=total_price, shipping_price=shipping_price, paid=False, email=None, credit_card=None, shipping_information=None)
            order.order_items.add(order_items)
            
        elif 'product' in data:
            product_data = data['product']
            product_id = product_data['id']
            quantity = product_data['quantity']

            if quantity < 1:
                return jsonify({'errors': {'products': {'code': 'missing-fields', 'name': 'La création d\'une commande nécessite un produit'}}}), 422

            product = Product.get_or_none(id=product_id)

            if product is None or not product.in_stock:
                return jsonify({'errors': {'products': {'code': 'out-of-inventory', 'name': 'Le produit demandé n\'est pas en inventaire'}}}), 422

            total_price += product.price * quantity
            total_weight += product.weight * quantity

            if total_weight < 0.5 :
                shipping_price = 5
            elif total_weight < 2 :
                shipping_price = 10
            else :
                shipping_price = 25

            order_item = OrderItem.create(product=product, quantity=quantity)
            order = Order.create(total_price=total_price, shipping_price=shipping_price, paid=False, email=None, credit_card=None, shipping_information=None)
            order.order_items.add(order_item) 
            
        return redirect(url_for('get_order', order_id=order.id), code=302)
    
    except Exception :
        product_id1 = request.form.get('productId')
        quantity1 = int(request.form.get('quantity', 0))
        product_id2 = request.form.get('productId2')
        quantity2 = int(request.form.get('quantity2', 0))

        if quantity1 < 1 and quantity2 < 1:
            return jsonify({'errors': {'products': {'code': 'missing-fields', 'name': 'La création d\'une commande nécessite un produit'}}}), 422
        
        product1 = Product.get_or_none(id=product_id1)
        product2 = Product.get_or_none(id=product_id2)

        if product1 is None or not product1.in_stock or product2 is None or not product2.in_stock:
            return jsonify({'errors': {'products': {'code': 'out-of-inventory', 'name': 'Le produit demandé n\'est pas en inventaire'}}}), 422
        
        total_price = product1.price * quantity1 + product2.price * quantity2
        total_weight = product1.weight * quantity1 + product2.weight * quantity2

        if total_weight < 0.5 :
            shipping_price = 5
        elif total_weight < 2 :
            shipping_price = 10
        else :
            shipping_price = 25

        order_item1 = OrderItem.create(product=product1, quantity=quantity1)
        order_item2 = OrderItem.create(product=product2, quantity=quantity2)
        order = Order.create(total_price=total_price, shipping_price=shipping_price, paid=False, email=None, credit_card=None, shipping_information=None)
        order.order_items.add([order_item1, order_item2])

        order_data = order.to_dict()

        for item in order_data['products']:
            product = Product.get_or_none(id=item['product'])
            if product:
                item['name'] = product.name
                item['price'] = product.price

        return render_template('orderInfo.html', order=order_data)
    

@app.route('/order/<int:order_id>', methods=['GET'])
def get_order(order_id):
    if (r.get('order:' + str(order_id)) is not None):
        return json.loads(r.get('order:' + str(order_id)))
    try:
        order = Order.get(id=order_id)
        return {"order": order.to_dict()}
    
    except Order.DoesNotExist or order_id is None:
        return jsonify({'errors': {'order': {'code': 'not-found', 'name': 'La commande demandée n\'existe pas'}}}), 404
    
        
@app.route('/web/order/<int:order_id>', methods=['GET'])
def show_order(order_id):
    order_data = get_order(order_id)
    order_data = order_data['order']
    if order_data:
        for item in order_data['products']:
            product = Product.get_or_none(id=item['product'])
            if product:
                item['name'] = product.name
                item['price'] = product.price
        return render_template('orderInfo.html', order=order_data)
    else:
        return jsonify({'error': 'Order not found'}), 404
    

@app.route('/web/checkOrder', methods=['GET'])
def show_check_order_form():
    return render_template('checkOrder.html')

    
@app.route('/order/<int:order_id>', methods=['PUT'])
def put_order(order_id):
    data = request.get_json()
    order = Order.get_or_none(id=order_id)

    if order is None:
        return jsonify({'errors': {'order': {'code': 'not-found', 'name': 'La commande demandée n\'existe pas'}}}), 404

    if 'order' not in data:
        if 'credit_card' not in data:
            return jsonify({'errors': {'order': {'code': 'missing-fields', 'name': 'Il manque un ou plusieurs champs qui sont obligatoires'}}}), 422

        card_data = data['credit_card']

        if 'number' not in card_data or 'expiration_year' not in card_data or 'expiration_month' not in card_data or 'cvv' not in card_data or 'name' not in card_data :
            return jsonify({'errors': {'order': {'code': 'missing-fields', 'name': 'Il manque un ou plusieurs champs qui sont obligatoires'}}}), 422
        
        if order.email is None or order.shipping_information is None:
            return jsonify({'errors': {'order': {'code': 'missing-fields', 'name': 'Les informations du client sont necessaires avant d\'appliquer une carte de credit'}}}), 422
        
        if order.shipping_information.country is None or order.shipping_information.address is None or order.shipping_information.postal_code is None or order.shipping_information.city is None or order.shipping_information.province is None:
            return jsonify({'errors': {'order': {'code': 'missing-fields', 'name': 'Les informations du client sont necessaires avant d\'appliquer une carte de credit'}}}), 422

        amount_charged = order.total_price + order.shipping_price
        body = {"credit_card": card_data, 'amount_charged': amount_charged}
        req = requests.post('http://dimprojetu.uqac.ca/~jgnault/shops/pay/', json=body)
        req = req.json()
        
        if 'errors' in req:
            return jsonify(req), 422
        
        transaction = req['transaction']
        order.paid = True
        order.transaction = Transaction.create(id=transaction['id'], amount_charged=amount_charged, success = transaction['success'])
        order.credit_card = CreditCard.create(number=card_data['number'], expiration_year=card_data['expiration_year'], expiration_month=card_data['expiration_month'], cvv=card_data['cvv'], name=card_data['name'])    
        order.save()

        r.set('order:' + str(order.id), json.dumps({"order" : order.to_dict()}))

        return jsonify({"order" : order.to_dict()})
    
    data = data['order']
    
    if 'shipping_information' not in data or 'email' not in data :
        return jsonify({'errors': {'order': {'code': 'missing-fields', 'name': 'Il manque un ou plusieurs champs qui sont obligatoires'}}}), 422
        
    ship_data = data['shipping_information']

    if 'country' not in ship_data or 'address' not in ship_data or 'postal_code' not in ship_data or 'city' not in ship_data or 'province' not in ship_data:
        return jsonify({'errors': {'order': {'code': 'missing-fields', 'name': 'Il manque un ou plusieurs champs qui sont obligatoires'}}}), 422

    order.shipping_information = ShippingInformation.create(country=ship_data['country'], address=ship_data['address'], postal_code=ship_data['postal_code'], city=ship_data['city'], province=ship_data['province'])
    order.email = data['email']
    order.save()

    return jsonify({"order" : order.to_dict()})


if __name__ == '__main__':

    db = PostgresqlDatabase(
        database=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )

    db.connect()
    db.create_tables([Product, OrderItem, CreditCard, ShippingInformation, Order, Transaction], safe=True)
    OrderOrderItemThrough = OrderItem.orders.get_through_model()
    OrderOrderItemThrough.create_table(safe=True)

    with open(PRODUCTS_FILE, encoding='utf-8') as f:
        products = json.load(f)['products']

    for product in products:
        if Product.get_or_none(id=product['id']) is None:
            if "\x00" in product["description"]:
                product["description"] = product["description"].replace("\x00", "")
            Product.create(id=product['id'], name=product['name'], type=product['type'], description=product['description'], image=product['image'], price=product['price'], weight=product['weight'], height=product['height'], in_stock=product['in_stock'])

    app.run(debug=True, host='0.0.0.0', port=5000)