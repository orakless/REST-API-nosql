# REST-API NoSQL

Application Flask de commandes en ligne. Chaque commande est persistée dans **PostgreSQL** et **Redis** (historique, événements, statistiques, cache).

[Hebergé ici](https://nosql.mudakle.fr/web)

## Lancer

```bash
git clone <url-du-repo> && cd REST-API-nosql
docker compose up --build
```

Les tables sont créées et les produits (`products.json`) importés automatiquement au démarrage.

## Interface web

| Page | URL |
|---|---|
| Produits | http://localhost:5000/web |
| Passer une commande (formulaire) | http://localhost:5000/web/order |
| Consulter une commande / historique client | http://localhost:5000/web/checkOrder |
| Historique récent + statistiques | http://localhost:5000/web/history |

API JSON : `/` (produits), `/order/<id>`, `/orders/recent`, `/products/top`, `/customers/<email>/orders`.

Paiement simulé : carte `4242 4242 4242 4242` acceptée, toute autre refusée.

## Constater la persistance

**Terminal 1 — PostgreSQL**
```bash
docker compose exec postgresql psql -U postgres -d API_REST
```
```sql
\dt
SELECT id, total_price, shipping_price, paid, email FROM "order";
```

**Terminal 2 — Redis**
```bash
docker compose exec redis redis-cli
```
```
KEYS *
HGETALL order:1
LRANGE orders:recent 0 -1
XRANGE orders:events - +
ZREVRANGE products:sales 0 4 WITHSCORES
MGET stats:orders stats:revenue
```

## Arrêter

```bash
docker compose down      # garde les données
docker compose down -v   # supprime aussi les volumes
```
