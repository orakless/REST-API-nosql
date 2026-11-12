from peewee import *
import json
import logging
import os
import time


db_name = os.environ.get('DB_NAME')
db_user = os.environ.get('DB_USER')
db_password = os.environ.get('DB_PASSWORD')
db_host = os.environ.get('DB_HOST')
db_port = os.environ.get('DB_PORT')

db = PostgresqlDatabase(
        database=db_name,
        user=db_user,
        password=db_password,
        host=db_host,
        port=db_port
    )

class BaseModel(Model):
    class Meta:
        database = db


class Product(BaseModel):
    id = IntegerField(primary_key=True)
    name = CharField()
    type = CharField()
    description = TextField()
    image = CharField()
    height = IntegerField()
    weight = IntegerField()
    price = FloatField()
    in_stock = BooleanField()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'image': self.image,
            'height': self.height,
            'weight': self.weight,
            'price': self.price,
            'in_stock': self.in_stock
        }
       

class CreditCard(BaseModel):
    name = CharField()
    number = CharField()
    expiration_year = IntegerField()
    cvv = CharField(3)
    expiration_month = IntegerField()

    def to_dict(self):
        return {
            'name': self.name,
            'number': self.number,
            'expiration_year': self.expiration_year,
            'cvv': self.cvv,
            'expiration_month': self.expiration_month
        }

class Transaction(BaseModel):
    id = CharField(primary_key=True)
    success = BooleanField()
    amount_charged =FloatField()

    def to_dict(self):
        return {
            'id': self.id,
            'success': self.success,
            'amount_charged': self.amount_charged
        }
        

class ShippingInformation(BaseModel):
    country = CharField()
    address = CharField()
    postal_code = CharField()
    city = CharField()
    province = CharField()

    def to_dict(self):
        return {
            'country': self.country,
            'address': self.address,
            'postal_code': self.postal_code,
            'city': self.city,
            'province': self.province
        }
    

class OrderItem(BaseModel):
    product = ForeignKeyField(Product, backref='order_items')  
    quantity = IntegerField()

    def to_dict(self):
        return {
            'id': self.id,
            'product': self.product.id,
            'quantity': self.quantity
        }
        


class Order(BaseModel):
    id = AutoField(primary_key=True)
    total_price = FloatField()
    email = CharField(null=True)
    credit_card = ForeignKeyField(CreditCard, backref='orders', null=True)
    shipping_information = ForeignKeyField(ShippingInformation, backref='orders', null=True)
    paid = BooleanField()
    transaction = ForeignKeyField(Transaction, backref='orders', null=True)
    shipping_price = IntegerField()
    order_items = ManyToManyField(OrderItem, backref='orders')

    def to_dict(self):
        return {
            'id': self.id,
            'total_price': self.total_price,
            'email': self.email,
            'credit_card': self.credit_card.to_dict() if self.credit_card is not None else {},  
            'shipping_information': self.shipping_information.to_dict() if self.shipping_information is not None else {},
            'transaction': self.transaction.to_dict() if self.transaction is not None else {},
            'paid': self.paid,
            'shipping_price': self.shipping_price,
            'products': [orderItem.to_dict() for orderItem in self.order_items]
        }




OrderOrderItemThrough = Order.order_items.get_through_model()

ALL_TABLES = [Product, OrderItem, CreditCard, ShippingInformation, Transaction, Order, OrderOrderItemThrough]


def wait_for_db(retries=15, delay=2):
    """Attend que PostgreSQL accepte les connexions (utile au démarrage docker)."""
    for attempt in range(1, retries + 1):
        try:
            db.connect(reuse_if_open=True)
            return
        except OperationalError as e:
            logging.warning("PostgreSQL indisponible (tentative %s/%s) : %s", attempt, retries, e)
            time.sleep(delay)
    raise RuntimeError("Impossible de se connecter à PostgreSQL")


def seed_products(products_file):
    with open(products_file, encoding='utf-8') as f:
        products = json.load(f)['products']

    for product in products:
        if Product.get_or_none(id=product['id']) is None:
            if "\x00" in product["description"]:
                product["description"] = product["description"].replace("\x00", "")
            Product.create(id=product['id'], name=product['name'], type=product['type'], description=product['description'], image=product['image'], price=product['price'], weight=product['weight'], height=product['height'], in_stock=product['in_stock'])


def init_db(products_file):
    """Crée les tables (idempotent) et importe les produits du JSON."""
    wait_for_db()
    with db.atomic():
        db.create_tables(ALL_TABLES, safe=True)
        seed_products(products_file)
    db.close()
