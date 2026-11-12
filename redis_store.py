"""Couche Redis : historique, journal d'événements, statistiques et cache.

PostgreSQL reste la source de vérité. Redis stocke (sans expiration, persisté via AOF) :
  - order:<id>                 Hash   résumé lisible de la commande + JSON complet (champ `data`)
  - orders:recent              List   ids des 50 dernières commandes
  - customer:<email>:orders    ZSet   commandes d'un client (score = timestamp)
  - orders:events              Stream journal created / updated / paid
  - products:sales             ZSet   quantités vendues par produit
  - stats:orders / stats:revenue      compteurs
et en cache (avec TTL) :
  - cache:products             String catalogue JSON, 5 min

Toute erreur Redis est loguée sans faire échouer la requête : Postgres a déjà persisté.
"""
import json
import logging
import os
import time

import redis

REDIS_HOST = os.environ.get('REDIS_URL', 'localhost')
REDIS_PORT = int(os.environ.get('REDIS_PORT', 6379))
RECENT_ORDERS_MAX = 50
PRODUCTS_CACHE_TTL = 300

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
log = logging.getLogger(__name__)


def _safe(default=None):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except redis.RedisError as e:
                log.warning("Redis indisponible (%s) : %s", fn.__name__, e)
                return default
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


def _order_hash(order_dict):
    return {
        'id': order_dict['id'],
        'email': order_dict['email'] or '',
        'total_price': order_dict['total_price'],
        'shipping_price': order_dict['shipping_price'],
        'paid': int(bool(order_dict['paid'])),
        'updated_at': int(time.time()),
        'data': json.dumps(order_dict),
    }


def _write_order(pipe, order_dict, event):
    key = f"order:{order_dict['id']}"
    pipe.hset(key, mapping=_order_hash(order_dict))
    pipe.hsetnx(key, 'created_at', int(time.time()))
    pipe.xadd('orders:events', {'type': event, 'order_id': order_dict['id']})


@_safe()
def record_order_created(order_dict):
    pipe = r.pipeline()
    _write_order(pipe, order_dict, 'created')
    pipe.lpush('orders:recent', order_dict['id'])
    pipe.ltrim('orders:recent', 0, RECENT_ORDERS_MAX - 1)
    for item in order_dict['products']:
        pipe.zincrby('products:sales', item['quantity'], item['product'])
    pipe.incr('stats:orders')
    pipe.execute()


@_safe()
def record_order_updated(order_dict):
    pipe = r.pipeline()
    _write_order(pipe, order_dict, 'updated')
    if order_dict['email']:
        pipe.zadd(f"customer:{order_dict['email']}:orders", {order_dict['id']: time.time()})
    pipe.execute()


@_safe()
def record_order_paid(order_dict, amount_charged):
    pipe = r.pipeline()
    _write_order(pipe, order_dict, 'paid')
    pipe.incrbyfloat('stats:revenue', amount_charged)
    pipe.execute()


@_safe()
def get_cached_order(order_id):
    data = r.hget(f"order:{order_id}", 'data')
    return json.loads(data) if data else None


@_safe(default=[])
def get_recent_orders(limit=10):
    ids = r.lrange('orders:recent', 0, limit - 1)
    pipe = r.pipeline()
    for order_id in ids:
        pipe.hgetall(f"order:{order_id}")
    orders = []
    for h in pipe.execute():
        if h:
            h.pop('data', None)
            orders.append(h)
    return orders


@_safe(default=[])
def get_customer_orders(email):
    return [int(i) for i in r.zrevrange(f"customer:{email}:orders", 0, -1)]


@_safe(default=[])
def get_top_products(limit=5):
    return [{'product': int(pid), 'quantity': int(qty)}
            for pid, qty in r.zrevrange('products:sales', 0, limit - 1, withscores=True)]


@_safe(default={})
def get_stats():
    orders, revenue = r.mget('stats:orders', 'stats:revenue')
    return {'orders': int(orders or 0), 'revenue': round(float(revenue or 0), 2)}


@_safe()
def get_cached_products():
    data = r.get('cache:products')
    return json.loads(data) if data else None


@_safe()
def cache_products(products):
    r.set('cache:products', json.dumps(products), ex=PRODUCTS_CACHE_TTL)
