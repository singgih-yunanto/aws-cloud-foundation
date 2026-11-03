#!/usr/bin/env python3
"""Mengisi koleksi `orders` di DocumentDB untuk setiap peserta (dijalankan trainer, sekali, dari instance di VPC yang sama).

Pemakaian:
  pip3 install boto3 pymongo
  python3 seed-orders.py trainee1 trainee2 trainee3 trainee4 [--docs 50000]
Secret `lab/docdb` berisi {"username","password","host","port"}. CA bundle: /opt/lab-app/global-bundle.pem
Koleksi dibuat TANPA indeks pada customer_id agar query /checkout terasa lambat (titik lambat untuk Lab 6 Bagian B).
"""
import argparse, json, random, sys
import boto3, pymongo

ap = argparse.ArgumentParser()
ap.add_argument("users", nargs="+")
ap.add_argument("--docs", type=int, default=50000)
ap.add_argument("--secret", default="lab/docdb")
ap.add_argument("--region", default="ap-southeast-3")
ap.add_argument("--ca", default="/opt/lab-app/global-bundle.pem")
a = ap.parse_args()

s = json.loads(boto3.client("secretsmanager", region_name=a.region).get_secret_value(SecretId=a.secret)["SecretString"])
uri = "mongodb://%s:%s@%s:%s/?tls=true&tlsCAFile=%s&replicaSet=rs0&retryWrites=false" % (
    s["username"], s["password"], s["host"], s.get("port", 27017), a.ca)
client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)

for u in a.users:
    safe = "".join(c for c in u if c.isalnum() or c in "-_")[:30]
    coll = client["lab_" + safe].orders
    coll.drop()
    batch = []
    for i in range(a.docs):
        batch.append({"order_id": i, "customer_id": random.randint(1, 5000), "amount": random.randint(10, 900) * 1000,
                      "status": random.choice(["paid", "shipped", "new"]), "note": "x" * 120})
        if len(batch) == 5000:
            coll.insert_many(batch); batch = []
    if batch:
        coll.insert_many(batch)
    print("lab_%s.orders: %d dokumen, indeks: %s" % (safe, coll.count_documents({}), list(coll.index_information())))
